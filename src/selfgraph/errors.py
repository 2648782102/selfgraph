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


def _uri_userinfo(uri: str) -> tuple[int, str]:
    """Locate the user and password of a URI, erring toward hiding too much.

    @param uri (str): the URI, with or without a scheme.
    @return (tuple[int, str]): the offset where the userinfo starts and the userinfo. It runs to the last @ of the
        authority (up to the first /, ? or # after any scheme); when the authority has no @, it runs to the last @
        anywhere after the scheme, so a password with an unencoded /, ? or # is still hidden. It is empty when the
        URI has no @.
    """
    start = uri.index("://") + 3 if "://" in uri else 0
    rest = uri[start:]
    userinfo, at, _ = re.split(r"[/?#]", rest, maxsplit=1)[0].rpartition("@")
    return start, userinfo if at else rest.rpartition("@")[0]


def mask_uri(uri: str) -> str:
    """Hide the user and password of a URI so a message can show it.

    @param uri (str): the URI, such as redis://user:pass@host:6379.
    @return (str): the URI with its userinfo replaced by ***, such as redis://***@host:6379.
    """
    start, userinfo = _uri_userinfo(uri)
    return f"{uri[:start]}***{uri[start + len(userinfo) :]}" if userinfo else uri


def _escaped_forms(part: str) -> tuple[str, str, str]:
    """The ways a message can show a piece of a URI: raw, as inside a Python repr, and as inside a JSON string.

    @param part (str): the piece of the URI.
    @return (tuple[str, str, str]): the raw, repr, and JSON renderings, without their quotes.
    """
    return part, repr(part)[1:-1], json.dumps(part, ensure_ascii=False)[1:-1]


def _echoed_pieces(userinfo: str) -> list[str]:
    """The pieces of a URI's userinfo that a driver may show before an @, longest first.

    Drivers that misread a password with an unencoded /, ?, #, & or = echo only the part after it, so each piece is
    the userinfo or the text after any of those characters up to one of its @. Each piece also comes without tabs and
    newlines, which URL parsers strip, and with + read as a space, as query parsers do.

    @param userinfo (str): the user and password of a URI.
    @return (list[str]): the distinct non-empty pieces, longest first.
    """
    chunks = userinfo.split("@")
    pieces = [userinfo]
    for i in range(len(chunks)):
        prefix = "@".join(chunks[: i + 1])
        pieces += [prefix[j + 1 :] for j, char in enumerate(prefix) if char in "/?#&="]
    variants = (v for p in pieces for v in (p, re.sub(r"[\t\r\n]", "", p), p.replace("+", " ")))
    return sorted(dict.fromkeys(v for v in variants if v), key=len, reverse=True)


def redact_uri(text: str, uri: str | None) -> str:
    """Replace the user and password of a URI with *** wherever a message shows them, raw or escaped.

    @param text (str): the message, which may quote the URI or repeat a driver's text about it.
    @param uri (str | None): the configured URI.
    @return (str): the message with each raw, repr, or JSON rendering of the whole URI replaced by the same rendering
        of the masked URI; then each such rendering of a piece of the userinfo that precedes an @ replaced by ***;
        then, when the userinfo runs past the authority, the authority itself when it holds a :, since a driver may
        take that part of the password for a host:port.
    """
    if not uri:
        return text
    start, userinfo = _uri_userinfo(uri)
    if not userinfo:
        return text
    masked = mask_uri(uri)
    for render in (repr, lambda s: json.dumps(s, ensure_ascii=False), str):
        text = text.replace(render(uri), render(masked))
    for piece in _echoed_pieces(userinfo):
        for form in _escaped_forms(piece):
            text = text.replace(f"{form}@", "***@")
    authority = re.split(r"[/?#]", uri[start:], maxsplit=1)[0]
    if "@" not in authority and ":" in authority:
        for form in _escaped_forms(authority):
            text = text.replace(form, "***")
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
