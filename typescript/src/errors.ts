import { pyRepr } from "./internal/py.js";

export type ErrorCode =
  | "invalid_argument"
  | "unknown_key"
  | "invalid_setting"
  | "llm_required"
  | "embedder_required"
  | "schema_required"
  | "schema_violation"
  | "immutable_identity"
  | "unknown_reference"
  | "relation_certified"
  | "relation_invalidated"
  | "merge_reverted"
  | "invalid_cursor"
  | "invalid_resolver_decision"
  | "read_only_query"
  | "missing_package"
  | "not_found"
  | "already_exists"
  | "extraction_failed"
  | "llm_auth_failed"
  | "llm_model_not_found"
  | "invalid_llm_output"
  | "invalid_prompt_template"
  | "query_failed"
  | "graph_closed"
  | "store_closed"
  | "store_unreachable"
  | "store_locked"
  | "store_auth_failed"
  | "database_not_found"
  | "wrong_engine"
  | "write_too_large"
  | "write_conflict"
  | "store_busy";
export const DOCS_URL = "https://github.com/hydra-db/selfgraph/blob/main/docs/errors.md";

export class SelfGraphError extends Error {
  static readonly code: ErrorCode = "invalid_argument";
  readonly code: ErrorCode;

  /**
   * An SDK error with a stable code that names the failure and its repair.
   *
   * @param message (string | undefined): what happened, with the fix when one applies.
   * @param options ({ cause?: unknown; code?: ErrorCode } | undefined): the cause, and the code when not the class default.
   */
  constructor(message?: string, options?: { cause?: unknown; code?: ErrorCode }) {
    super(message, options);
    this.name = new.target.name;
    this.code = options?.code ?? (new.target as typeof SelfGraphError).code;
  }

  /** Whether the same call can succeed when run again unchanged: true for a TransientError. */
  get retryable(): boolean {
    return this instanceof TransientError;
  }

  /** The docs section that explains this error's code and its repair. */
  get docs(): string {
    return `${DOCS_URL}#${this.code}`;
  }

  /**
   * The error as JSON-ready fields, as the MCP server returns it.
   *
   * @return ({ error: string; error_type: string; code: ErrorCode; retryable: boolean; docs: string }): the fields.
   */
  toJSON(): { error: string; error_type: string; code: ErrorCode; retryable: boolean; docs: string } {
    return { error: this.message, error_type: this.name, code: this.code, retryable: this.retryable, docs: this.docs };
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
  static override readonly code: ErrorCode = "not_found";

  constructor(objectType: string, objectId: string, message?: string) {
    super(objectType, objectId, "does not exist", message);
  }
}

export class ConflictError extends ObjectError {
  static override readonly code: ErrorCode = "already_exists";

  constructor(objectType: string, objectId: string) {
    super(objectType, objectId, "already exists");
  }
}

export class ExtractionError extends SelfGraphError {
  static override readonly code: ErrorCode = "extraction_failed";
}

export class PromptTemplateError extends SelfGraphError {
  static override readonly code: ErrorCode = "invalid_prompt_template";
}

export class StoreError extends SelfGraphError {
  static override readonly code: ErrorCode = "query_failed";
}

export class TransientError extends StoreError {
  static override readonly code: ErrorCode = "write_conflict";
}

export const LLM_HINT = "pass llm in the SelfGraph options (or set SELFGRAPH_LLM_PROVIDER and SELFGRAPH_LLM_MODEL)";
export const STORE_CLOSED_MESSAGE = "this store is closed; create a new store for each SelfGraph";
export const TOKEN_HINT = "pass auth: TOKEN in the HydraDBStore options (or set SELFGRAPH_AUTH)";
export const STORE_KUZU_HINT = 'pass store: "kuzu" (or SELFGRAPH_STORE=kuzu)';
export const OTHER_ENGINE_HINT = 'pass store: "neo4j" (or store: "memgraph")';
export const DECAY_HINT = "run maintenance.decay({ dry_run: false }) first";
export const KEY_SOURCES = "api_key in the llm config (or SELFGRAPH_LLM_API_KEY)";

/**
 * The error for a feature that needs an LLM when none is configured.
 *
 * @param what (string): the feature, such as "level 'max'".
 * @return (ValidationError): the error, with code llm_required.
 */
export function needsLlm(what: string): ValidationError {
  return new ValidationError(`${what} needs an LLM: ${LLM_HINT}`, { code: "llm_required" });
}

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
