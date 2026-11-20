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
HINTS: dict[ErrorCode, str] = {
    "invalid_argument": (
        "An argument, input field, or option value is wrong. The message names the field and what it "
        "expected. Fix the value and call again."
    ),
    "unknown_key": (
        "A key or option name is not one the call accepts. Use the name the message suggests after `did you mean`."
    ),
    "invalid_setting": (
        "A graph setting is missing or wrong: `uri`, `store`, `llm_provider`, `llm_model`, `llm_timeout`, "
        "`llm_concurrency`, or the provider in the LLM config. Fix the setting, flag, or `SELFGRAPH_*` "
        "variable the message names."
    ),
    "llm_required": (
        "The call needs an LLM and none is configured. Configure one (the `llm` option, or `--llm-provider` "
        "and `--llm-model` in the CLI and MCP server), or choose a tier that needs no LLM."
    ),
    "embedder_required": (
        "The `embeddings` seeds tier needs an embedder. Pass one with the SDK's `embedder` option, or choose "
        "another seeds tier."
    ),
    "schema_required": (
        "Strict schema mode, or exporting the schema, needs a schema. Pass one (the `schema` option, or "
        "`--schema`), or use schema mode `warn`."
    ),
    "schema_violation": (
        "A write breaks the schema in strict mode. Fix the facts to match the schema, change the schema, or "
        "use schema mode `warn`. A relation over its `max_count` can also retire the older one with "
        "contradiction mode `supersede`."
    ),
    "immutable_identity": (
        "The change touches a field that is part of the object's id: an entity's type, a relation's endpoints "
        "and type, or a preference's subject, stance, key, and value. Create a new object instead of updating "
        "this one."
    ),
    "unknown_reference": (
        "The input references an entity or relation that does not exist. Create it first, or fix the id."
    ),
    "relation_certified": "A certified relation blocks the change. Uncertify the relation, then run the call again.",
    "relation_invalidated": (
        "The relation was invalidated (superseded or retired). Create it again to reassert it, or act on its "
        "current version."
    ),
    "merge_reverted": "The merge was already reverted. There is nothing left to undo.",
    "invalid_cursor": "The cursor did not come from this listing. Start the listing again without a cursor.",
    "invalid_resolver_decision": (
        "A custom entity resolver returned a bad decision. Return a `ResolutionDecision` whose target is one "
        "of the offered entities, with a confidence and a reason."
    ),
    "read_only_query": "`run_cypher` runs a single read. Write through the typed tools instead.",
    "missing_package": "An optional package is not installed. Run the install command in the message.",
    "not_found": "The object does not exist in this namespace. Check the id and the namespace, or create the object.",
    "already_exists": "An object with this id already exists. Update it, or insert it, which upserts.",
    "extraction_failed": (
        "LLM extraction failed. The message carries the first failure. Check the LLM settings and the "
        "provider, then run the insert again."
    ),
    "llm_auth_failed": (
        "The LLM provider got no API key, or rejected it. Pass `api_key` in the LLM config, or set "
        "`SELFGRAPH_LLM_API_KEY` or the provider's own variable."
    ),
    "llm_model_not_found": "The provider does not know the model. Check the model name and the provider.",
    "invalid_llm_output": (
        "The model, or a custom LLM client, returned output that does not match the pass's schema. Use "
        "another model, or fix the client."
    ),
    "invalid_prompt_template": (
        "A prompt template is malformed. Keep `{text}` in the user template and use no placeholder other than "
        "`{text}` and `{instructions}`."
    ),
    "query_failed": (
        "The backend rejected a query. The message keeps the engine's reason. Check any Cypher you passed yourself."
    ),
    "graph_closed": "The SelfGraph was closed. Create a new SelfGraph.",
    "store_closed": (
        "The store was closed, and closing a graph closes its store. Create a new store for each SelfGraph."
    ),
    "store_unreachable": (
        "The SDK could not connect to the backend. Check that the server is running and that the address is right."
    ),
    "store_locked": (
        "Another process (an MCP server or a script) has the embedded Kuzu database open, and Kuzu allows one "
        "process at a time. Close it, or point this one at another path."
    ),
    "store_auth_failed": (
        "The backend rejected the credentials, or HydraDB got no token. Pass the right `auth` (CLI and MCP: "
        "`--auth`, or `SELFGRAPH_AUTH`)."
    ),
    "database_not_found": (
        "The database named in the settings does not exist on the server. Create it, or fix the name."
    ),
    "wrong_engine": "The server at the address is another engine. Pass the store that matches it, such as `neo4j`.",
    "write_too_large": (
        "A single node or edge row is larger than HydraDB accepts in one message. Split large property values or text."
    ),
    "write_conflict": (
        "A concurrent write conflicted and the SDK's own retries ran out. Run the same call again: ids are "
        "deterministic and inserts are upserts, so a retry does not duplicate anything. Retryable, as is "
        "every `TransientError`."
    ),
    "store_busy": (
        "The server timed out or was too busy to take the query. Run the same call again after a moment. Retryable."
    ),
}
DOCS_URL = "https://github.com/hydra-db/selfgraph/blob/v{version}/docs/errors.md"


class SelfGraphError(Exception):
    code: ErrorCode = "invalid_argument"
    field: str | None = None

    def __init__(self, message: str = "", *, code: ErrorCode | None = None, field: str | None = None) -> None:
        """An SDK error with a stable code that names the failure and its repair.

        @param message (str): what happened, with the fix when one applies.
        @param code (ErrorCode | None): the code, or None for the class default.
        @param field (str | None): the argument, key, or setting at fault, when one is.
        """
        super().__init__(message)
        if code is not None:
            self.code = code
        if field is not None:
            self.field = field

    @property
    def hint(self) -> str:
        """How to repair this error's code, as its docs section says.

        @return (str): the repair.
        """
        return HINTS[self.code]

    @property
    def retryable(self) -> bool:
        """Whether the same call can succeed when run again unchanged.

        @return (bool): True for a TransientError.
        """
        return isinstance(self, TransientError)

    @property
    def docs(self) -> str:
        """The docs section for this error's code, at the installed release.

        @return (str): the URL.
        """
        from . import __version__

        return f"{DOCS_URL.format(version=__version__)}#{self.code}"

    def to_dict(self) -> dict[str, Any]:
        """The error as JSON-ready fields, as the MCP server returns it.

        @return (dict[str, Any]): error, error_type, code, field when one is at fault, hint, retryable, and docs.
        """
        field = {} if self.field is None else {"field": self.field}
        return {
            "error": str(self),
            "error_type": type(self).__name__,
            "code": self.code,
            **field,
            "hint": self.hint,
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


def connection_reason(exc: BaseException) -> str:
    """Describe a failed connection in plain words ("connection refused") when the cause chain says which.

    @param exc (BaseException): the raised error.
    @return (str): the phrase, or the error's reason.
    """
    return _connect_failure(exc, set()) or error_reason(exc)


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
