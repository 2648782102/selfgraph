import { createServer } from "node:http";
import type { AddressInfo } from "node:net";

import { describe, expect, it } from "vitest";
import { z } from "zod";

import { pyRepr } from "../src/internal/py.js";
import { buildLlmClient } from "../src/llm/index.js";

/**
 * Call an LLM provider that answers every request with one HTTP status.
 *
 * @param status (number): the status.
 * @return (Promise<string>): the error message.
 */
async function providerMessage(status: number): Promise<string> {
  const server = createServer((_req, res) => res.writeHead(status, { "Content-Type": "application/json" }).end("{}"));
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const { port } = server.address() as AddressInfo;
    const base_url = `http://127.0.0.1:${port}`;
    const llm = buildLlmClient({ provider: "openai", model: "gpt-x", api_key: "k", base_url, max_retries: 0 });
    await llm.generate({ system: "", user: "x", output: z.object({ ok: z.boolean() }) });
    throw new Error("provider call did not fail");
  } catch (exc) {
    return exc instanceof Error ? exc.message : String(exc);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

describe("LLM error quoting", () => {
  it.each([
    [403, "LLM access denied for provider openai and model 'gpt-x':"],
    [404, "LLM model 'gpt-x' was not found for provider openai"],
  ])("quotes the model like Python on HTTP %i", async (status, expected) => {
    expect(await providerMessage(status)).toContain(expected);
    expect(await providerMessage(status)).not.toContain(JSON.stringify("gpt-x"));
    expect(pyRepr("gpt-x")).toBe("'gpt-x'");
  });
});
