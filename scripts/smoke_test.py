"""Prueba de humo fuera de Claude: verifica la key y muestra los datos del hotel.

Uso (desde la raíz del proyecto):
    Windows: .\\.venv\\Scripts\\python.exe scripts\\smoke_test.py
    macOS:   ./.venv/bin/python scripts/smoke_test.py

Nunca imprime la API key.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cloudbeds_mcp.client import CloudbedsClient  # noqa: E402
from cloudbeds_mcp.config import ENV_PATH, configure_logging, load_settings  # noqa: E402
from cloudbeds_mcp.errors import CloudbedsError, ConfigError  # noqa: E402


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
