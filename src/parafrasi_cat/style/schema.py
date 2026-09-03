"""Validació mínima d'un document JSON contra un subconjunt de JSON Schema.

Només es fan servir les paraules clau necessàries per a l'esquema de
l'empremta estilística (``style/fingerprint.schema.json``): ``type``,
``properties``, ``required``, ``additionalProperties``, ``items``, ``enum``,
``const``, ``minimum``, ``maximum``, ``minItems``, ``maxItems``, ``anyOf`` i
referències ``$ref`` a ``#/$defs/...``. Així el projecte no depèn de cap
biblioteca externa de validació.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from parafrasi_cat.core.errors import ResourceError

SCHEMA_FILE = "style/fingerprint.schema.json"

_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, Mapping),
    "array": lambda v: isinstance(v, list | tuple),
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def load_schema(path: str | Path) -> dict[str, object]:
    file = Path(path)
    if not file.is_file():
        raise ResourceError(f"No s'ha trobat l'esquema «{file}»")
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ResourceError(f"No s'ha pogut llegir l'esquema «{file}»: {exc}") from exc
    if not isinstance(data, dict):
        raise ResourceError(f"L'esquema «{file}» ha de ser un objecte JSON")
    return {str(k): v for k, v in data.items()}


def validate(data: object, schema: Mapping[str, object]) -> list[str]:
    """Retorna la llista d'errors (buida si el document compleix l'esquema)."""
    errors: list[str] = []
    _validate(data, schema, schema, "$", errors)
    return errors


def _resolve(ref: str, root: Mapping[str, object]) -> Mapping[str, object]:
    if not ref.startswith("#/"):
        raise ResourceError(f"Referència d'esquema no suportada: {ref}")
    node: object = root
    for part in ref[2:].split("/"):
        if not isinstance(node, Mapping) or part not in node:
            raise ResourceError(f"Referència d'esquema no trobada: {ref}")
        node = node[part]
    if not isinstance(node, Mapping):
        raise ResourceError(f"La referència {ref} no apunta a un esquema")
    return node


def _validate(
    value: object,
    schema: Mapping[str, object],
    root: Mapping[str, object],
    path: str,
    errors: list[str],
) -> None:
    ref = schema.get("$ref")
    if isinstance(ref, str):
        _validate(value, _resolve(ref, root), root, path, errors)
        return

    any_of = schema.get("anyOf")
    if isinstance(any_of, Sequence) and not isinstance(any_of, str):
        for option in any_of:
            if isinstance(option, Mapping):
                trial: list[str] = []
                _validate(value, option, root, path, trial)
                if not trial:
                    break
        else:
            errors.append(f"{path}: no compleix cap de les alternatives (anyOf)")
            return

    expected = schema.get("type")
    if expected is not None:
        if isinstance(expected, str):
            types = [expected]
        elif isinstance(expected, Sequence):
            types = [str(t) for t in expected]
        else:
            raise ResourceError(f"Tipus d'esquema invàlid a {path}")
        if not any(_TYPE_CHECKS[t](value) for t in types):
            errors.append(f"{path}: s'esperava el tipus {'/'.join(map(str, types))}")
            return

    if "enum" in schema:
        options = schema["enum"]
        if isinstance(options, Sequence) and value not in options:
            errors.append(f"{path}: valor «{value}» fora de l'enumeració")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: s'esperava el valor constant «{schema['const']}»")

    if isinstance(value, int | float) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, int | float) and value < minimum:
            errors.append(f"{path}: {value} és menor que el mínim {minimum}")
        if isinstance(maximum, int | float) and value > maximum:
            errors.append(f"{path}: {value} és més gran que el màxim {maximum}")

    if isinstance(value, Mapping):
        _validate_object(value, schema, root, path, errors)
    elif isinstance(value, list | tuple):
        _validate_array(value, schema, root, path, errors)


def _validate_object(
    value: Mapping[object, object],
    schema: Mapping[str, object],
    root: Mapping[str, object],
    path: str,
    errors: list[str],
) -> None:
    properties = schema.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    required = schema.get("required")
    if isinstance(required, Sequence) and not isinstance(required, str):
        for name in required:
            if name not in value:
                errors.append(f"{path}: falta la clau obligatòria «{name}»")
    for key, item in value.items():
        child_path = f"{path}.{key}"
        subschema = properties.get(key)
        if isinstance(subschema, Mapping):
            _validate(item, subschema, root, child_path, errors)
            continue
        additional = schema.get("additionalProperties", True)
        if additional is False:
            errors.append(f"{child_path}: clau no permesa")
        elif isinstance(additional, Mapping):
            _validate(item, additional, root, child_path, errors)


def _validate_array(
    value: Sequence[object],
    schema: Mapping[str, object],
    root: Mapping[str, object],
    path: str,
    errors: list[str],
) -> None:
    min_items = schema.get("minItems")
    max_items = schema.get("maxItems")
    if isinstance(min_items, int) and len(value) < min_items:
        errors.append(f"{path}: calen almenys {min_items} elements")
    if isinstance(max_items, int) and len(value) > max_items:
        errors.append(f"{path}: hi ha més de {max_items} elements")
    items = schema.get("items")
    if isinstance(items, Mapping):
        for index, item in enumerate(value):
            _validate(item, items, root, f"{path}[{index}]", errors)
