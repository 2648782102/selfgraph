import { describe, expect, it } from "vitest";

import { DOCS_URL } from "../src/errors.js";
import { NotFoundError, StoreError, TransientError } from "../src/index.js";
import { checkSettings, settingsFromEnv } from "../src/runtime.js";

describe("error codes", () => {
  it("carries the code, retryability, and docs link", () => {
    expect(new NotFoundError("Entity", "person:nobody").toJSON()).toEqual({
      error: "Entity 'person:nobody' does not exist",
      error_type: "NotFoundError",
      code: "not_found",
      retryable: false,
      docs: `${DOCS_URL}#not_found`,
    });
    expect([new TransientError().retryable, new StoreError().retryable]).toEqual([true, false]);
  });

  it.each([
    [{ store: "bogus" }, "invalid_setting"],
    [{ level: "max" }, "llm_required"],
    [{ schema_mode: "strict" }, "schema_required"],
    [{ llm_timeout: "-1" }, "invalid_setting"],
  ] as const)("fails settings %o with %s", (overrides, code) => {
    expect(() => checkSettings(settingsFromEnv(overrides, {}))).toThrow(expect.objectContaining({ code }));
  });
});
