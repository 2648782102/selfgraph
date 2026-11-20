import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { version } from "../package.json";
import { HINTS } from "../src/errors.js";
import { Extraction, NotFoundError, StoreError, TransientError } from "../src/index.js";
import { parseOrThrow } from "../src/models.js";
import { checkSettings, settingsFromEnv } from "../src/runtime.js";

/**
 * Each code's section in docs/errors.md, as one line of text.
 *
 * @return (Record<string, string>): the section text by code.
 */
function documented(): Record<string, string> {
  const text = readFileSync(new URL("../../docs/errors.md", import.meta.url), "utf8");
  const sections = text.matchAll(/^#### `(\w+)`\n\n([\s\S]*?)(?=\n#|$(?![\s\S]))/gm);
  return Object.fromEntries([...sections].map((m) => [m[1]!, m[2]!.split(/\s+/).join(" ").trim()]));
}

describe("error codes", () => {
  it("documents every code, with its hint as its docs section", () => {
    expect(documented()).toEqual(HINTS);
  });

  it("carries the code, hint, retryability, and release docs link", () => {
    expect(new NotFoundError("Entity", "person:nobody").toJSON()).toEqual({
      error: "Entity 'person:nobody' does not exist",
      error_type: "NotFoundError",
      code: "not_found",
      hint: HINTS.not_found,
      retryable: false,
      docs: `https://github.com/hydra-db/selfgraph/blob/ts-v${version}/docs/errors.md#not_found`,
    });
    expect([new TransientError().retryable, new StoreError().retryable]).toEqual([true, false]);
  });

  it.each([
    [{ entities: [{ name: "Ada", type: "Person", bogus: 1 }] }, "unknown_key", "entities[0].bogus"],
    [{ entities: [{ type: "Person" }] }, "invalid_argument", "entities[0].name"],
  ] as const)("names the field at fault in %o", (facts, code, field) => {
    expect(() => parseOrThrow(Extraction, facts, "facts")).toThrow(expect.objectContaining({ code, field }));
  });

  it.each([
    [{ store: "bogus" }, "invalid_setting", "store"],
    [{ level: "max" }, "llm_required", undefined],
    [{ schema_mode: "strict" }, "schema_required", undefined],
    [{ llm_timeout: "-1" }, "invalid_setting", "llm_timeout"],
  ] as const)("fails settings %o with %s", (overrides, code, field) => {
    expect(() => checkSettings(settingsFromEnv(overrides, {}))).toThrow(expect.objectContaining({ code, field }));
  });
});
