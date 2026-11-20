#!/usr/bin/env python3
import asyncio
import sys

from _harness import fresh_graph


def install_plan_apply_hook(graph, hook, *, fire_on_call=1):
    """Run a coroutine once at a maintenance or judge plan/apply boundary.

    A capability reads the store to build its plan, then calls the client write path to apply it. This wraps
    that write path so the hook runs just before the chosen apply transaction, which is where a concurrent
    delete and recreate of the same id, a cancelled waiter, or a second writer must not corrupt the result.

    @param graph (SelfGraph): the graph whose next apply to interleave.
    @param hook (Callable[[], Awaitable]): the coroutine factory to run once at the boundary.
    @param fire_on_call (int): the 1-based write call to fire before; the first by default.
    @return (Callable[[], None]): restores the original write path.
    """
    original = graph._write
    state = {"n": 0, "fired": False}

    async def wrapped(op, *args, **kwargs):
        state["n"] += 1
        if not state["fired"] and state["n"] == fire_on_call:
            state["fired"] = True
            await hook()
        return await original(op, *args, **kwargs)

    graph._write = wrapped

    def uninstall():
        graph._write = original

    return uninstall


async def _seed(graph):
    """Create two entities and one low relevance relation ready to prune.

    @param graph (SelfGraph): the graph to seed.
    @return (None): nothing.
    """
    from datetime import datetime, timezone

    await graph.entities.create("A", "T", id="t:a")
    await graph.entities.create("B", "T", id="t:b")
    await graph.relations.create("t:a", "KNOWS", "t:b", id="relation:r")
    await graph.maintenance.decay(now=datetime.now(timezone.utc), half_life_days=1e-9, dry_run=False)


async def probe_delete_recreate_during_prune():
    """Delete and recreate a relation between prune's plan and its apply, then report the outcome.

    @return (dict): the planned relation ids, whether the recreated relation survived, and a verdict.
    """
    from selfgraph import SelfGraph

    graph = fresh_graph()
    await graph.initialize()
    await _seed(graph)

    planned = await graph.maintenance.prune(min_relevance=1.0, relation_types=["KNOWS"], dry_run=True)

    side = SelfGraph(store=graph.store, namespace="probe")

    async def hook():
        await side.relations.delete("relation:r")
        await side.relations.create("t:a", "KNOWS", "t:b", id="relation:r")

    uninstall = install_plan_apply_hook(graph, hook)
    try:
        applied = await graph.maintenance.prune(min_relevance=1.0, relation_types=["KNOWS"], dry_run=False)
    finally:
        uninstall()

    survivor = await graph.relations.get("relation:r")
    survived = survivor is not None
    verdict = (
        "the fresh relation survived; the apply re-checked current state"
        if survived
        else "the recreated relation was removed by the stale plan; the apply acted on planned state"
    )
    await graph.close()
    await side.close()
    return {
        "planned_relation_ids": planned.relation_ids,
        "applied_relation_ids": applied.relation_ids,
        "recreated_survived": survived,
        "verdict": verdict,
    }


def main():
    """Run the plan/apply interleaving demonstration and print the outcome.

    @return (int): always 0; the probe reports behaviour, it does not assert a verdict.
    """
    result = asyncio.run(probe_delete_recreate_during_prune())
    print("plan/apply interleaving: prune, delete and recreate relation:r at the boundary")
    print(f"       planned to remove: {result['planned_relation_ids']}")
    print(f"       applied removed:   {result['applied_relation_ids']}")
    print(f"       relation:r after:  {'present' if result['recreated_survived'] else 'gone'}")
    print(f"       {result['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
