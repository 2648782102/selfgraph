from __future__ import annotations

import errno
import re
from typing import Any, Literal

__all__ = [
    "ErrorCode",
    "SelfGraphError",
    "ValidationError",
    "NotFoundError",
    "ConflictError",
    "ExtractionError",
    "PromptTemplateError",
    "StoreError",
    "TransientError",
]


ErrorCode = Literal[
    "invalid_argument",
    "unknown_key",
    "invalid_setting",
    "llm_required",
    "embedder_required",
    "schema_required",
    "schema_violation",
    "immutable_identity",
    "unknown_reference",
    "relation_certified",
    "relation_invalidated",
    "merge_reverted",
    "invalid_cursor",
    "invalid_resolver_decision",
    "read_only_query",
    "missing_package",
    "not_found",
    "already_exists",
    "extraction_failed",
    "llm_auth_failed",
    "llm_model_not_found",
    "invalid_llm_output",
    "invalid_prompt_template",
    "query_failed",
    "graph_closed",
    "store_closed",
    "store_unreachable",
    "store_locked",
    "store_auth_failed",
    "database_not_found",
    "wrong_engine",
    "write_too_large",
    "write_conflict",
    "store_busy",
]
DOCS_URL = "https://github.com/hydra-db/selfgraph/blob/main/docs/errors.md"


class SelfGraphError(Exception):
    code: ErrorCode = "invalid_argument"

    def __init__(self, message: str = "", *, code: ErrorCode | None = None) -> None:
        """An SDK error with a stable code that names the failure and its repair.

        @param message (str): what happened, with the fix when one applies.
        @param code (ErrorCode | None): the code, or None for the class default.
        """
        super().__init__(message)
        if code is not None:
            self.code = code

    @property
    def retryable(self) -> bool:
        """Whether the same call can succeed when run again unchanged.

        @return (bool): True for a TransientError.
        """
        return isinstance(self, TransientError)

    @property
    def docs(self) -> str:
        """The docs section that explains this error's code and its repair.

        @return (str): the URL.
        """
        return f"{DOCS_URL}#{self.code}"

    def to_dict(self) -> dict[str, Any]:
        """The error as JSON-ready fields, as the MCP server returns it.

        @return (dict[str, Any]): error, error_type, code, retryable, and docs.
        """
        return {
            "error": str(self),
            "error_type": type(self).__name__,
            "code": self.code,
            "retryable": self.retryable,
            "docs": self.docs,
        }


class ValidationError(SelfGraphError):
    pass


class NotFoundError(SelfGraphError):
    code: ErrorCode = "not_found"

    def __init__(self, object_type: str, object_id: str, message: str | None = None) -> None:
        self.object_type = object_type
        self.object_id = object_id
        super().__init__(message or f"{object_type} {object_id!r} does not exist")


class ConflictError(SelfGraphError):
    code: ErrorCode = "already_exists"

    def __init__(self, object_type: str, object_id: str) -> None:
        self.object_type = object_type
        self.object_id = object_id
        super().__init__(f"{object_type} {object_id!r} already exists")


class ExtractionError(SelfGraphError):
    code: ErrorCode = "extraction_failed"


class PromptTemplateError(SelfGraphError):
    code: ErrorCode = "invalid_prompt_template"


class StoreError(SelfGraphError):
    code: ErrorCode = "query_failed"


class TransientError(StoreError):
    code: ErrorCode = "write_conflict"


CLOSED_MESSAGE = "this SelfGraph is closed; create a new SelfGraph to keep using the store"
LLM_HINT = "pass llm= to SelfGraph (or set SELFGRAPH_LLM_PROVIDER and SELFGRAPH_LLM_MODEL)"
STORE_CLOSED_MESSAGE = "this store is closed; create a new store for each SelfGraph"
TOKEN_HINT = "pass auth=TOKEN to HydraDBStore (or set SELFGRAPH_AUTH)"
STORE_KUZU_HINT = 'pass store="kuzu" (or SELFGRAPH_STORE=kuzu)'
OTHER_ENGINE_HINT = 'pass store="neo4j" (or store="memgraph")'
DECAY_HINT = "run maintenance.decay(dry_run=False) first"
KEY_SOURCES = "api_key in the llm config (or SELFGRAPH_LLM_API_KEY)"


def needs_llm(what: str) -> ValidationError:
    """The error for a feature that needs an LLM when none is configured.

    @param what (str): the feature, such as "level 'max'".
    @return (ValidationError): the error, with code llm_required.
    """
    return ValidationError(f"{what} needs an LLM: {LLM_HINT}", code="llm_required")


def setting_hint(key: str) -> str:
    """Name a connect or from_env setting with its environment variable, as library messages do.

    @param key (str): the setting name, such as "llm_model".
    @return (str): the hint, such as "llm_model= (or SELFGRAPH_LLM_MODEL)", which the CLI rewords to its flag.
    """
    return f"{key}= (or SELFGRAPH_{key.upper()})"


_SURFACE_HINTS = (
    (LLM_HINT, "pass --llm-provider and --llm-model (or SELFGRAPH_LLM_*)"),
    (TOKEN_HINT, "pass --auth TOKEN (or SELFGRAPH_AUTH)"),
    (STORE_KUZU_HINT, "pass --store kuzu (or SELFGRAPH_STORE=kuzu)"),
    (OTHER_ENGINE_HINT, "pass --store neo4j (or memgraph)"),
    (DECAY_HINT, "run maintenance decay --apply first"),
    (KEY_SOURCES, "--llm-api-key (or SELFGRAPH_LLM_API_KEY)"),
    *(
        (setting_hint(key), f"--{key.replace('_', '-')} (or SELFGRAPH_{key.upper()})")
        for key in ("uri", "llm_provider", "llm_model")
    ),
)

_CONNECT_CODES = {
    errno.ECONNREFUSED: "connection refused",
    errno.ECONNRESET: "connection reset",
    errno.EHOSTUNREACH: "host unreachable",
    errno.ETIMEDOUT: "connection timed out",
}
_DANGLING = re.compile(r":[\s.]*$")
_DRIVER_BOILERPLATE = re.compile(
    r"(?:Connection Failed\. )?Please ensure that your database is listening on the correct host and port[^.]*\. "
    r"Note that the default encryption setting has changed in Neo4j 4\.0\.(?: See the docs for more information\.)?\s*"
)


def surface_hint(message: str) -> str:
    """Reword a library message for the CLI and MCP server, which take the LLM from flags or the environment.

    @param message (str): the library message.
    @return (str): the message with the library setting hints (llm=, auth=, store=, uri=, llm_model=, and the like)
        replaced by the flag hints.
    """
    for library, surface in _SURFACE_HINTS:
        message = message.replace(library, surface)
    return message


def _connect_failure(exc: BaseException | None, seen: set[int]) -> str:
    """The plain-words connection failure ("connection refused") of the first known errno in a cause chain.

    @param exc (BaseException | None): the error.
    @param seen (set[int]): ids of errors already visited.
    @return (str): the phrase, or "" when no known errno is present.
    """
    if exc is None or id(exc) in seen:
        return ""
    seen.add(id(exc))
    phrase = _CONNECT_CODES.get(getattr(exc, "errno", None))
    return phrase or _connect_failure(exc.__cause__ or exc.__context__, seen)


def error_reason(exc: BaseException) -> str:
    """Describe an error, filling an empty or dangling reason from its cause chain or errno, minus trailing dots.

    @param exc (BaseException): the raised error.
    @return (str): the reason, or the error type name when nothing says more.
    """
    seen: set[int] = set()

    def reason(err: BaseException | None) -> str:
        if err is None or id(err) in seen:
            return ""
        seen.add(id(err))
        text = _DRIVER_BOILERPLATE.sub("", " ".join(str(err).split()))
        head = text.rstrip(" .:;,")
        if head and not _DANGLING.search(text):
            return head
        inner = _connect_failure(err, set()) or reason(err.__cause__ or err.__context__)
        return f"{head}: {inner}" if head and inner else head or inner

    return reason(exc) or type(exc).__name__
