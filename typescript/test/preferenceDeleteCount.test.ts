import { expect, it } from "vitest";

import { NotFoundError, type SelfGraph } from "../src/index.js";
import { forEachStore, freshGraphs, type StoreSpec } from "./helpers.js";

const POOL = ["kind0:a", "kind1:b", "kind2:c"];
const SHAPES: Record<string, [number, number, number | null]> = {
  distinct: [0, 1, 2],
  subject_is_value: [0, 0, 1],
  subject_is_about: [0, 1, 0],
  value_is_about: [0, 1, 1],
  no_about: [0, 1, null],
};
const SUBSETS = [[0], [1], [2], [0, 1], [0, 2], [1, 2], [0, 1, 2]];
const AUTHORED = 2;
const later = () => new Date(Date.now() + 30_000);

const permutations = (items: number[]): number[][] =>
  items.length <= 1
    ? [items]
    : items.flatMap((item, i) =>
        permutations([...items.slice(0, i), ...items.slice(i + 1)]).map((rest) => [item, ...rest]),
      );

async function poolGraph(
  open: () => SelfGraph,
  shape: [number, number, number | null],
): Promise<{ g: SelfGraph; pid: string; bystander: string }> {
  const g = open();
  for (const [i, eid] of POOL.entries()) await g.entities.create(`E${i}`, `Kind${i}`, { id: eid });
  await g.entities.create("Keep", "Person", { id: "person:keep" });
  const [subject, value, about] = shape;
  const pref = await g.preferences.create(POOL[subject]!, "likes", POOL[value]!, {
    about_entity: about === null ? undefined : POOL[about],
    strength: 0.2,
  });
  await g.preferences.update(pref.id, { strength: 0.4 });
  const bystander = await g.preferences.create("person:keep", "likes", "person:keep");
  return { g, pid: pref.id, bystander: bystander.id };
}

async function expectState(
  g: SelfGraph,
  pid: string,
  bystander: string,
  shape: [number, number, number | null],
  gone: number[],
): Promise<void> {
  const [subject, value, about] = shape;
  expect(await g.preferences.get(bystander)).not.toBeNull();
  expect(await g.preferences.versions(bystander)).toHaveLength(1);
  if (gone.includes(subject) || gone.includes(value)) {
    expect(await g.preferences.get(pid)).toBeNull();
    await expect(g.preferences.versions(pid)).rejects.toBeInstanceOf(NotFoundError);
    return;
  }
  const dropped = about !== null && gone.includes(about);
  expect((await g.preferences.get(pid))!.about_entity).toBe(dropped || about === null ? null : POOL[about]);
  expect(await g.preferences.versions(pid)).toHaveLength(AUTHORED + (dropped ? 1 : 0));
}

function suite(spec: StoreSpec) {
  const open = freshGraphs(spec, "pc");

  for (const [name, shape] of Object.entries(SHAPES)) {
    for (const gone of SUBSETS) {
      it(`counts preference versions the same in every delete order and in prune: ${name} ${gone.join("")}`, async () => {
        const [subject, value] = shape;
        const count = gone.includes(subject) || gone.includes(value) ? AUTHORED : 0;
        for (const order of permutations(gone)) {
          const { g, pid, bystander } = await poolGraph(open, shape);
          let total = 0;
          for (const i of order) total += (await g.entities.delete(POOL[i]!)).deleted_preference_versions;
          expect(total).toBe(count);
          await expectState(g, pid, bystander, shape, gone);
        }
        const { g, pid, bystander } = await poolGraph(open, shape);
        const done = await g.maintenance.prune({
          older_than: later(),
          types: gone.map((i) => `Kind${i}`),
          dry_run: false,
        });
        expect(done.entity_ids).toEqual(gone.map((i) => POOL[i]!).sort());
        expect(done.deleted!.deleted_preference_versions).toBe(count);
        await expectState(g, pid, bystander, shape, gone);
      });
    }
  }

  it("counts a user update after an about cleanup but not the cleanup", async () => {
    const { g, pid } = await poolGraph(open, SHAPES.distinct!);
    expect((await g.entities.delete("kind2:c")).deleted_preference_versions).toBe(0);
    await g.preferences.update(pid, { strength: 0.9 });
    expect((await g.entities.delete("kind1:b")).deleted_preference_versions).toBe(AUTHORED + 1);
    expect(await g.preferences.get(pid)).toBeNull();
  });

  it("does not count the about cleanup when the preference is deleted by id", async () => {
    const { g, pid } = await poolGraph(open, SHAPES.distinct!);
    await g.entities.delete("kind2:c");
    expect(await g.preferences.versions(pid)).toHaveLength(AUTHORED + 1);
    expect((await g.preferences.delete(pid)).deleted_preference_versions).toBe(AUTHORED);
    expect(await g.preferences.get(pid)).toBeNull();
  });

  it("counts an about the user cleared", async () => {
    const { g, pid } = await poolGraph(open, SHAPES.distinct!);
    await g.preferences.update(pid, { clear: ["about_entity"] });
    expect((await g.entities.delete("kind1:b")).deleted_preference_versions).toBe(AUTHORED + 1);
  });
}

await forEachStore("preference delete counts", suite);
