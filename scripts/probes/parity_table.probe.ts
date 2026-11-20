import { writeFileSync } from "node:fs";

import { test } from "vitest";

import {
  entityId,
  type JsonValue,
  KuzuStore,
  SelfGraph,
  SelfGraphError,
  toJsonable,
} from "../../typescript/src/index.js";
import { jsonIso } from "../../typescript/src/internal/time.js";

type Case = [string, string, unknown];

const CASES: Case[] = [
  ["null_value", "prop_value", null],
  ["int_2p53_minus_1", "prop_value", 9007199254740991],
  ["int_2p53", "prop_value", 9007199254740992],
  ["int_2p53_plus_1", "prop_value", Number("9007199254740993")],
  ["float_1e21", "prop_value", 1e21],
  ["float_neg_1e20", "prop_value", -1e20],
  ["astral_value", "prop_value", "a\u{1f600}b"],
  ["bom_value", "prop_value", "\ufeffhi"],
  ["dollar_amp_value", "extid_value", "$&"],
  ["proto_key", "extid_key", "__proto__"],
  ["nul_key", "prop_key", "a\u0000b"],
  ["bom_key", "extid_key", "\ufeffk"],
  ["nfkc_name", "name", "Ångström"],
  ["nfkc_lookalike_name", "name", "Ångström"],
  ["bom_astral_name", "name", "\ufeff\u{1f600}X"],
  ["year0000_event_time", "event_time", "0000-01-01T00:00:00+01:00"],
];

/**
 * Mask the run specific namespace in an error message.
 *
 * @param message (string): the error message.
 * @return (string): the message with the namespace masked.
 */
function mask(message: string): string {
  return message.replace(/in namespace '[^']*'/g, "in namespace '<ns>'");
}

/**
 * Run one edge input through the TypeScript SDK on an isolated Kuzu graph.
 *
 * @param op (string): the operation name.
 * @param value (unknown): the edge input.
 * @return (Promise<unknown>): the stored output, or an error descriptor.
 */
async function runCase(op: string, value: unknown): Promise<unknown> {
  const graph = new SelfGraph(new KuzuStore(""), { namespace: "probe" });
  await graph.initialize();
  try {
    if (op === "name") {
      const name = value as string;
      const entity = await graph.entities.create(name, "Person");
      return { id: entityId("Person", name), name: entity.name };
    }
    if (op === "event_time") {
      await graph.entities.create("A", "Person", { id: "t:a" });
      await graph.entities.create("B", "Person", { id: "t:b" });
      const rel = await graph.relations.create("t:a", "KNOWS", "t:b", { event_time: value as string });
      return { event_time: rel.event_time ? jsonIso(rel.event_time) : null };
    }
    if (op === "prop_value") {
      const entity = await graph.entities.create("X", "Person", { properties: { p: value as JsonValue } });
      return { value: toJsonable(entity.properties?.p) };
    }
    if (op === "extid_value") {
      const entity = await graph.entities.create("X", "Person", { external_ids: { k: value as string } });
      return { value: entity.external_ids?.k ?? null };
    }
    if (op === "prop_key") {
      const entity = await graph.entities.create("X", "Person", { properties: { [value as string]: "v" } });
      return { keys: Object.keys(entity.properties ?? {}).sort() };
    }
    if (op === "extid_key") {
      const entity = await graph.entities.create("X", "Person", { external_ids: { [value as string]: "v" } });
      return { keys: Object.keys(entity.external_ids ?? {}).sort() };
    }
    return { error_code: "unknown_op", error_field: null, message: op };
  } catch (exc) {
    if (exc instanceof SelfGraphError) {
      return { error_code: exc.code, error_field: exc.field ?? null, message: mask(exc.message) };
    }
    throw exc;
  } finally {
    await graph.close();
  }
}

test("parity table emits the TypeScript side", async () => {
  const out: Record<string, unknown> = {};
  for (const [id, op, value] of CASES) {
    out[id] = await runCase(op, value);
  }
  const dest = process.env.PARITY_OUT;
  if (dest) writeFileSync(dest, JSON.stringify(out));
});
