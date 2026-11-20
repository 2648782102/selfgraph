import { version } from "../package.json";
import { pyRepr } from "./internal/py.js";

export const HINTS = {
  invalid_argument:
    "An argument, input field, or option value is wrong. The message names the field and what it expected. Fix the value and call again.",
  unknown_key:
    "A key or option name is not one the call accepts. Use the name the message suggests after `did you mean`.",
  invalid_setting:
    "A graph setting is missing or wrong: `uri`, `store`, `llm_provider`, `llm_model`, `llm_timeout`, `llm_concurrency`, or the provider in the LLM config. Fix the setting, flag, or `SELFGRAPH_*` variable the message names.",
  llm_required:
    "The call needs an LLM and none is configured. Configure one (the `llm` option, or `--llm-provider` and `--llm-model` in the CLI and MCP server), or choose a tier that needs no LLM.",
  embedder_required:
    "The `embeddings` seeds tier needs an embedder. Pass one with the SDK's `embedder` option, or choose another seeds tier.",
  schema_required:
    "Strict schema mode, or exporting the schema, needs a schema. Pass one (the `schema` option, or `--schema`), or use schema mode `warn`.",
  schema_violation:
    "A write breaks the schema in strict mode. Fix the facts to match the schema, change the schema, or use schema mode `warn`. A relation over its `max_count` can also retire the older one with contradiction mode `supersede`.",
  immutable_identity:
    "The change touches a field that is part of the object's id: an entity's type, a relation's endpoints and type, or a preference's subject, stance, key, and value. Create a new object instead of updating this one.",
  unknown_reference: "The input references an entity or relation that does not exist. Create it first, or fix the id.",
  relation_certified: "A certified relation blocks the change. Uncertify the relation, then run the call again.",
  relation_invalidated:
    "The relation was invalidated (superseded or retired). Create it again to reassert it, or act on its current version.",
  merge_reverted: "The merge was already reverted. There is nothing left to undo.",
  invalid_cursor: "The cursor did not come from this listing. Start the listing again without a cursor.",
  invalid_resolver_decision:
    "A custom entity resolver returned a bad decision. Return a `ResolutionDecision` whose target is one of the offered entities, with a confidence and a reason.",
  read_only_query: "`run_cypher` runs a single read. Write through the typed tools instead.",
  missing_package: "An optional package is not installed. Run the install command in the message.",
  not_found: "The object does not exist in this namespace. Check the id and the namespace, or create the object.",
  already_exists: "An object with this id already exists. Update it, or insert it, which upserts.",
  extraction_failed:
    "LLM extraction failed. The message carries the first failure. Check the LLM settings and the provider, then run the insert again.",
  llm_auth_failed:
    "The LLM provider got no API key, or rejected it. Pass `api_key` in the LLM config, or set `SELFGRAPH_LLM_API_KEY` or the provider's own variable.",
  llm_model_not_found: "The provider does not know the model. Check the model name and the provider.",
  invalid_llm_output:
    "The model, or a custom LLM client, returned output that does not match the pass's schema. Use another model, or fix the client.",
  invalid_prompt_template:
    "A prompt template is malformed. Keep `{text}` in the user template and use no placeholder other than `{text}` and `{instructions}`.",
  query_failed:
    "The backend rejected a query. The message keeps the engine's reason. Check any Cypher you passed yourself.",
  graph_closed: "The SelfGraph was closed. Create a new SelfGraph.",
  store_closed: "The store was closed, and closing a graph closes its store. Create a new store for each SelfGraph.",
  store_unreachable:
    "The SDK could not connect to the backend. Check that the server is running and that the address is right.",
  store_locked:
    "Another process (an MCP server or a script) has the embedded Kuzu database open, and Kuzu allows one process at a time. Close it, or point this one at another path.",
  store_auth_failed:
    "The backend rejected the credentials, or HydraDB got no token. Pass the right `auth` (CLI and MCP: `--auth`, or `SELFGRAPH_AUTH`).",
  database_not_found: "The database named in the settings does not exist on the server. Create it, or fix the name.",
  wrong_engine: "The server at the address is another engine. Pass the store that matches it, such as `neo4j`.",
  write_too_large:
    "A single node or edge row is larger than HydraDB accepts in one message. Split large property values or text.",
  write_conflict:
    "A concurrent write conflicted and the SDK's own retries ran out. Run the same call again: ids are deterministic and inserts are upserts, so a retry does not duplicate anything. Retryable, as is every `TransientError`.",
  store_busy:
    "The server timed out or was too busy to take the query. Run the same call again after a moment. Retryable.",
} as const;
export type ErrorCode = keyof typeof HINTS;
export const DOCS_URL = `https://github.com/hydra-db/selfgraph/blob/ts-v${version}/docs/errors.md`;

export type ErrorFields = {
  error: string;
  error_type: string;
  code: ErrorCode;
  field?: string;
  hint: string;
  retryable: boolean;
  docs: string;
};

export class SelfGraphError extends Error {
  static readonly code: ErrorCode = "invalid_argument";
  readonly code: ErrorCode;
  readonly field?: string;

  /**
   * An SDK error with a stable code that names the failure and its repair.
   *
   * @param message (string | undefined): what happened, with the fix when one applies.
   * @param options ({ cause?: unknown; code?: ErrorCode; field?: string } | undefined): the cause, the code when not the class default, and the argument, key, or setting at fault, when one is.
   */
  constructor(message?: string, options?: { cause?: unknown; code?: ErrorCode; field?: string }) {
    super(message, options);
    this.name = new.target.name;
    this.code = options?.code ?? (new.target as typeof SelfGraphError).code;
    if (options?.field !== undefined) this.field = options.field;
  }

  /** How to repair this error's code, as its docs section says. */
  get hint(): string {
    return HINTS[this.code];
  }

  /** Whether the same call can succeed when run again unchanged: true for a TransientError. */
  get retryable(): boolean {
    return this instanceof TransientError;
  }

  /** The docs section for this error's code, at the installed release. */
  get docs(): string {
    return `${DOCS_URL}#${this.code}`;
  }

  /**
   * The error as JSON-ready fields, as the MCP server returns it.
   *
   * @return (ErrorFields): error, error_type, code, field when one is at fault, hint, retryable, and docs.
   */
  toJSON(): ErrorFields {
    return {
      error: this.message,
      error_type: this.name,
      code: this.code,
      ...(this.field === undefined ? {} : { field: this.field }),
      hint: this.hint,
      retryable: this.retryable,
      docs: this.docs,
    };
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
 * Describe a failed connection in plain words ("connection refused") when the error chain says which.
 *
 * @param exc (unknown): the thrown value.
 * @return (string): the phrase, or the error's reason.
 */
export function connectionReason(exc: unknown): string {
  const err = connectError(exc);
  return err === null ? errorReason(exc) : CONNECT_CODES[err.code as string]!;
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
