"""Agregaciones gerenciales (F4) calculadas en el servidor a partir de reservas de Cloudbeds.

Reglas verificadas contra la API real (oct-2026, 292 reservas):
- detailedRates / detailedRoomRates son tarifas por noche CON impuestos incluidos.
- balanceDetailed.subTotal es el importe de habitación SIN impuestos; incluye ajustes manuales
  de precio que no se reflejan en las tarifas por fecha.
- Canceladas y no-show tienen total=0 aunque conserven sus tarifas: no generan ingreso.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from .formatters import ESTADOS, _int, _num, reservation_summary

SIN_INGRESO = {"canceled", "no_show"}
LLEGO = {"checked_in", "checked_out"}
PENDIENTE_LLEGADA = {"confirmed", "not_confirmed"}


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _nights(start: Any, end: Any) -> int:
    d1, d2 = _date(start), _date(end)
    return max((d2 - d1).days, 0) if d1 and d2 else 0


def _sorted(counter: Counter | dict) -> dict[str, Any]:
    items = counter.items()
    key = (lambda kv: -kv[1]) if isinstance(counter, Counter) else (lambda kv: -kv[1].get("noches", 0))
    return dict(sorted(items, key=key))


def _active_rooms(r: dict[str, Any]) -> list[dict[str, Any]]:
    return [x for x in (r.get("rooms") or []) if x.get("roomStatus") not in ("cancelled", "canceled")]


def _short(r: dict[str, Any]) -> dict[str, Any]:
    s = reservation_summary(r)
    return {k: s[k] for k in ("id", "huesped", "estado", "tipo_habitacion", "fuente") if k in s}


# ---------- resumen_dia ----------

def day_summary(
    dashboard: dict[str, Any],
    arrivals: list[dict[str, Any]],
    departures: list[dict[str, Any]],
    fecha: str,
    limit: int = 20,
) -> dict[str, Any]:
    arr_ok = [r for r in arrivals if r.get("status") not in SIN_INGRESO]
    dep_ok = [r for r in departures if r.get("status") not in SIN_INGRESO]
    return {
        "fecha": fecha,
        "ocupacion": {
            "habitaciones_ocupadas": _int(dashboard.get("roomsOccupied")),
            "porcentaje_ocupacion": _num(dashboard.get("percentageOccupied")),
            "in_house": _int(dashboard.get("inHouse")),
        },
        "llegadas": {
            "total": len(arr_ok),
            "ya_ingresaron": sum(1 for r in arr_ok if r.get("status") in LLEGO),
            "pendientes": sum(1 for r in arr_ok if r.get("status") in PENDIENTE_LLEGADA),
            "pendientes_segun_dashboard": _int(dashboard.get("arrivals")),
            "no_show": sum(1 for r in arrivals if r.get("status") == "no_show"),
            "canceladas": sum(1 for r in arrivals if r.get("status") == "canceled"),
            "lista": [_short(r) for r in arr_ok[:limit]],
        },
        "salidas": {
            "total": len(dep_ok),
            "ya_salieron": sum(1 for r in dep_ok if r.get("status") == "checked_out"),
            "pendientes": sum(1 for r in dep_ok if r.get("status") == "checked_in"),
            "pendientes_segun_dashboard": _int(dashboard.get("departures")),
            "lista": [_short(r) for r in dep_ok[:limit]],
        },
        "lista_recortada": len(arr_ok) > limit or len(dep_ok) > limit,
    }


# ---------- resumen_periodo ----------

def period_summary(reservations: list[dict[str, Any]]) -> dict[str, Any]:
    """Reservas de getReservations (con includeAllRooms) ya filtradas por el criterio del periodo."""
    total = len(reservations)
    por_estado = Counter(ESTADOS.get(r.get("status") or "", r.get("status")) for r in reservations)
    validas = [r for r in reservations if r.get("status") not in SIN_INGRESO]

    por_fuente: Counter = Counter()
    por_tipo: Counter = Counter()
    noches = 0
    habitaciones = 0
    for r in validas:
        por_fuente[r.get("sourceName") or "sin fuente"] += 1
        rooms = _active_rooms(r)
        if rooms:
            for x in rooms:
                por_tipo[x.get("roomTypeName") or "sin tipo"] += 1
                noches += _nights(x.get("roomCheckIn") or r.get("startDate"), x.get("roomCheckOut") or r.get("endDate"))
                habitaciones += 1
        else:
            noches += _nights(r.get("startDate"), r.get("endDate"))
            habitaciones += 1

    canceladas = sum(1 for r in reservations if r.get("status") == "canceled")
    return {
        "reservas_total": total,
        "reservas_validas": len(validas),
        "por_estado": _sorted(por_estado),
        "por_fuente": _sorted(por_fuente),
        "por_tipo_habitacion": _sorted(por_tipo),
        "habitaciones_reservadas": habitaciones,
        "noches_reservadas": noches,
        "estancia_media_noches": round(noches / habitaciones, 2) if habitaciones else None,
        "cancelaciones": {
            "cantidad": canceladas,
            "porcentaje": round(100 * canceladas / total, 1) if total else None,
        },
        "no_show": sum(1 for r in reservations if r.get("status") == "no_show"),
    }


# ---------- ingresos_periodo ----------

def revenue(
    reservations: list[dict[str, Any]], desde: date, hasta: date, unidades: int | None
) -> dict[str, Any]:
    """Ingresos de habitación por fecha de estadía (noches de desde a hasta, ambas incluidas)."""
    dias = (hasta - desde).days + 1
    bruto = neto = 0.0
    noches = 0
    reservas = 0
    por_fuente: dict[str, dict[str, float]] = defaultdict(lambda: {"noches": 0, "ingreso_bruto": 0.0, "ingreso_neto": 0.0})
    por_tipo: dict[str, dict[str, float]] = defaultdict(lambda: {"noches": 0, "ingreso_bruto": 0.0})
    excluidas = Counter()

    for r in reservations:
        status = r.get("status")
        if r.get("isDeleted"):
            continue
        if status in SIN_INGRESO:
            # solo cuenta si tenía noches en el periodo
            if any(desde <= (_date(d) or date.min) <= hasta for d in (r.get("detailedRates") or {})):
                excluidas[status] += 1
            continue

        # (fecha, tarifa, tipo) por cada noche de cada habitación activa
        nights: list[tuple[date, float, str]] = []
        rooms = _active_rooms(r)
        if rooms:
            for x in rooms:
                for d, rate in (x.get("detailedRoomRates") or {}).items():
                    dd = _date(d)
                    if dd:
                        nights.append((dd, float(_num(rate) or 0), x.get("roomTypeName") or "sin tipo"))
        else:
            for d, rate in (r.get("detailedRates") or {}).items():
                dd = _date(d)
                if dd:
                    nights.append((dd, float(_num(rate) or 0), "sin tipo"))

        total_rates = sum(n[1] for n in nights)
        in_period = [n for n in nights if desde <= n[0] <= hasta]
        if not in_period:
            continue
        sub_total = _num((r.get("balanceDetailed") or {}).get("subTotal"))
        # neto: subTotal (sin impuestos, con ajustes manuales) prorrateado según el peso de las noches del periodo
        factor = (sub_total / total_rates) if (sub_total is not None and total_rates > 0) else 0.0

        reservas += 1
        fuente = r.get("sourceName") or (r.get("source") or {}).get("name") or "sin fuente"
        for _, rate, tipo in in_period:
            bruto += rate
            neto += rate * factor
            noches += 1
            por_fuente[fuente]["noches"] += 1
            por_fuente[fuente]["ingreso_bruto"] += rate
            por_fuente[fuente]["ingreso_neto"] += rate * factor
            por_tipo[tipo]["noches"] += 1
            por_tipo[tipo]["ingreso_bruto"] += rate

    def _round(d: dict[str, dict[str, float]]) -> dict[str, Any]:
        return _sorted({k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in d.items()})

    capacidad = unidades * dias if unidades else None
    return {
        "periodo": {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "dias": dias},
        "reservas_con_noches_en_periodo": reservas,
        "noches_vendidas": noches,
        "ingreso_habitacion_bruto": round(bruto, 2),
        "ingreso_habitacion_neto": round(neto, 2),
        "adr_bruto": round(bruto / noches, 2) if noches else None,
        "adr_neto": round(neto / noches, 2) if noches else None,
        "habitaciones_hotel": unidades,
        "ocupacion_pct": round(100 * noches / capacidad, 1) if capacidad else None,
        "revpar_neto": round(neto / capacidad, 2) if capacidad else None,
        "por_fuente": _round(por_fuente),
        "por_tipo_habitacion": _round(por_tipo),
        "excluidas_sin_ingreso": {"canceladas": excluidas["canceled"], "no_show": excluidas["no_show"]},
    }


def stay_query_window(desde: date, hasta: date, max_stay_days: int = 35) -> tuple[date, date]:
    """Ventana de check-out para traer las estadías que tocan el periodo.

    getReservationsWithRateDetails no filtra por check-in: se piden reservas con check-out
    entre desde+1 y hasta+1+max_stay_days, y luego se filtran las noches localmente.
    35 días: la estadía más larga del último año fue de 31 noches (verificado, 4.132 reservas).
    """
    return desde + timedelta(days=1), hasta + timedelta(days=1 + max_stay_days)
