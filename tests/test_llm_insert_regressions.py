import pytest
from helpers import FakeLLM, fresh_graph, run

from selfgraph import ExtractionError
from selfgraph.errors import HINTS


@pytest.fixture
def graph():
    g = fresh_graph(llm=FakeLLM(), extraction="llm", contradiction="llm")
    yield g
    run(g.close())


def extraction(g, properties=None):
    g._llm.responses.update(
        {
            "_EntitiesOut": {"entities": [{"type": "T", "name": n} for n in ("A", "B", "C")]},
            "_RelationsOut": {
                "relations": [{"from_name": "A", "type": "KNOWS", "to_name": "C", "properties": properties or {}}]
            },
        }
    )


@pytest.mark.parametrize("key", ["", "   "])
def test_339_empty_extracted_property(graph, key):
    extraction(graph, {key: "bad", "since": 2020})
    result = run(graph.insert.text("A knows C."))
    assert len(result.entities) == 3
    assert [r.properties for r in result.relations] == [{"since": 2020}]
    [warning] = result.warnings
    assert warning.code == "extraction_partial_failure"
    assert warning.message == "dropped an extracted relation property: properties keys cannot be empty or whitespace"


@pytest.mark.parametrize("operation", ["facts", "text", "create"])
@pytest.mark.parametrize("reply", [{"retired": "bad"}, {"retired": [None]}])
def test_336_invalid_verdict_before_writes(graph, operation, reply):
    run(
        graph.insert.facts(
            {
                "entities": [{"type": "T", "name": n} for n in ("A", "B", "C")],
                "relations": [{"from_entity": "t:a", "type": "KNOWS", "to_entity": "t:b"}],
            }
        )
    )
    before = run(graph.relations.list()).items
    graph._llm.responses["_Verdict"] = reply
    extraction(graph)
    with pytest.raises(Exception) as caught:
        if operation == "text":
            run(graph.insert.text("A knows C.", source_id="new-source"))
        elif operation == "create":
            run(graph.relations.create("t:a", "KNOWS", "t:c"))
        else:
            run(
                graph.insert.facts(
                    {
                        "entities": [{"type": "T", "name": "D"}],
                        "relations": [{"from_entity": "t:a", "type": "KNOWS", "to_entity": "t:c"}],
                    },
                    source_id="new-source",
                )
            )
    assert run(graph.relations.list()).items == before
    assert run(graph.entities.get("t:d")) is None
    assert run(graph.store.get_node(graph.namespace, "Source", "new-source")) is None
    assert isinstance(caught.value, ExtractionError)
    assert (caught.value.code, caught.value.field, caught.value.hint) == (
        "invalid_llm_output",
        "retired",
        HINTS["invalid_llm_output"],
    )
    assert str(caught.value) == "LLM client returned an invalid contradiction verdict"
