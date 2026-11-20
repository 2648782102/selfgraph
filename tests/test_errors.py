import ast
import pathlib
import re
from typing import get_args

import pytest

import selfgraph
from selfgraph import Extraction, NotFoundError, StoreError, TransientError
from selfgraph.errors import HINTS, ErrorCode, SelfGraphError
from selfgraph.runtime import GraphSettings, check_settings

ROOT = pathlib.Path(__file__).resolve().parent.parent
ERROR_CODES = get_args(ErrorCode)
ERROR_CLASSES = {name for name in selfgraph.__all__ if name.endswith("Error")}


def _python_codes():
    """Every code a Python raise site or error class names.

    @return (set[str]): the codes.
    """
    found = set()
    for path in (ROOT / "src" / "selfgraph").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ERROR_CLASSES:
                found |= {k.value.value for k in node.keywords if k.arg == "code" and isinstance(k.value, ast.Constant)}
            if isinstance(node, ast.ClassDef) and node.name in ERROR_CLASSES:
                found |= {
                    stmt.value.value
                    for stmt in node.body
                    if isinstance(stmt, ast.AnnAssign) and getattr(stmt.target, "id", None) == "code"
                }
    return found


def _documented():
    """Each code's section in docs/errors.md, as one line of text.

    @return (dict[str, str]): the section text by code.
    """
    text = (ROOT / "docs" / "errors.md").read_text()
    sections = re.finditer(r"^#### `(\w+)`\n\n(.*?)(?=\n#|\Z)", text, re.S | re.M)
    return {m.group(1): " ".join(m.group(2).split()) for m in sections}


def test_every_raised_code_is_documented_and_its_hint_is_its_docs_section():
    assert _documented() == HINTS
    assert set(HINTS) == set(ERROR_CODES)
    assert _python_codes() == set(ERROR_CODES)


def test_an_error_carries_its_code_hint_retryability_and_release_docs():
    missing = NotFoundError("Entity", "person:nobody")
    assert missing.to_dict() == {
        "error": "Entity 'person:nobody' does not exist",
        "error_type": "NotFoundError",
        "code": "not_found",
        "hint": HINTS["not_found"],
        "retryable": False,
        "docs": f"https://github.com/hydra-db/selfgraph/blob/v{selfgraph.__version__}/docs/errors.md#not_found",
    }
    assert [TransientError().retryable, StoreError().retryable] == [True, False]


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
