import ast
import pathlib
import re
from typing import get_args

import pytest

import selfgraph
from selfgraph import NotFoundError, StoreError, TransientError
from selfgraph.errors import DOCS_URL, ErrorCode, SelfGraphError
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


def test_codes_agree_across_python_typescript_and_the_docs():
    ts_source = "".join(p.read_text() for p in (ROOT / "typescript" / "src").rglob("*.ts"))
    start = ts_source.index("export type ErrorCode =")
    catalog = ts_source[start : ts_source.index(";", start)]
    documented = re.findall(r"^#### `(\w+)`$", (ROOT / "docs" / "errors.md").read_text(), re.M)
    assert set(re.findall(r'^  \| "(\w+)"$', catalog, re.M)) == set(ERROR_CODES)
    assert sorted(documented) == sorted(ERROR_CODES)
    assert _python_codes() == set(ERROR_CODES)


def test_an_error_carries_its_code_retryability_and_docs():
    missing = NotFoundError("Entity", "person:nobody")
    assert missing.to_dict() == {
        "error": "Entity 'person:nobody' does not exist",
        "error_type": "NotFoundError",
        "code": "not_found",
        "retryable": False,
        "docs": f"{DOCS_URL}#not_found",
    }
    assert [TransientError().retryable, StoreError().retryable] == [True, False]


@pytest.mark.parametrize(
    ("settings", "code"),
    [
        ({"store": "bogus"}, "invalid_setting"),
        ({"level": "max"}, "llm_required"),
        ({"schema_mode": "strict"}, "schema_required"),
        ({"llm_timeout": "-1"}, "invalid_setting"),
    ],
)
def test_settings_fail_with_a_narrow_code(settings, code):
    with pytest.raises(SelfGraphError) as exc:
        check_settings(GraphSettings(**settings))
    assert exc.value.code == code
