#!/usr/bin/env python3
import asyncio
import sys

from _harness import fresh_graph


async def _build(graph):
    """Seed Robert with two aliases that each bring a merge sharing source s1, plus a direct statement.

    @param graph (SelfGraph): the graph to seed.
    @return (dict): the merge records keyed by the absorbed id.
    """
    await graph.insert.facts(
        {"entities": [{"type": "Person", "name": "Robert", "aliases": ["Bob", "Bobby"]}]}, source_id="seed"
    )
    await graph.insert.facts(
        {
            "entities": [{"type": "Person", "name": "Bob"}, {"type": "Person", "name": "Xena"}],
            "relations": [{"from_entity": "person:bob", "type": "KNOWS", "to_entity": "person:xena"}],
        },
        source_id="s1",
    )
    await graph.insert.facts(
        {
            "entities": [{"type": "Person", "name": "Bobby"}],
            "relations": [{"from_entity": "person:bobby", "type": "KNOWS", "to_entity": "person:xena"}],
        },
        source_id="s1",
    )
    await graph.insert.facts(
        {"relations": [{"from_entity": "person:robert", "type": "KNOWS", "to_entity": "person:xena"}]},
        source_id="s1",
    )
    merges = (await graph.entities.merges("person:robert")).items
    return {m.absorbed_id: m for m in merges}


async def _snapshot(graph):
    """Read every current relation and its evidence sources.

    @param graph (SelfGraph): the graph.
    @return (list): sorted (from, type, to, sources) tuples.
    """
    rows = []
    for rel in (await graph.relations.list()).items:
        sources = sorted(e.source_id for e in (await graph.relations.evidence(rel.id)).items)
        rows.append([rel.from_entity, rel.type, rel.to_entity, sources])
    return sorted(rows)


async def _unmerge_in_order(order):
    """Build the scenario, unmerge in the given order, and snapshot the result.

    @param order (list[str]): the absorbed ids to unmerge, in order.
    @return (list): the snapshot after both unmerges.
    """
    graph = fresh_graph("default")
    await graph.initialize()
    merges = await _build(graph)
    for absorbed in order:
        await graph.entities.unmerge(merges[absorbed].id)
    snap = await _snapshot(graph)
    await graph.close()
    return snap


async def _replay_without_aliases():
    """Insert the same evidence with Bob, Bobby, and Robert kept separate, as if no merge happened.

    @return (list): the snapshot of the alias-free graph.
    """
    graph = fresh_graph("default")
    await graph.initialize()
    await graph.insert.facts({"entities": [{"type": "Person", "name": "Robert"}]}, source_id="seed")
    for name in ("bob", "bobby", "robert"):
        await graph.insert.facts(
            {
                "entities": [{"type": "Person", "name": name.capitalize()}, {"type": "Person", "name": "Xena"}],
                "relations": [{"from_entity": f"person:{name}", "type": "KNOWS", "to_entity": "person:xena"}],
            },
            source_id="s1",
        )
    snap = await _snapshot(graph)
    await graph.close()
    return snap


async def run():
    """Unmerge in both orders and compare with each other and with the alias-free replay.

    @return (dict): the three snapshots and the two verdicts.
    """
    forward = await _unmerge_in_order(["person:bob", "person:bobby"])
    reverse = await _unmerge_in_order(["person:bobby", "person:bob"])
    replay = await _replay_without_aliases()
    return {
        "forward": forward,
        "reverse": reverse,
        "replay": replay,
        "order_independent": forward == reverse,
        "matches_replay": forward == replay and reverse == replay,
    }


def main():
    """Run the unmerge order check and print the snapshots and verdicts.

    Order independence is the hard invariant: the two unmerge orders must leave identical provenance.
    The alias-free replay is a diagnostic, since whether a direct statement after a merge creates
    independent provenance is a semantic the reviewer judges.

    @return (int): 0 when the two orders agree, 1 otherwise.
    """
    result = asyncio.run(run())
    print("unmerge order: two merges plus a direct statement share source s1")
    print(f"       forward (unmerge Bob then Bobby): {result['forward']}")
    print(f"       reverse (unmerge Bobby then Bob): {result['reverse']}")
    print(f"       replay (kept separate, no merge):  {result['replay']}")
    if not result["matches_replay"]:
        print("       inspect: unmerge does not restore the alias-free replay (check for lost or empty evidence)")
    if not result["order_independent"]:
        print("\nunmerge order: FAIL, provenance depends on unmerge order")
        return 1
    print("\nunmerge order: order independent" + ("" if result["matches_replay"] else "; replay differs, see inspect"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
