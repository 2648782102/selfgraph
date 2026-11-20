import { pyRepr } from "./internal/py.js";

export class SelfGraphError extends Error {
  constructor(message?: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = new.target.name;
  }
}

export class ValidationError extends SelfGraphError {}

class ObjectError extends SelfGraphError {
  /**
   * An error about one stored object, naming its type and id.
   *
   * @param object_type (string): the object type, e.g. "Entity".
   * @param object_id (string): the object id.
   * @param state (string): what is wrong with it, e.g. "does not exist".
   * @param message (string | undefined): a message that replaces the default one.
   */
  constructor(
    readonly object_type: string,
    readonly object_id: string,
    state: string,
    message?: string,
  ) {
    super(message || `${object_type} ${pyRepr(object_id)} ${state}`);
  }
}

export class NotFoundError extends ObjectError {
  constructor(objectType: string, objectId: string, message?: string) {
    super(objectType, objectId, "does not exist", message);
  }
}

export class ConflictError extends ObjectError {
  constructor(objectType: string, objectId: string) {
    super(objectType, objectId, "already exists");
  }
}

export class ExtractionError extends SelfGraphError {}

export class PromptTemplateError extends SelfGraphError {}

export class StoreError extends SelfGraphError {}

export class TransientError extends StoreError {}

export const LLM_HINT = "pass llm in the SelfGraph options (or set SELFGRAPH_LLM_PROVIDER and SELFGRAPH_LLM_MODEL)";
export const STORE_CLOSED_MESSAGE = "this store is closed; create a new store for each SelfGraph";
export const TOKEN_HINT = "pass auth: TOKEN in the HydraDBStore options (or set SELFGRAPH_AUTH)";
export const STORE_KUZU_HINT = 'pass store: "kuzu" (or SELFGRAPH_STORE=kuzu)';
export const OTHER_ENGINE_HINT = 'pass store: "neo4j" (or store: "memgraph")';
export const DECAY_HINT = "run maintenance.decay({ dry_run: false }) first";
export const KEY_SOURCES = "api_key in the llm config (or SELFGRAPH_LLM_API_KEY)";

/**
 * Name a connect or fromEnv setting with its environment variable, as library messages do.
 *
 * @param key (string): the setting name, such as "llm_model".
 * @return (string): the hint, such as "the llm_model option (or SELFGRAPH_LLM_MODEL)", which the CLI rewords to its flag.
 */
export function settingHint(key: string): string {
  return `the ${key} option (or SELFGRAPH_${key.toUpperCase()})`;
}

const SURFACE_HINTS: ReadonlyArray<readonly [string, string]> = [
  [LLM_HINT, "pass --llm-provider and --llm-model (or SELFGRAPH_LLM_*)"],
  [TOKEN_HINT, "pass --auth TOKEN (or SELFGRAPH_AUTH)"],
  [STORE_KUZU_HINT, "pass --store kuzu (or SELFGRAPH_STORE=kuzu)"],
  [OTHER_ENGINE_HINT, "pass --store neo4j (or memgraph)"],
  [DECAY_HINT, "run maintenance decay --apply first"],
  [KEY_SOURCES, "--llm-api-key (or SELFGRAPH_LLM_API_KEY)"],
  ...["uri", "llm_provider", "llm_model"].map(
    (key) => [settingHint(key), `--${key.replaceAll("_", "-")} (or SELFGRAPH_${key.toUpperCase()})`] as const,
  ),
];
const DRIVER_BOILERPLATE =
  /(?:Connection Failed\. )?Please ensure that your database is listening on the correct host and port[^.]*\. Note that the default encryption setting has changed in Neo4j 4\.0\.(?: See the docs for more information\.)?\s*/g;

/**
 * Reword a library message for the CLI and MCP server, which take the LLM from flags or the environment.
 *
 * @param message (string): the library message.
 * @return (string): the message with the library setting hints (llm, auth, store, uri, llm_model, and the like) replaced by the flag hints.
 */
export function surfaceHint(message: string): string {
  return SURFACE_HINTS.reduce((text, [library, surface]) => text.replaceAll(library, surface), message);
}

/**
 * Split a URI into its scheme and the rest, taking a scheme only when the URI starts with one followed by ://.
 *
 * @param uri (string): the URI, such as bolt://host:7687 or host:7687.
 * @return ([string, string]): the scheme, empty when there is none, and the text after its ://, or the whole URI.
 */
export function splitScheme(uri: string): [string, string] {
  const match = /^[A-Za-z][A-Za-z0-9+.-]*:\/\//.exec(uri);
  return match ? [uri.slice(0, match[0].length - 3), uri.slice(match[0].length)] : ["", uri];
}

const AT_SIGNS = ["@", "\uff20", "\ufe6b"];

export const UNENCODED_USERINFO =
  "the store URI has an unencoded character in its user or password; " +
  "percent-encode it (/ as %2F, ? as %3F, # as %23, @ as %40, [ as %5B, ] as %5D)";

/**
 * Whether an authority holds non-ASCII text that NFKC turns into a /, ?, #, @, :, [ or ].
 *
 * Python's urlsplit refuses a netloc whose text NFKC turns into a /, ?, #, @ or : with a ValueError that quotes it,
 * and other parsers read such a character as part of the host, so a fullwidth ＠ sends the password to the DNS resolver.
 *
 * @param authority (string): the URI text between the scheme's :// and the first /, ? or #.
 * @return (boolean): true when one of its characters is non-ASCII and NFKC-normalizes to text holding a separator.
 */
export function nfkcSeparator(authority: string): boolean {
  return Array.from(authority).some(
    (char) => char.codePointAt(0)! >= 0x80 && /[/?#@:[\]]/.test(char.normalize("NFKC")),
  );
}

/**
 * Reject a URI whose user or password holds an unencoded /, ?, #, @, [ or ], before any driver reads it.
 *
 * Drivers read such a URI as another host, port, path, or query and repeat pieces of the password in their errors,
 * so the message names the problem without quoting the URI. Brackets around an IPv6 host stay valid.
 *
 * @param uri (string): the store URI, with or without a scheme.
 * @return (void): nothing; throws ValidationError when the text between the scheme and the last @ (counting the
 *   fullwidth ＠ and small ﹫) holds a /, ?, #, [ or ], the authority holds more than one @, or the authority holds a
 *   character that NFKC turns into one of / ? # @ : [ ].
 */
export function requireEncodedUserinfo(uri: string): void {
  const rest = splitScheme(uri)[1];
  const authority = rest.split(/[/?#]/, 1)[0] ?? "";
  const userinfo = rest.slice(0, Math.max(...AT_SIGNS.map((at) => rest.lastIndexOf(at)), 0));
  if (/[/?#[\]]/.test(userinfo) || authority.split("@").length > 2 || nfkcSeparator(authority)) {
    throw new ValidationError(UNENCODED_USERINFO);
  }
}

/**
 * Locate the user and password of a URI inside its authority.
 *
 * @param uri (string): the URI, with or without a scheme.
 * @return ([number, string]): the offset where the userinfo starts and the userinfo, which runs to the last @ before
 *   the first /, ? or # after any scheme, counting the fullwidth ＠ and small ﹫ that NFKC turns into @ (parsers that
 *   normalize read them as the separator); the userinfo is empty when the authority has none.
 */
function uriUserinfo(uri: string): [number, string] {
  const rest = splitScheme(uri)[1];
  const authority = rest.split(/[/?#]/, 1)[0] ?? "";
  const end = Math.max(...AT_SIGNS.map((at) => authority.lastIndexOf(at)));
  return [uri.length - rest.length, authority.slice(0, Math.max(end, 0))];
}

/**
 * Hide the user and password of a URI so a message can show it.
 *
 * @param uri (string): the URI, such as redis://user:pass@host:6379.
 * @return (string): the URI with its userinfo replaced by ***, such as redis://***@host:6379.
 */
export function maskUri(uri: string): string {
  const [start, userinfo] = uriUserinfo(uri);
  return userinfo ? `${uri.slice(0, start)}***${uri.slice(start + userinfo.length)}` : uri;
}

/**
 * Replace the user and password of a URI with *** wherever a message shows them, raw or escaped.
 *
 * @param text (string): the message, which may quote the URI or repeat a driver's text about it.
 * @param uri (string | null | undefined): the configured URI.
 * @return (string): the message with each raw, repr, or JSON rendering of the whole URI replaced by the same
 *   rendering of the masked URI, then each such rendering of the userinfo before its separator replaced by ***.
 */
export function redactUri(text: string, uri: string | null | undefined): string {
  if (!uri) return text;
  const [start, userinfo] = uriUserinfo(uri);
  if (!userinfo) return text;
  const masked = maskUri(uri);
  const renders = [pyRepr, JSON.stringify, String] as ((value: string) => string)[];
  const whole = renders.reduce((out, render) => out.replaceAll(render(uri), () => render(masked)), text);
  const at = uri.charAt(start + userinfo.length);
  return [userinfo, pyRepr(userinfo).slice(1, -1), JSON.stringify(userinfo).slice(1, -1)].reduce(
    (out, form) => out.replaceAll(`${form}${at}`, () => `***${at}`),
    whole,
  );
}

/**
 * The message of a thrown value, or its text when it is not an Error.
 *
 * @param exc (unknown): the thrown value.
 * @return (string): the message.
 */
export function errorMessage(exc: unknown): string {
  return exc instanceof Error ? exc.message : String(exc);
}

const CONNECT_CODES: Readonly<Record<string, string>> = {
  ECONNREFUSED: "connection refused",
  ECONNRESET: "connection reset",
  ENOTFOUND: "host not found",
  EAI_AGAIN: "host lookup failed",
  EHOSTUNREACH: "host unreachable",
  ETIMEDOUT: "connection timed out",
};

type ErrorLinks = {
  code?: unknown;
  cause?: unknown;
  errors?: unknown;
  socketError?: unknown;
  address?: unknown;
  port?: unknown;
};

/**
 * The errors behind an error: its cause, a node-redis socketError, and AggregateError members.
 *
 * @param err (unknown): the error.
 * @return (unknown[]): the inner errors.
 */
function innerErrors(err: unknown): unknown[] {
  const e = err as ErrorLinks;
  return [e.cause, e.socketError, ...(Array.isArray(e.errors) ? e.errors : [])].filter((x) => x != null);
}

/**
 * The first error in a chain that carries a known connection error code.
 *
 * @param exc (unknown): the error.
 * @param seen (Set<unknown>): errors already visited.
 * @return (ErrorLinks | null): the error, or null when no known code is present.
 */
function connectError(exc: unknown, seen = new Set<unknown>()): ErrorLinks | null {
  if (exc == null || seen.has(exc)) return null;
  seen.add(exc);
  const code = (exc as ErrorLinks).code;
  if (typeof code === "string" && CONNECT_CODES[code] !== undefined) return exc as ErrorLinks;
  return innerErrors(exc).reduce<ErrorLinks | null>((found, inner) => found ?? connectError(inner, seen), null);
}

/**
 * The connection failure of an error chain with the address it failed on, such as "connection refused 127.0.0.1:11434".
 *
 * @param exc (unknown): the error.
 * @return (string): the failure, or "" when the chain holds no connection error.
 */
export function connectionFailure(exc: unknown): string {
  const err = connectError(exc);
  if (err === null) return "";
  const phrase = CONNECT_CODES[err.code as string]!;
  return typeof err.address === "string" ? `${phrase} ${err.address}${err.port ? `:${err.port}` : ""}` : phrase;
}

/**
 * The reason an error gives, with an empty or dangling reason (such as "Cannot connect to API: ") filled in from a connection error code in its chain, else its causes, and with no trailing punctuation.
 *
 * @param exc (unknown): the thrown value.
 * @return (string): the reason, or the error name when nothing says more.
 */
export function errorReason(exc: unknown): string {
  const seen = new Set<unknown>();
  const reason = (err: unknown): string => {
    if (err == null || seen.has(err)) return "";
    seen.add(err);
    const text = errorMessage(err).split(/\s+/).join(" ").trim().replace(DRIVER_BOILERPLATE, "");
    const head = text.replace(/[\s.:;,]+$/, "");
    if (head && !/:[\s.]*$/.test(text)) return head;
    const code = (err as ErrorLinks).code;
    const found = connectError(err);
    const inner =
      (found && CONNECT_CODES[found.code as string]) ||
      innerErrors(err).reduce<string>((found, x) => found || reason(x), "") ||
      (typeof code === "string" ? code : "");
    return head && inner ? `${head}: ${inner}` : head || inner;
  };
  return reason(exc) || (exc instanceof Error ? exc.name : String(exc));
}
