import { comparePy } from "./internal/py.js";
import { epochMicros } from "./internal/time.js";
import { L_ENTITY } from "./labels.js";
import type { GraphDiff, Relation } from "./models.js";
import { edgesAt, keyset, relationOf } from "./ops.js";
import type { GraphPrimitives } from "./protocols.js";
import { decodeEntity } from "./serde.js";

const order = (a: Relation, b: Relation): number => comparePy(a.id, b.id) || a.revision - b.revision;

/**
 * Scan stored changes one page at a time, retaining only changes in the window.
 *
 * @param runner (GraphPrimitives): the graph reader.
 * @param ns (string): the namespace.
 * @param since (Date): exclusive known-time lower bound.
 * @param until (Date): inclusive known-time upper bound.
 * @return (GraphDiff): changes in id and revision order.
 */
export async function graphDiff(runner: GraphPrimitives, ns: string, since: Date, until: Date): Promise<GraphDiff> {
  const result: GraphDiff = {
    since,
    until,
    relations_added: [],
    relations_retired: [],
    relations_revised: [],
    entities_created: [],
    limitations: ["Deletes and merges are not visible."],
  };
  const within = (stamp: Date): boolean =>
    epochMicros(since) < epochMicros(stamp) && epochMicros(stamp) <= epochMicros(until);
  const retired = new Map<string, Relation>();
  for await (const page of keyset((after, limit) => runner.matchNodes(ns, L_ENTITY, { id_gt: after, limit }))) {
    for (const row of page) {
      const entity = decodeEntity(row);
      if (within(entity.created_at)) result.entities_created.push(entity);
    }
    const from = page.map((row) => row.id as string);
    for (const row of await edgesAt(runner, ns, { from_label: L_ENTITY, to_label: L_ENTITY }, "from_in", from)) {
      const relation = relationOf(row);
      if (within(relation.created_at)) {
        (relation.revision === 1 ? result.relations_added : result.relations_revised).push(relation);
      }
      const ended = relation.invalidated_known_at;
      if (ended !== null && within(ended) && epochMicros(relation.created_at) <= epochMicros(ended)) {
        const key = JSON.stringify([relation.id, epochMicros(ended)]);
        const previous = retired.get(key);
        if (!previous || previous.revision < relation.revision) retired.set(key, relation);
      }
    }
  }
  result.relations_added.sort(order);
  result.relations_revised.sort(order);
  result.relations_retired = [...retired.values()].sort(
    (a, b) => comparePy(a.id, b.id) || epochMicros(a.invalidated_known_at!) - epochMicros(b.invalidated_known_at!),
  );
  result.entities_created.sort((a, b) => comparePy(a.id, b.id));
  return result;
}
