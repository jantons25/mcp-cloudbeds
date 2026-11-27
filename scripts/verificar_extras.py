"""Verifica, fuera de Claude, que el MCP lee los extras y su detalle por producto en cada sede.

Uso (desde la raíz del proyecto):
    Windows: .\\.venv\\Scripts\\python.exe scripts\\verificar_extras.py                       últimos 7 días, todas las sedes
             .\\.venv\\Scripts\\python.exe scripts\\verificar_extras.py --alias balta         una sede
             .\\.venv\\Scripts\\python.exe scripts\\verificar_extras.py --desde 2026-11-01 --hasta 2026-11-15
             .\\.venv\\Scripts\\python.exe scripts\\verificar_extras.py --todos               todos los productos de cada rubro
    macOS:   ./.venv/bin/python scripts/verificar_extras.py [...]

Llama a la misma herramienta que usa Claude (extras_periodo con agrupar="producto"), así que
prueba la key, los scopes read:item y read:payment, el catálogo de ítems y el mapeo a rubros.
Solo lee. No muestra la key ni datos de huéspedes: solo rubros, productos, importes y unidades.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cloudbeds_mcp import server  # noqa: E402
from cloudbeds_mcp.config import Hotel, load_hotels  # noqa: E402
from cloudbeds_mcp.errors import ConfigError  # noqa: E402
from cloudbeds_mcp.finanzas import SIN_PRODUCTO, SIN_RUBRO  # noqa: E402

TOP = 5  # productos por rubro que se muestran sin --todos


def _fecha(valor: str) -> date:
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise argparse.ArgumentTypeError("usa el formato YYYY-MM-DD") from None


def _monto(moneda: str | None, importe: float) -> str:
    return f"{moneda or ''} {importe:,.2f}".strip()


async def _verificar(hotel: Hotel, desde: date | None, hasta: date | None, todos: bool) -> bool:
    print(f"\n== {hotel.nombre or hotel.alias} ({hotel.alias}) · propertyID {hotel.property_id}")
    if hotel.settings is None:
        print(f"  [FALTA KEY] {hotel.motivo}")
        return False
    hoy = datetime.now(hotel.tz).date()
    d2 = hasta or hoy - timedelta(days=1)
    d1 = desde or d2 - timedelta(days=6)
    texto = await server.extras_periodo(d1.isoformat(), d2.isoformat(), agrupar="producto", hotel=hotel.alias)
    try:
        data = json.loads(texto)
    except json.JSONDecodeError:
        print(f"  [ERROR] {texto}")
        return False

    moneda = data.get("moneda")
    total = data.get("total") or {}
    rubros = data.get("por_rubro") or {}
    print(f"  Periodo: {d1} a {d2}")
    print(f"  Total de extras: {_monto(moneda, total.get('importe', 0))} · "
          f"{total.get('movimientos', 0)} movimientos · {total.get('unidades', 0):g} unidades")
    if not rubros:
        print("  [AVISO] La lectura funcionó, pero no hay extras en el periodo. Prueba con otras fechas.")
        return True

    for nombre, r in rubros.items():
        productos = r.get("productos") or {}
        print(f"  - {nombre}: {_monto(moneda, r.get('importe', 0))} · {len(productos)} producto(s)")
        lista = list(productos.items())
        for prod, p in lista if todos else lista[:TOP]:
            print(f"      {prod}: {_monto(moneda, p.get('importe', 0))} ({p.get('unidades', 0):g} u.)")
        if not todos and len(lista) > TOP:
            print(f"      … y {len(lista) - TOP} más (usa --todos para verlos)")

    sin_rubro = rubros.get(SIN_RUBRO)
    sin_prod = sum(
        (r.get("productos") or {}).get(SIN_PRODUCTO, {}).get("importe", 0)
        for nombre, r in rubros.items() if nombre != SIN_RUBRO  # ese ya tiene su propio aviso
    )
    if sin_rubro:
        print(f"  [AVISO] {_monto(moneda, sin_rubro.get('importe', 0))} en '{SIN_RUBRO}': ítems que no se "
              "reconocen en el catálogo de Cloudbeds.")
    if sin_prod:
        print(f"  [AVISO] {_monto(moneda, sin_prod)} en productos sin identificar (nombre distinto al catálogo).")
    if data.get("advertencia"):
        print(f"  [AVISO] {data['advertencia']}")
    print("  OK: lee los extras y el detalle por producto.")
    return True


async def main() -> int:
    parser = argparse.ArgumentParser(description="Verifica la lectura de extras por rubro y producto en cada sede.")
    parser.add_argument("--alias", help="solo esta sede (ej. balta, plaza, san_jose)")
    parser.add_argument("--desde", type=_fecha, help="primer día, YYYY-MM-DD (por defecto, hace 7 días)")
    parser.add_argument("--hasta", type=_fecha, help="último día, YYYY-MM-DD (por defecto, ayer)")
    parser.add_argument("--todos", action="store_true", help="muestra todos los productos de cada rubro")
    args = parser.parse_args()

    logging.disable(logging.INFO)  # solo el resultado; los avisos y errores sí se muestran
    try:
        cfg = load_hotels()
    except ConfigError as exc:
        print(f"[CONFIG] {exc}")
        return 2
    hoteles = [h for h in cfg.hoteles if not args.alias or h.alias == args.alias]
    if not hoteles:
        print(f"[ERROR] No hay una sede '{args.alias}' en hoteles.json.")
        return 2
    try:
        results = [await _verificar(h, args.desde, args.hasta, args.todos) for h in hoteles]
    finally:
        await server._get_registry().aclose()

    fallaron = [h.alias for h, ok in zip(hoteles, results) if not ok]
    if fallaron:
        print(f"\n[RESULTADO] No se pudieron leer los extras de: {', '.join(fallaron)}.")
        return 1
    print("\nVerificación de extras OK en todas las sedes consultadas.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
