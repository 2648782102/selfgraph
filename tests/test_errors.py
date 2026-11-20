import ast
import pathlib
import re
from typing import get_args

import pytest
from helpers import new_graph, run, unique_ns

import selfgraph
from selfgraph import Extraction, NotFoundError, StoreError, TransientError
from selfgraph.errors import HINTS, WARNING_HINTS, ErrorCode, SelfGraphError
from selfgraph.runtime import GraphSettings, check_settings

ROOT = pathlib.Path(__file__).resolve().parent.parent
ERROR_CODES = get_args(ErrorCode)
ERROR_CLASSES = {name for name in selfgraph.__all__ if name.endswith("Error")}
DOCS = (ROOT / "docs" / "errors.md").read_text()


def _python_codes(call_names):
    """Every literal code= a Python call names, plus the code class attributes of the error classes.

    @param call_names (set[str]): the called names to read, such as the error classes or InsertWarning.
    @return (set[str]): the codes.
    """
    found = set()
    for path in (ROOT / "src" / "selfgraph").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in call_names:
                found |= {k.value.value for k in node.keywords if k.arg == "code" and isinstance(k.value, ast.Constant)}
            if isinstance(node, ast.ClassDef) and node.name in call_names:
                found |= {
                    stmt.value.value
                    for stmt in node.body
                    if isinstance(stmt, ast.AnnAssign)
                    and getattr(stmt.target, "id", None) == "code"
                    and isinstance(stmt.value, ast.Constant)
                }
    return found


def _sections(start, end):
    """The first paragraph of each code section between two second-level headings of docs/errors.md.

    @param start (str): the heading the sections follow.
    @param end (str): the heading after them.
    @return (dict[str, str]): the paragraph by code, as one line of text.
    """
    part = DOCS[DOCS.index(f"\n## {start}\n") : DOCS.index(f"\n## {end}\n")]
    found = re.finditer(r"^#### `(\w+)`\n\n(.*?)(?=\n\n|\n#|\Z)", part, re.S | re.M)
    return {m.group(1): " ".join(m.group(2).split()) for m in found}


def test_every_code_is_documented_and_its_hint_is_the_first_paragraph_of_its_section():
    assert _sections("Codes", "Messages") == HINTS
    assert set(HINTS) == set(ERROR_CODES) == _python_codes(ERROR_CLASSES)
    assert _sections("Warning codes", "Warnings and logging") == WARNING_HINTS
    assert _python_codes({"InsertWarning"}) <= WARNING_HINTS.keys()


def test_an_error_carries_its_code_hint_retryability_and_both_docs_links():
    missing = NotFoundError("Entity", "person:nobody")
    assert missing.to_dict() == {
        "error": "Entity 'person:nobody' does not exist",
        "error_type": "NotFoundError",
        "code": "not_found",
        "hint": HINTS["not_found"],
        "retryable": False,
        "docs": f"https://github.com/hydra-db/selfgraph/blob/v{selfgraph.__version__}/docs/errors.md#not_found",
        "agent_guide": "site-packages/selfgraph/errors.md#not_found",
    }
    assert [TransientError().retryable, StoreError().retryable] == [True, False]


def test_a_missing_entity_names_the_namespace_and_the_closest_id_of_its_type():
    ns = unique_ns("missing")
    g = new_graph(namespace=ns)
    run(g.insert.facts({"entities": [{"name": "Ada", "type": "Person"}, {"name": "Acme", "type": "Company"}]}))
    with pytest.raises(NotFoundError) as near:
        run(g.entities.update("person:ad", name="Ad"))
    with pytest.raises(NotFoundError) as far:
        run(g.entities.delete("person:zzzz"))
    assert str(near.value) == f"Entity 'person:ad' does not exist in namespace '{ns}'; did you mean 'person:ada'?"
    assert str(far.value) == f"Entity 'person:zzzz' does not exist in namespace '{ns}'"


@pytest.mark.parametrize(
    ("facts", "code", "field"),
    [
        ({"entities": [{"name": "Ada", "type": "Person", "bogus": 1}]}, "unknown_key", "entities[0].bogus"),
        ({"entities": [{"type": "Person"}]}, "invalid_argument", "entities[0].name"),
    ],
)
def test_bad_input_names_the_field_at_fault(facts, code, field):
    with pytest.raises(SelfGraphError) as exc:
        Extraction(**facts)
    assert (exc.value.code, exc.value.to_dict()["field"]) == (code, field)


@pytest.mark.parametrize(
    ("settings", "code", "field"),
    [
        ({"store": "bogus"}, "invalid_setting", "store"),
        ({"level": "max"}, "llm_required", None),
        ({"schema_mode": "strict"}, "schema_required", None),
        ({"llm_timeout": "-1"}, "invalid_setting", "llm_timeout"),
    ],
)
def test_settings_fail_with_a_narrow_code(settings, code, field):
    with pytest.raises(SelfGraphError) as exc:
        check_settings(GraphSettings(**settings))
    assert (exc.value.code, exc.value.to_dict().get("field")) == (code, field)
