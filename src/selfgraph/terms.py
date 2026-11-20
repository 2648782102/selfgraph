from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import NamedTuple

from .ids import normalize_rel_type
from .schema import Schema, _entity_index, _lineage, canonical_entity_type, canonical_relation_type

__all__ = ["DefinitionIndex", "definition_index", "expand_tokens", "grounded_terms", "schema_forms", "stem"]

Tokenize = Callable[[str], set[str]]

_SINGULARS = {
    "calories": "calorie",
    "cookies": "cookie",
    "hoodies": "hoodie",
    "movies": "movie",
    "rookies": "rookie",
    "selfies": "selfie",
    "zombies": "zombie",
    "quizzes": "quiz",
    "echoes": "echo",
    "heroes": "hero",
    "potatoes": "potato",
    "tomatoes": "tomato",
    "vetoes": "veto",
    "buses": "bus",
    "statuses": "status",
    "status": "status",
    "analysis": "analysis",
    "news": "news",
    "series": "series",
    "species": "species",
}
_ES_AFTER = ("ss", "sh", "x", "zz", "tz")
_VOWELS = "aeiou"


def _takes_es(base: str) -> bool:
    """Report whether a singular forms its plural with "es", so the plural loses both letters.

    @param base (str): a plural without its final "es".
    @return (bool): True after ss, sh, x, zz, or tz, and after a consonant followed by ch.
    """
    if base.endswith(_ES_AFTER):
        return True
    return base.endswith("ch") and len(base) > 2 and base[-3] not in _VOWELS


def stem(token: str) -> str:
    """Strip a plural ending so "customers" and "customer", or "addresses" and "address", compare equal.

    @param token (str): a casefolded token.
    @return (str): the token in its singular form.
    """
    if token in _SINGULARS:
        return _SINGULARS[token]
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("es") and len(token) > 4 and _takes_es(token[:-2]):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def _spaced(name: str) -> str:
    """Put spaces at camel-case and underscore boundaries, so InvoiceLine and WORKS_AT read as words.

    @param name (str): the type name.
    @return (str): the name as space-separated words.
    """
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).replace("_", " ")


def _forms(names: Iterable[str]) -> list[str]:
    """List the distinct surface forms of a term, each also split into words.

    @param names (Iterable[str]): the name, aliases, and synonyms.
    @return (list[str]): the forms, in order.
    """
    return list(dict.fromkeys(form for name in names for form in (name, _spaced(name))))


class DefinitionIndex(NamedTuple):
    """Each definition form's names and declaring types, and each name's certified flag across every declaration."""

    owners: dict[str, dict[str, list[str]]]
    certified: dict[str, bool]


def definition_index(schema: Schema | None) -> DefinitionIndex:
    """Index the schema's definitions by surface form, keeping every declaring entity type and every declaration.

    A name declared twice by one type, or by several types, keeps the synonyms of every declaration.

    @param schema (Schema | None): the schema, or None for no definitions.
    @return (DefinitionIndex): each form's definitions and declaring types, and each name's certified flag.
    """
    owners: dict[str, dict[str, dict[str, None]]] = {}
    certified: dict[str, bool] = {}
    for entity in schema.entities if schema is not None else ():
        for definition in entity.definitions:
            certified[definition.name] = certified.get(definition.name, True) and definition.certified
            for form in _forms([definition.name, *definition.synonyms]):
                owners.setdefault(form, {}).setdefault(definition.name, {})[entity.name] = None
    return DefinitionIndex(
        {form: {name: list(types) for name, types in names.items()} for form, names in owners.items()}, certified
    )


def schema_forms(
    schema: Schema | None, definitions: DefinitionIndex | None = None
) -> dict[str, dict[str, list[tuple[str, bool]]]]:
    """Map every surface form of the schema's terms, by kind, to the terms it names and whether each is certified.

    Entity types and relation types are named by name, alias, and synonym, and definitions by name and synonym; each
    form is also listed split into words, so InvoiceLine reads as "Invoice Line". A type or relation form names the
    first term that declares it. A definition form names every definition that declares it, and a name declared by
    several entity types, or twice by one, is certified only when every declaration is.

    @param schema (Schema | None): the schema, or None for no terms.
    @param definitions (DefinitionIndex | None): the schema's definition index when the caller already built it.
    @return (dict[str, dict[str, list[tuple[str, bool]]]]): for "type", "definition", and "relation", each form's
        terms and their certified flags.
    """
    found: dict[str, dict[str, list[tuple[str, bool]]]] = {"type": {}, "definition": {}, "relation": {}}
    if schema is None:
        return found

    def note(kind: str, term: str, names: Iterable[str], certified: bool) -> None:
        for form in _forms(names):
            found[kind].setdefault(form, [(term, certified)])

    for entity in schema.entities:
        note("type", entity.name, [entity.name, *entity.aliases, *entity.synonyms], entity.certified)
    definitions = definition_index(schema) if definitions is None else definitions
    for form, names in definitions.owners.items():
        found["definition"][form] = [(name, definitions.certified[name]) for name in names]
    for relation in schema.relations:
        note("relation", relation.type, [relation.type, *relation.aliases, *relation.synonyms], relation.certified)
    return found


def grounded_terms(
    schema: Schema | None, entity_types: Iterable[str], relation_types: Iterable[str]
) -> dict[str, set[str]]:
    """List the terms the stored graph holds instances of, by kind, so a schema term alone never grounds a question.

    A type is held when an entity of it or of a subtype is stored, and a relation type when a relation of it is
    stored. The stored types themselves are held too. A definition is held through its declaring entity types, which
    the caller checks against the held types.

    @param schema (Schema | None): the schema, or None for the stored types only.
    @param entity_types (Iterable[str]): the stored entities' types.
    @param relation_types (Iterable[str]): the stored relations' types.
    @return (dict[str, set[str]]): for "type" and "relation", the held term names.
    """
    types, rels = set(entity_types), set(relation_types)
    held: dict[str, set[str]] = {"type": set(types), "relation": set(rels)}
    if schema is None:
        return held
    index = _entity_index(schema)
    for etype in types:
        entity = index.get(canonical_entity_type(etype, schema))
        if entity is not None:
            held["type"].update(t.name for t in _lineage(entity, index))
    stored = {normalize_rel_type(canonical_relation_type(t, schema)) for t in rels}
    held["relation"].update(r.type for r in schema.relations if normalize_rel_type(r.type) in stored)
    return held


def expand_tokens(tokens: set[str], schema: Schema | None, tokenize: Tokenize) -> set[str]:
    """Add the words of each entity type and its subtypes when a question names the type or a definition.

    A definition adds the words of every entity type that declares it and those types' subtypes.

    @param tokens (set[str]): the question's content tokens.
    @param schema (Schema | None): the schema, or None for no expansion.
    @param tokenize (Tokenize): splits text into content tokens.
    @return (set[str]): the tokens with the matched type and subtype names added.
    """
    if schema is None:
        return tokens
    index = _entity_index(schema)
    stems = {stem(t) for t in tokens}
    out = set(tokens)
    named: dict[str, set[str]] = {}
    for form, terms in schema_forms(schema)["type"].items():
        named.setdefault(form, set()).update(term for term, _ in terms)
    for form, names in definition_index(schema).owners.items():
        named.setdefault(form, set()).update(owner for owners in names.values() for owner in owners)
    for form, types in named.items():
        words = {stem(t) for t in tokenize(form)}
        if words and words <= stems:
            for entity in schema.entities:
                if any(t.name in types for t in _lineage(entity, index)):
                    out |= tokenize(entity.name)
    return out
