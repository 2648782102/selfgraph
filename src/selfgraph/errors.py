from __future__ import annotations

import errno
import json
import re

__all__ = [
    "SelfGraphError",
    "ValidationError",
    "NotFoundError",
    "ConflictError",
    "ExtractionError",
    "PromptTemplateError",
    "StoreError",
    "TransientError",
]


class SelfGraphError(Exception):
    pass


class ValidationError(SelfGraphError):
    pass


class NotFoundError(SelfGraphError):
    def __init__(self, object_type: str, object_id: str, message: str | None = None) -> None:
        self.object_type = object_type
        self.object_id = object_id
        super().__init__(message or f"{object_type} {object_id!r} does not exist")


class ConflictError(SelfGraphError):
    def __init__(self, object_type: str, object_id: str) -> None:
        self.object_type = object_type
        self.object_id = object_id
        super().__init__(f"{object_type} {object_id!r} already exists")


class ExtractionError(SelfGraphError):
    pass


class PromptTemplateError(SelfGraphError):
    pass


class StoreError(SelfGraphError):
    pass


class TransientError(StoreError):
    pass


CLOSED_MESSAGE = "this SelfGraph is closed; create a new SelfGraph to keep using the store"
LLM_HINT = "pass llm= to SelfGraph (or set SELFGRAPH_LLM_PROVIDER and SELFGRAPH_LLM_MODEL)"
STORE_CLOSED_MESSAGE = "this store is closed; create a new store for each SelfGraph"
TOKEN_HINT = "pass auth=TOKEN to HydraDBStore (or set SELFGRAPH_AUTH)"
STORE_KUZU_HINT = 'pass store="kuzu" (or SELFGRAPH_STORE=kuzu)'
OTHER_ENGINE_HINT = 'pass store="neo4j" (or store="memgraph")'
DECAY_HINT = "run maintenance.decay(dry_run=False) first"
KEY_SOURCES = "api_key in the llm config (or SELFGRAPH_LLM_API_KEY)"


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


_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_AT_SIGNS = ("@", "\uff20", "\ufe6b")


def split_scheme(uri: str) -> tuple[str, str]:
    """Split a URI into its scheme and the rest, taking a scheme only when the URI starts with one followed by ://.

    @param uri (str): the URI, such as bolt://host:7687 or host:7687.
    @return (tuple[str, str]): the scheme, empty when there is none, and the text after its ://, or the whole URI.
    """
    match = _SCHEME.match(uri)
    return (uri[: match.end() - 3], uri[match.end() :]) if match else ("", uri)


UNENCODED_USERINFO = (
    "the store URI has an unencoded character in its user or password; "
    "percent-encode it (/ as %2F, ? as %3F, # as %23, @ as %40)"
)


def require_encoded_userinfo(uri: str) -> None:
    """Reject a URI whose user or password holds an unencoded /, ?, # or @, before any driver reads it.

    Drivers read such a URI as another host, port, path, or query and repeat pieces of the password in their errors,
    so the message names the problem without quoting the URI.

    @param uri (str): the store URI, with or without a scheme.
    @return (None): nothing; raises ValidationError when the text between the scheme and the last @ holds a /, ? or
        #, or the authority holds more than one @.
    """
    rest = split_scheme(uri)[1]
    if re.search(r"[/?#]", rest.rpartition("@")[0]) or re.split(r"[/?#]", rest, maxsplit=1)[0].count("@") > 1:
        raise ValidationError(UNENCODED_USERINFO)


def _uri_userinfo(uri: str) -> tuple[int, str]:
    """Locate the user and password of a URI inside its authority.

    @param uri (str): the URI, with or without a scheme.
    @return (tuple[int, str]): the offset where the userinfo starts and the userinfo, which runs to the last @ before
        the first /, ? or # after any scheme, counting the fullwidth ＠ and small ﹫ that NFKC turns into @ (parsers
        that normalize read them as the separator); the userinfo is empty when the authority has none.
    """
    rest = split_scheme(uri)[1]
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    end = max(authority.rfind(at) for at in _AT_SIGNS)
    return len(uri) - len(rest), authority[: max(end, 0)]


def mask_uri(uri: str) -> str:
    """Hide the user and password of a URI so a message can show it.

    @param uri (str): the URI, such as redis://user:pass@host:6379.
    @return (str): the URI with its userinfo replaced by ***, such as redis://***@host:6379.
    """
    start, userinfo = _uri_userinfo(uri)
    return f"{uri[:start]}***{uri[start + len(userinfo) :]}" if userinfo else uri


def redact_uri(text: str, uri: str | None) -> str:
    """Replace the user and password of a URI with *** wherever a message shows them, raw or escaped.

    @param text (str): the message, which may quote the URI or repeat a driver's text about it.
    @param uri (str | None): the configured URI.
    @return (str): the message with each raw, repr, or JSON rendering of the whole URI replaced by the same rendering
        of the masked URI, then each such rendering of the userinfo before its separator replaced by ***.
    """
    if not uri:
        return text
    start, userinfo = _uri_userinfo(uri)
    if not userinfo:
        return text
    masked = mask_uri(uri)
    for render in (repr, lambda s: json.dumps(s, ensure_ascii=False), str):
        text = text.replace(render(uri), render(masked))
    at = uri[start + len(userinfo)]
    for form in (userinfo, repr(userinfo)[1:-1], json.dumps(userinfo, ensure_ascii=False)[1:-1]):
        text = text.replace(f"{form}{at}", f"***{at}")
    return text


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
