import { normalizeRelType } from "./ids.js";
import { cpLen } from "./internal/py.js";
import { canonicalEntityType, canonicalRelationType, entityIndex, lineage, type ParsedSchema } from "./schema.js";

export type Tokenize = (text: string) => Set<string>;

export type SchemaTermKind = "type" | "definition" | "relation";

const SINGULARS = new Map([
  ["calories", "calorie"],
  ["cookies", "cookie"],
  ["hoodies", "hoodie"],
  ["movies", "movie"],
  ["rookies", "rookie"],
  ["selfies", "selfie"],
  ["zombies", "zombie"],
  ["quizzes", "quiz"],
  ["echoes", "echo"],
  ["heroes", "hero"],
  ["potatoes", "potato"],
  ["tomatoes", "tomato"],
  ["vetoes", "veto"],
  ["buses", "bus"],
  ["statuses", "status"],
  ["status", "status"],
  ["analysis", "analysis"],
  ["news", "news"],
  ["series", "series"],
  ["species", "species"],
]);
const ES_AFTER = ["ss", "sh", "x", "zz", "tz"];
const VOWELS = "aeiou";

/**
 * Report whether a singular forms its plural with "es", so the plural loses both letters.
 *
 * @param base (string): a plural without its final "es".
 * @return (boolean): true after ss, sh, x, zz, or tz, and after a consonant followed by ch.
 */
function takesEs(base: string): boolean {
  if (ES_AFTER.some((end) => base.endsWith(end))) return true;
  const before = Array.from(base).at(-3);
  return base.endsWith("ch") && before !== undefined && !VOWELS.includes(before);
}

/**
 * Strip a plural ending so "customers" and "customer", or "addresses" and "address", compare equal.
 *
 * @param token (string): a casefolded token.
 * @return (string): the token in its singular form.
 */
export function stem(token: string): string {
  const known = SINGULARS.get(token);
  if (known !== undefined) return known;
  if (token.endsWith("ies") && cpLen(token) > 4) return `${token.slice(0, -3)}y`;
  if (token.endsWith("es") && cpLen(token) > 4 && takesEs(token.slice(0, -2))) return token.slice(0, -2);
  if (token.endsWith("s") && !token.endsWith("ss") && cpLen(token) > 3) return token.slice(0, -1);
  return token;
}

/**
 * Put spaces at camel-case and underscore boundaries, so InvoiceLine and WORKS_AT read as words.
 *
 * @param name (string): the type name.
 * @return (string): the name as space-separated words.
 */
export function spaced(name: string): string {
  return name.replace(/(?<=[a-z0-9])(?=[A-Z])/g, " ").replaceAll("_", " ");
}

/**
 * List the distinct surface forms of a term, each also split into words.
 *
 * @param names (readonly string[]): the name, aliases, and synonyms.
 * @return (string[]): the forms, in order.
 */
function forms(names: readonly string[]): string[] {
  return [...new Set(names.flatMap((name) => [name, spaced(name)]))];
}

/** Each definition form's names and declaring types, and each name's certified flag across every declaration. */
export interface DefinitionIndex {
  owners: Map<string, Map<string, string[]>>;
  certified: Map<string, boolean>;
}

/**
 * Index the schema's definitions by surface form, keeping every declaring entity type and every declaration.
 *
 * A name declared twice by one type, or by several types, keeps the synonyms of every declaration.
 *
 * @param schema (ParsedSchema | null): the schema, or null for no definitions.
 * @return (DefinitionIndex): each form's definitions and declaring types, and each name's certified flag.
 */
export function definitionIndex(schema: ParsedSchema | null): DefinitionIndex {
  const owners = new Map<string, Map<string, Set<string>>>();
  const certified = new Map<string, boolean>();
  for (const entity of schema?.entities ?? []) {
    for (const definition of entity.definitions) {
      certified.set(definition.name, (certified.get(definition.name) ?? true) && definition.certified);
      for (const form of forms([definition.name, ...definition.synonyms])) {
        const names = owners.get(form) ?? new Map<string, Set<string>>();
        names.set(definition.name, (names.get(definition.name) ?? new Set<string>()).add(entity.name));
        owners.set(form, names);
      }
    }
  }
  return {
    owners: new Map(
      [...owners].map(([form, names]) => [form, new Map([...names].map(([name, types]) => [name, [...types]]))]),
    ),
    certified,
  };
}

/**
 * List the terms the stored graph holds instances of, by kind, so a schema term alone never grounds a question.
 *
 * A type is held when an entity of it or of a subtype is stored, and a relation type when a relation of it is stored. The stored types themselves are held too. A definition is held through its declaring entity types, which the caller checks against the held types.
 *
 * @param schema (ParsedSchema | null): the schema, or null for the stored types only.
 * @param entityTypes (Iterable<string>): the stored entities' types.
 * @param relationTypes (Iterable<string>): the stored relations' types.
 * @return (Record<"type" | "relation", Set<string>>): for "type" and "relation", the held term names.
 */
export function groundedTerms(
  schema: ParsedSchema | null,
  entityTypes: Iterable<string>,
  relationTypes: Iterable<string>,
): Record<"type" | "relation", Set<string>> {
  const types = new Set(entityTypes);
  const rels = new Set(relationTypes);
  const held: Record<"type" | "relation", Set<string>> = { type: new Set(types), relation: new Set(rels) };
  if (schema === null) return held;
  const index = entityIndex(schema);
  for (const etype of types) {
    const entity = index.get(canonicalEntityType(etype, schema));
    if (entity !== undefined) for (const t of lineage(entity, index)) held.type.add(t.name);
  }
  const stored = new Set([...rels].map((t) => normalizeRelType(canonicalRelationType(t, schema))));
  for (const r of schema.relations) if (stored.has(normalizeRelType(r.type))) held.relation.add(r.type);
  return held;
}

/**
 * Map every surface form of the schema's terms, by kind, to the terms it names and whether each is certified.
 *
 * Entity types and relation types are named by name, alias, and synonym, and definitions by name and synonym; each form is also listed split into words, so InvoiceLine reads as "Invoice Line". A type or relation form names the first term that declares it. A definition form names every definition that declares it, and a name declared by several entity types, or twice by one, is certified only when every declaration is.
 *
 * @param schema (ParsedSchema | null): the schema, or null for no terms.
 * @param definitions (DefinitionIndex): the schema's definition index when the caller already built it.
 * @return (Record<SchemaTermKind, Map<string, Array<readonly [string, boolean]>>>): for "type", "definition", and "relation", each form's terms and their certified flags.
 */
export function schemaForms(
  schema: ParsedSchema | null,
  definitions: DefinitionIndex = definitionIndex(schema),
): Record<SchemaTermKind, Map<string, Array<readonly [string, boolean]>>> {
  const found: Record<SchemaTermKind, Map<string, Array<readonly [string, boolean]>>> = {
    type: new Map(),
    definition: new Map(),
    relation: new Map(),
  };
  if (schema === null) return found;
  const note = (kind: SchemaTermKind, term: string, names: readonly string[], certified: boolean): void => {
    for (const form of forms(names)) if (!found[kind].has(form)) found[kind].set(form, [[term, certified]]);
  };
  for (const entity of schema.entities) {
    note("type", entity.name, [entity.name, ...entity.aliases, ...entity.synonyms], entity.certified);
  }
  for (const [form, names] of definitions.owners) {
    found.definition.set(
      form,
      [...names.keys()].map((name) => [name, definitions.certified.get(name)!] as const),
    );
  }
  for (const relation of schema.relations) {
    note("relation", relation.type, [relation.type, ...relation.aliases, ...relation.synonyms], relation.certified);
  }
  return found;
}

/**
 * Add the words of each entity type and its subtypes when a question names the type or a definition.
 *
 * A definition adds the words of every entity type that declares it and those types' subtypes.
 *
 * @param tokens (ReadonlySet<string>): the question's content tokens.
 * @param schema (ParsedSchema | null): the schema, or null for no expansion.
 * @param tokenize (Tokenize): splits text into content tokens.
 * @return (Set<string>): the tokens with the matched type and subtype names added.
 */
export function expandTokens(
  tokens: ReadonlySet<string>,
  schema: ParsedSchema | null,
  tokenize: Tokenize,
): Set<string> {
  const out = new Set(tokens);
  if (schema === null) return out;
  const index = entityIndex(schema);
  const stems = new Set([...tokens].map(stem));
  const named = new Map<string, Set<string>>();
  const add = (form: string, type: string) => named.set(form, (named.get(form) ?? new Set<string>()).add(type));
  for (const [form, terms] of schemaForms(schema).type) for (const [term] of terms) add(form, term);
  for (const [form, names] of definitionIndex(schema).owners) {
    for (const types of names.values()) for (const owner of types) add(form, owner);
  }
  for (const [form, types] of named) {
    const words = [...tokenize(form)].map(stem);
    if (!words.length || !words.every((w) => stems.has(w))) continue;
    for (const entity of schema.entities) {
      if ([...lineage(entity, index)].some((t) => types.has(t.name))) {
        for (const token of tokenize(entity.name)) out.add(token);
      }
    }
  }
  return out;
}
