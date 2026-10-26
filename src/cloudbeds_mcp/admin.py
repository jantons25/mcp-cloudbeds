"""Alta y mantenimiento de hoteles (lo usa scripts/agregar_hotel.py).

Aquí está la lógica que se puede probar sin consola: armar la entrada de hoteles.json a
partir de lo que devuelve Cloudbeds, escribir el JSON validado y resumir de dónde sale
la key de cada hotel. Nunca se lee ni se muestra el valor de una key.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import (
    ALIAS_RE,
    Catalog,
    env_key_var,
    key_from_keyring,
    keyring_user,
    load_catalog,
)
from .errors import ConfigError
from .hotels import normalizar, palabras_de_marca


def currency_code(value: Any) -> str | None:
    """getHotels/getHotelDetails devuelven la moneda como objeto, lista de objetos o texto."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("currencyCode")
    return value.strip().upper() if isinstance(value, str) and value.strip() else None


def valid_tz(name: Any) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return name.strip()


def suggest_alias(nombre: str, otros_nombres: list[str]) -> str:
    """Alias sugerido: el nombre sin la marca. 'Zentra San José' -> 'san_jose'.

    Si aún no hay otros hoteles, se quita la primera palabra cuando el nombre tiene varias
    (suele ser la marca: 'Zentra Balta' -> 'balta').
    """
    tokens = normalizar(nombre)
    if otros_nombres:
        marca = palabras_de_marca([nombre, *otros_nombres])
        tokens = tuple(t for t in tokens if t not in marca) or tokens
    elif len(tokens) > 1:
        tokens = tokens[1:]
    alias = "_".join(tokens)[:32].strip("_")
    return alias if ALIAS_RE.match(alias) else "hotel"


def entry_from_cloudbeds(alias: str, prop: dict[str, Any]) -> dict[str, Any]:
    """Entrada de hoteles.json con los datos reales de la propiedad (de getHotels)."""
    if not ALIAS_RE.match(alias):
        raise ConfigError("El alias solo admite minúsculas, números y '_' (máx. 32), ej. 'san_jose'.")
    entry: dict[str, Any] = {
        "alias": alias,
        "nombre": str(prop.get("propertyName") or alias).strip(),
        "property_id": str(prop.get("propertyID") or "").strip(),
    }
    tz = valid_tz(prop.get("propertyTimezone"))
    if tz:
        entry["tz"] = tz
    moneda = currency_code(prop.get("propertyCurrency"))
    if moneda:
        entry["moneda"] = moneda
    return entry


def read_raw(path: Path) -> dict[str, Any]:
    """hoteles.json tal cual (con comentarios y campos extra), o uno vacío si no existe."""
    if not path.exists():
        return {"hoteles": []}
    load_catalog(path)  # no se edita un archivo inválido: primero hay que corregirlo
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_validated(path: Path, data: dict[str, Any]) -> None:
    """Escribe de forma atómica y solo si el resultado es un hoteles.json válido."""
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=".hoteles-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        load_catalog(Path(tmp))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def upsert_hotel(path: Path, entry: dict[str, Any]) -> str:
    """Agrega o actualiza un hotel por alias. Conserva los campos que no vienen de Cloudbeds
    (por ejemplo otros_nombres). Devuelve 'agregado' o 'actualizado'."""
    data = read_raw(path)
    hoteles = data.setdefault("hoteles", [])
    for h in hoteles:
        if h.get("alias") != entry["alias"] and str(h.get("property_id")) == entry["property_id"]:
            raise ConfigError(
                f"La propiedad {entry['property_id']} ya está registrada con el alias '{h.get('alias')}'."
            )
    for h in hoteles:
        if h.get("alias") == entry["alias"]:
            h.update(entry)
            _write_validated(path, data)
            return "actualizado"
    hoteles.append(entry)
    _write_validated(path, data)
    return "agregado"


def remove_hotel(path: Path, alias: str) -> bool:
    """Quita un hotel de hoteles.json. Si era el último, borra el archivo (vuelve al modo legacy)."""
    data = read_raw(path)
    hoteles = data.get("hoteles", [])
    restantes = [h for h in hoteles if h.get("alias") != alias]
    if len(restantes) == len(hoteles):
        return False
    if not restantes:
        path.unlink()
        return True
    data["hoteles"] = restantes
    if data.get("predeterminado") == alias:
        data.pop("predeterminado")
    _write_validated(path, data)
    return True


def key_status(catalog: Catalog, legacy_property_id: str | None) -> list[dict[str, Any]]:
    """De dónde tomará el servidor la key de cada hotel (sin leer ni mostrar su valor)."""
    rows = []
    unico = len(catalog.hoteles) == 1
    for h in catalog.hoteles:
        if key_from_keyring(keyring_user(h.alias)):
            fuente = f"keyring ({keyring_user(h.alias)})"
        elif os.getenv(env_key_var(h.alias), "").strip():
            fuente = f"variable {env_key_var(h.alias)}"
        elif (unico or h.property_id == legacy_property_id) and (
            key_from_keyring() or os.getenv("CLOUDBEDS_API_KEY", "").strip()
        ):
            fuente = "key legacy (guardar_key.py / .env)"
        else:
            fuente = None
        rows.append({"alias": h.alias, "nombre": h.nombre, "property_id": h.property_id, "fuente": fuente})
    return rows
