import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { version } from "../package.json";
import { HINTS, WARNING_HINTS } from "../src/errors.js";
import { Extraction, KuzuStore, NotFoundError, SelfGraph, StoreError, TransientError } from "../src/index.js";
import { parseOrThrow } from "../src/models.js";
import { checkSettings, settingsFromEnv } from "../src/runtime.js";
import { tempKuzu } from "./helpers.js";

const DOCS = readFileSync(new URL("../../docs/errors.md", import.meta.url), "utf8");

/**
 * The first paragraph of each code section between two second-level headings of docs/errors.md.
 *
 * @param start (string): the heading the sections follow.
 * @param end (string): the heading after them.
 * @return (Record<string, string>): the paragraph by code, as one line of text.
 */
function sections(start: string, end: string): Record<string, string> {
  const part = DOCS.slice(DOCS.indexOf(`\n## ${start}\n`), DOCS.indexOf(`\n## ${end}\n`));
  const found = part.matchAll(/^#### `(\w+)`\n\n([\s\S]*?)(?=\n\n|\n#|$(?![\s\S]))/gm);
  return Object.fromEntries([...found].map((m) => [m[1]!, m[2]!.split(/\s+/).join(" ").trim()]));
}

describe("error codes", () => {
  it("documents every code, with its hint as the first paragraph of its section", () => {
    expect(sections("Codes", "Messages")).toEqual(HINTS);
    expect(sections("Warning codes", "Warnings and logging")).toEqual(WARNING_HINTS);
  });

  it("carries the code, hint, retryability, and both docs links", () => {
    expect(new NotFoundError("Entity", "person:nobody").toJSON()).toEqual({
      error: "Entity 'person:nobody' does not exist",
      error_type: "NotFoundError",
      code: "not_found",
      hint: HINTS.not_found,
      retryable: false,
      docs: `https://github.com/hydra-db/selfgraph/blob/ts-v${version}/docs/errors.md#not_found`,
      agent_guide: "node_modules/@hydradb/selfgraph/errors.md#not_found",
    });
    expect([new TransientError().retryable, new StoreError().retryable]).toEqual([true, false]);
  });

  it("names the namespace and the closest id of the type for a missing entity", async () => {
    const g = new SelfGraph(new KuzuStore(tempKuzu("sg-missing-")), { namespace: "missing" });
    try {
      await g.insert.facts({
        entities: [
          { name: "Ada", type: "Person" },
          { name: "Acme", type: "Company" },
        ],
      });
      await expect(g.entities.update("person:ad", { name: "Ad" })).rejects.toThrow(
        "Entity 'person:ad' does not exist in namespace 'missing'; did you mean 'person:ada'?",
      );
      await expect(g.entities.delete("person:zzzz")).rejects.toThrow(
        /^Entity 'person:zzzz' does not exist in namespace 'missing'$/,
      );
    } finally {
      await g.close();
    }
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
