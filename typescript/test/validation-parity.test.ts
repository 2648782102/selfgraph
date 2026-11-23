import { describe, expect, it } from "vitest";
import { HINTS } from "../src/errors.js";
import { KuzuStore, SelfGraph } from "../src/index.js";

const booleanCases = [
  [{ entities: [{ name: "T", certified: null }] }, "entities[0].certified"],
  [{ entities: [{ name: "T", properties: [{ name: "p", required: null }] }] }, "entities[0].properties[0].required"],
  [
    { entities: [{ name: "T", definitions: [{ name: "d", expression: "x", certified: null }] }] },
    "entities[0].definitions[0].certified",
  ],
  [{ relations: [{ type: "R", certified: null }] }, "relations[0].certified"],
] as const;

describe("validation parity", () => {
  for (const [schema, field] of booleanCases) {
    for (const value of ["false", 0, 1]) {
      it(`#376 rejects ${field}=${value}`, async () => {
        const input = JSON.parse(JSON.stringify(schema));
        let target = input.entities?.[0] ?? input.relations[0];
        target = target.properties?.[0] ?? target.definitions?.[0] ?? target;
        target[field.split(".").at(-1)!] = value;
        const store = new KuzuStore(":memory:", { buffer_pool_size: 128 << 20 });
        try {
          await store.initialize();
          expect(() => new SelfGraph(store, { schema: input })).toThrowError(
            expect.objectContaining({
              code: "invalid_argument",
              field,
              hint: HINTS.invalid_argument,
              message: `invalid schema: ${field}: expected boolean`,
            }),
          );
        } finally {
          await store.close();
        }
      });
    }
  }
  for (const offset of ["start_offset", "end_offset"]) {
    for (const value of ["2", true, false]) {
      it(`#376 rejects ${offset}=${value}`, async () => {
        const graph = new SelfGraph(new KuzuStore(":memory:", { buffer_pool_size: 128 << 20 }));
        try {
          await graph.initialize();
          const field = `relations[0].evidence[0].${offset}`;
          await expect(
            graph.insert.facts({
              entities: [
                { type: "T", name: "a" },
                { type: "T", name: "b" },
              ],
              relations: [
                { from_entity: "t:a", type: "R", to_entity: "t:b", evidence: [{ source_id: "s", [offset]: value }] },
              ],
            } as never),
          ).rejects.toMatchObject({
            code: "invalid_argument",
            field,
            hint: HINTS.invalid_argument,
            message: `invalid facts: ${field}: expected number`,
          });
        } finally {
          await graph.close();
        }
      });
    }
  }
});
