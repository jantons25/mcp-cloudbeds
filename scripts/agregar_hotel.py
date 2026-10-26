"""Da de alta un hotel: verifica su API key, lo registra en hoteles.json y guarda la key en el keyring.

Uso (desde la raíz del proyecto):
    Windows: .\\.venv\\Scripts\\python.exe scripts\\agregar_hotel.py                    agregar / actualizar un hotel
             .\\.venv\\Scripts\\python.exe scripts\\agregar_hotel.py --alias plaza       con el alias ya decidido
             .\\.venv\\Scripts\\python.exe scripts\\agregar_hotel.py --estado            hoteles y origen de cada key
             .\\.venv\\Scripts\\python.exe scripts\\agregar_hotel.py --borrar plaza      quita la key (y opcionalmente el hotel)
    macOS:   ./.venv/bin/python scripts/agregar_hotel.py [...]

La key se escribe sin eco, se verifica contra Cloudbeds antes de guardarla y nunca se imprime.
El nombre, propertyID, zona horaria y moneda se toman de Cloudbeds (getHotels), no se tipean.
Se repite una vez por hotel; si una misma key ve varios hoteles, se puede usar para todos.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import keyring  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from cloudbeds_mcp.admin import (  # noqa: E402
    entry_from_cloudbeds,
    key_status,
    read_raw,
    remove_hotel,
    suggest_alias,
    upsert_hotel,
)
from cloudbeds_mcp.client import CloudbedsClient  # noqa: E402
from cloudbeds_mcp.config import (  # noqa: E402
    ALIAS_RE,
    ENV_PATH,
    HOTELES_PATH,
    KEYRING_SERVICE,
    Settings,
    keyring_user,
    load_catalog,
)
from cloudbeds_mcp.errors import CloudbedsError, ConfigError  # noqa: E402

REINICIO = "Cierra Claude desde la bandeja (clic derecho → Salir) y vuelve a abrirlo para que tome los cambios."


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _yes(prompt: str) -> bool:
    return _ask(f"{prompt} (s/N): ").lower() in ("s", "si", "sí")


async def _properties(api_key: str) -> tuple[str, list[dict[str, Any]]]:
    """Verifica la key y devuelve (usuario que la autorizó, propiedades que ve)."""
    settings = Settings(api_key=api_key, property_id=None, show_pii=False, tz=ZoneInfo("America/Lima"),
                        max_results=500, key_source="manual")
    async with CloudbedsClient(settings) as client:
        user = await client.get("userinfo")
        hotels = (await client.get_all("getHotels"))["data"]
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or "-"
    return name, hotels


def _choose(hotels: list[dict[str, Any]], property_id: str | None) -> dict[str, Any] | None:
    if property_id:
        match = [h for h in hotels if str(h.get("propertyID")) == property_id]
        if not match:
            print(f"[ERROR] La key no tiene acceso a la propiedad {property_id}.")
        return match[0] if match else None
    if len(hotels) == 1:
        return hotels[0]
    print("\nLa key tiene acceso a varias propiedades:")
    for i, h in enumerate(hotels, start=1):
        print(f"  {i}. {h.get('propertyName', '-')} (propertyID {h.get('propertyID', '-')})")
    choice = _ask(f"¿Cuál quieres agregar? (1-{len(hotels)}): ")
    if not choice.isdigit() or not 1 <= int(choice) <= len(hotels):
        print("Opción no válida. No se guardó nada.")
        return None
    return hotels[int(choice) - 1]


def agregar(alias: str | None, property_id: str | None) -> int:
    try:
        existentes = read_raw(HOTELES_PATH).get("hoteles", [])
    except ConfigError as exc:
        print(f"[CONFIG] Corrige hoteles.json antes de continuar: {exc}")
        return 2

    api_key = getpass.getpass("Pega la API key de Cloudbeds del hotel (no se mostrará) y pulsa Enter: ").strip()
    if not api_key:
        print("No se ingresó ninguna key. No se guardó nada.")
        return 1
    if not api_key.startswith("cbat_"):
        print("Aviso: la key no empieza por 'cbat_'. Se verificará igualmente.")
    try:
        user, hotels = asyncio.run(_properties(api_key))
    except CloudbedsError as exc:
        print(f"[ERROR] La key no funcionó, no se guardó: {exc}")
        return 1
    if not hotels:
        print("[ERROR] La key no tiene acceso a ninguna propiedad. No se guardó nada.")
        return 1
    print(f"Key verificada (autorizada por: {user}).")

    prop = _choose(hotels, property_id)
    if prop is None:
        return 1

    pid = str(prop.get("propertyID"))
    actual = next((h for h in existentes if str(h.get("property_id")) == pid), None)
    if not alias:
        sugerido = actual["alias"] if actual else suggest_alias(
            str(prop.get("propertyName") or ""), [h.get("nombre", "") for h in existentes]
        )
        alias = _ask(f"Alias corto para '{prop.get('propertyName')}' (Enter = {sugerido}): ") or sugerido
    if not ALIAS_RE.match(alias):
        print("[ERROR] El alias solo admite minúsculas, números y '_' (máx. 32), ej. 'san_jose'.")
        return 1

    entry = entry_from_cloudbeds(alias, prop)
    print(
        f"\n  Alias:        {entry['alias']}\n  Nombre:       {entry['nombre']}\n"
        f"  propertyID:   {entry['property_id']}\n  Zona horaria: {entry.get('tz', '- (se usará CLOUDBEDS_TZ)')}\n"
        f"  Moneda:       {entry.get('moneda', '-')}"
    )
    if any(h.get("alias") == alias for h in existentes) and not _yes(f"El alias '{alias}' ya existe. ¿Actualizarlo?"):
        print("No se cambió nada.")
        return 1
    try:
        accion = upsert_hotel(HOTELES_PATH, entry)
    except ConfigError as exc:
        print(f"[ERROR] {exc} No se guardó nada.")
        return 1
    keyring.set_password(KEYRING_SERVICE, keyring_user(alias), api_key)
    print(f"\nHotel {accion} en {HOTELES_PATH.name} y key guardada en el keyring ({keyring_user(alias)}).")
    print(REINICIO)
    return 0


def estado() -> int:
    load_dotenv(ENV_PATH, override=False)
    print(f"Backend de keyring: {keyring.get_keyring().__class__.__name__}")
    try:
        catalog = load_catalog(HOTELES_PATH)
    except ConfigError as exc:
        print(f"[CONFIG] {exc}")
        return 2
    if catalog is None:
        print(f"No existe {HOTELES_PATH.name}: el servidor funciona en modo de un solo hotel (ver guardar_key.py --estado).")
        return 0
    legacy_pid = os.getenv("CLOUDBEDS_PROPERTY_ID", "").strip() or None
    rows = key_status(catalog, legacy_pid)
    print(f"\nHoteles en {HOTELES_PATH}:")
    for r, h in zip(rows, catalog.hoteles):
        fuente = r["fuente"] or "SIN KEY: no estará disponible"
        tz = h.tz.key if h.tz else "CLOUDBEDS_TZ"
        print(f"  - {r['alias']:<12} {r['nombre']:<26} propertyID {r['property_id']:<10} {tz:<16} {h.moneda or '-':<4} key: {fuente}")
    faltan = [r["alias"] for r in rows if not r["fuente"]]
    if faltan:
        print(f"\n[ACCIÓN] Falta la key de: {', '.join(faltan)}. Ejecuta: scripts\\agregar_hotel.py --alias <alias>")
    return 1 if faltan else 0


def borrar(alias: str) -> int:
    try:
        keyring.delete_password(KEYRING_SERVICE, keyring_user(alias))
        print(f"Key de '{alias}' eliminada del keyring.")
    except keyring.errors.PasswordDeleteError:
        print(f"No había key de '{alias}' en el keyring.")
    if _yes(f"¿Quitar también '{alias}' de {HOTELES_PATH.name}?"):
        try:
            quitado = remove_hotel(HOTELES_PATH, alias)
        except ConfigError as exc:
            print(f"[CONFIG] {exc}")
            return 2
        print(f"Hotel '{alias}' quitado de {HOTELES_PATH.name}." if quitado else f"'{alias}' no estaba en {HOTELES_PATH.name}.")
    print(REINICIO)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Alta de hoteles de Cloudbeds para el MCP (key en el keyring).")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--estado", action="store_true", help="lista los hoteles y de dónde sale cada key (sin mostrarla)")
    group.add_argument("--borrar", metavar="ALIAS", help="elimina la key de un hotel del keyring")
    parser.add_argument("--alias", help="alias del hotel a agregar (minúsculas, ej. balta, plaza, san_jose)")
    parser.add_argument("--property-id", help="propertyID a usar si la key ve varias propiedades")
    args = parser.parse_args()
    if args.estado:
        return estado()
    if args.borrar:
        return borrar(args.borrar)
    return agregar(args.alias, args.property_id)


if __name__ == "__main__":
    sys.exit(main())
