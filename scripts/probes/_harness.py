import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))


def fresh_graph(resolver=None):
    """Open a SelfGraph over a fresh temporary Kuzu store in namespace 'probe'.

    @param resolver (str | None): the entity resolver mode, or None for the default.
    @return (SelfGraph): an uninitialized graph.
    """
    from selfgraph import KuzuStore, SelfGraph

    path = tempfile.mkdtemp(prefix="sg-probe-")
    options = {"namespace": "probe"}
    if resolver is not None:
        options["resolver"] = resolver
    return SelfGraph(store=KuzuStore(os.path.join(path, "g.kuzu")), **options)
