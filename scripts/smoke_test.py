"""Prueba de humo fuera de Claude: verifica las keys y muestra los datos de cada hotel.

Uso (desde la raíz del proyecto):
    Windows: .\\.venv\\Scripts\\python.exe scripts\\smoke_test.py
    macOS:   ./.venv/bin/python scripts/smoke_test.py

Con hoteles.json prueba todos los hoteles y marca los que fallan sin detenerse.
Sin hoteles.json prueba el único hotel de .env, como siempre. Nunca imprime la API key.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cloudbeds_mcp.admin import currency_code  # noqa: E402
from cloudbeds_mcp.client import CloudbedsClient  # noqa: E402
from cloudbeds_mcp.config import (  # noqa: E402
    ENV_PATH,
    HOTELES_PATH,
    Hotel,
    configure_logging,
    load_catalog,
    load_hotels,
    load_settings,
)
from cloudbeds_mcp.errors import CloudbedsError, ConfigError  # noqa: E402


async def _check_hotel(hotel: Hotel) -> bool:
    """Verifica un hotel de hoteles.json: key, acceso a su propiedad y datos coherentes."""
    print(f"\n== {hotel.nombre} ({hotel.alias}) · propertyID {hotel.property_id}")
    if hotel.settings is None:
        print(f"  [FALTA KEY] {hotel.motivo}")
        return False
    s = hotel.settings
    async with CloudbedsClient(s) as client:
        try:
            user = await client.get("userinfo")
            name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or "-"
            details = (await client.get("getHotelDetails", {"propertyID": s.property_id})).get("data") or {}
        except CloudbedsError as exc:
            print(f"  [ERROR] {exc}")
            return False
    moneda = currency_code(details.get("propertyCurrency"))
    print(f"  Key: *** tomada de {s.key_source}, autorizada por {name}")
    print(f"  Nombre en Cloudbeds: {details.get('propertyName', '-')}")
    print(f"  Moneda: {moneda or '-'} · Zona horaria configurada: {s.tz.key}")
    ok = True
    if s.currency and moneda and s.currency != moneda:
        print(f"  [AVISO] hoteles.json dice moneda {s.currency}; corrígelo con agregar_hotel.py --alias {hotel.alias}.")
        ok = False
    return ok


async def main_multi() -> int:
    try:
        cfg = load_hotels()
    except ConfigError as exc:
        print(f"[CONFIG] {exc}")
        return 2
    print(f"Hoteles configurados en {HOTELES_PATH}: {len(cfg.hoteles)}")
    results = [await _check_hotel(h) for h in cfg.hoteles]
    fallaron = [h.alias for h, ok in zip(cfg.hoteles, results) if not ok]
    if fallaron:
        print(f"\n[RESULTADO] Con problemas: {', '.join(fallaron)}. El resto funciona.")
        return 1
    print("\nPrueba de humo OK en todos los hoteles.")
    return 0


def _currency(value: object) -> str:
    # getHotels devuelve una lista; getHotelDetails, un objeto
    if isinstance(value, list):
        value = value[0] if value else {}
    if isinstance(value, dict):
        return " ".join(filter(None, [value.get("currencyCode"), value.get("currencySymbol")])) or "-"
    return "-"


async def main() -> int:
    configure_logging()
    try:
        multi = load_catalog() is not None
    except ConfigError as exc:
        print(f"[CONFIG] {exc}")
        return 2
    if multi:
        return await main_multi()
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"[CONFIG] {exc}")
        return 2

    print(f"Configuración cargada desde {ENV_PATH} (API key: *** tomada de {settings.key_source})")

    async with CloudbedsClient(settings) as client:
        try:
            user = await client.get("userinfo")
            name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or "-"
            print(f"Key autorizada por el usuario: {name} (user_id {user.get('user_id', '-')})")

            hotels = (await client.get_all("getHotels"))["data"]
            if not hotels:
                print("La key no tiene acceso a ninguna propiedad.")
                return 1

            print(f"\nPropiedades accesibles con esta key: {len(hotels)}")
            for h in hotels:
                print(
                    f"  - {h.get('propertyName', '-')} | propertyID {h.get('propertyID', '-')} | "
                    f"moneda {_currency(h.get('propertyCurrency'))} | zona horaria {h.get('propertyTimezone', '-')}"
                )

            property_id = settings.property_id or str(hotels[0].get("propertyID"))
            details = (await client.get("getHotelDetails", {"propertyID": property_id})).get("data") or {}
            tz = next(
                (h.get("propertyTimezone") for h in hotels if str(h.get("propertyID")) == property_id), "-"
            )
            print("\nDetalle de la propiedad:")
            print(f"  Nombre:       {details.get('propertyName', '-')}")
            print(f"  propertyID:   {details.get('propertyID', property_id)}")
            print(f"  Tipo:         {details.get('propertyType', '-')}")
            print(f"  Moneda:       {_currency(details.get('propertyCurrency'))}")
            print(f"  Zona horaria: {tz} (configurada en .env: {settings.tz.key})")

            if not settings.property_id:
                print(
                    f"\n[ACCIÓN] CLOUDBEDS_PROPERTY_ID está vacío en .env. "
                    f"Agrega: CLOUDBEDS_PROPERTY_ID={property_id}"
                )
        except CloudbedsError as exc:
            print(f"[ERROR] {exc}")
            return 1

    print("\nPrueba de humo OK.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
