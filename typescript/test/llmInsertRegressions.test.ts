import { expect, it } from "vitest";
import { HINTS } from "../src/errors.js";
import { ExtractionError, type LLMClient } from "../src/index.js";
import { freshGraphs, KUZU_SPEC } from "./helpers.js";

const graph = freshGraphs(KUZU_SPEC, "llm_regression");
const entities = ["A", "B", "C"].map((name) => ({ type: "T", name }));
const relation = { from_entity: "t:a", type: "KNOWS", to_entity: "t:c" };

function client(reply: unknown, properties: Record<string, unknown> = {}): LLMClient {
  return {
    async generate({ output }) {
      const fields = (output as unknown as { shape: Record<string, unknown> }).shape;
      const result =
        "retired" in fields
          ? reply
          : "entities" in fields
            ? { entities: entities.map((e) => ({ ...e, aliases: [] })) }
            : "relations" in fields
              ? { relations: [{ from_name: "A", type: "KNOWS", to_name: "C", properties, event_time: null }] }
              : "preferences" in fields
                ? { preferences: [] }
                : { decisions: [] };
      return result as never;
    },
  };
}

it.each(["", "   "])("339 drops empty extracted property %j", async (key) => {
  const g = graph({ llm: client({}, { [key]: "bad", since: 2020 }), extraction: "llm" });
  const result = await g.insert.text("A knows C.");
  expect(result.entities).toHaveLength(3);
  expect(result.relations.map((r) => r.properties)).toEqual([{ since: 2020 }]);
  expect(result.warnings).toHaveLength(1);
  expect(result.warnings[0]).toMatchObject({
    code: "extraction_partial_failure",
    message: "dropped an extracted relation property: properties keys cannot be empty or whitespace",
  });
});

for (const operation of ["facts", "text", "create"]) {
  it.each([{ retired: "bad" }, { retired: [null] }])(
    `336 ${operation} rejects verdict %j before writes`,
    async (reply) => {
      const g = graph({ llm: client(reply), extraction: "llm", contradiction: "llm" });
      await g.insert.facts({ entities, relations: [{ ...relation, to_entity: "t:b" }] });
      const before = (await g.relations.list()).items;
      const write =
        operation === "text"
          ? () => g.insert.text("A knows C.", { source_id: "new-source" })
          : operation === "create"
            ? () => g.relations.create("t:a", "KNOWS", "t:c")
            : () =>
                g.insert.facts(
                  { entities: [{ type: "T", name: "D" }], relations: [relation] },
                  { source_id: "new-source" },
                );
      const error = await write().catch((error: unknown) => error);
      expect((await g.relations.list()).items).toEqual(before);
      expect(await g.entities.get("t:d")).toBeNull();
      expect(await g.store.getNode(g.namespace, "Source", "new-source")).toBeNull();
      expect(error).toMatchObject({
        name: new ExtractionError("").name,
        code: "invalid_llm_output",
        field: "retired",
        hint: HINTS.invalid_llm_output,
        message: "LLM client returned an invalid contradiction verdict",
      });
    },
  );
}
