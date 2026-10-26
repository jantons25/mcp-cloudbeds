"""Recorte de respuestas de Cloudbeds: solo los campos útiles, con PII enmascarada.

Nunca se devuelven tarjetas (cardsOnFile), direcciones ni fechas de nacimiento.
"""

from __future__ import annotations

import json
from typing import Any

from . import pii

ESTADOS = {
    "not_confirmed": "pendiente de confirmar",
    "confirmed": "confirmada",
    "canceled": "cancelada",
    "checked_in": "con check-in (en casa)",
    "checked_out": "con check-out",
    "no_show": "no show",
}


def to_json(obj: Any) -> str:
    """JSON compacto y legible en español (sin escapar tildes)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _drop_empty(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _estado(code: str | None) -> str | None:
    return ESTADOS.get(code or "", code)


def _unique(values: list[Any]) -> list[Any]:
    seen: list[Any] = []
    for v in values:
        if v and v not in seen:
            seen.append(v)
    return seen


def dashboard(data: dict[str, Any], fecha: str) -> dict[str, Any]:
    """Solo campos documentados de getDashboard.

    Verificado contra getReservations: arrivals/departures son las llegadas y
    salidas del día que AÚN NO hicieron check-in/check-out. La API real los
    envía como texto y percentageOccupied con decimales, por eso se normalizan.
    """
    return {
        "fecha": fecha,
        "habitaciones_ocupadas": _int(data.get("roomsOccupied")),
        "porcentaje_ocupacion": _num(data.get("percentageOccupied")),
        "llegadas_pendientes": _int(data.get("arrivals")),
        "salidas_pendientes": _int(data.get("departures")),
        "in_house": _int(data.get("inHouse")),
    }


def reservation_summary(r: dict[str, Any]) -> dict[str, Any]:
    """Elemento de getReservations (consultado con includeAllRooms=true)."""
    rooms = r.get("rooms") or []
    return _drop_empty(
        {
            "id": r.get("reservationID"),
            "huesped": r.get("guestName"),
            "checkin": r.get("startDate"),
            "checkout": r.get("endDate"),
            "estado": _estado(r.get("status")),
            "tipo_habitacion": _unique([x.get("roomTypeName") for x in rooms]),
            "habitacion": _unique([x.get("roomName") for x in rooms]),
            "fuente": r.get("sourceName"),
            "adultos": _int(r.get("adults")),
            "ninos": _int(r.get("children")),
            "saldo": _num(r.get("balance")),
        }
    )


FRONTDESK = {
    "check-in": "llegada",
    "check-out": "salida",
    "stayover": "continúa (stayover)",
    "turnover": "salida y llegada (turnover)",
    "unused": "libre",
}

CONDICION = {"clean": "limpia", "dirty": "sucia"}


def _currency_code(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else {}
    return value.get("currencyCode") if isinstance(value, dict) else None


def _per_night(total: Any, noches: int) -> float | None:
    t = _num(total)
    return round(t / noches, 2) if t is not None and noches > 0 else None


def available_room_types(body: dict[str, Any], noches: int) -> dict[str, Any]:
    """getAvailableRoomTypes. Verificado: roomRate es el total de la estadía, no por noche."""
    props = body.get("data") or []
    prop = props[0] if props else {}
    tipos = [
        _drop_empty(
            {
                "tipo": r.get("roomTypeName"),
                "disponibles": _int(r.get("roomsAvailable")),
                "tarifa_estadia": _num(r.get("roomRate")),
                "tarifa_promedio_noche": _per_night(r.get("roomRate"), noches),
                "plan_tarifa": r.get("ratePlanNamePublic"),
                "max_huespedes": _int(r.get("maxGuests")),
            }
        )
        for r in (prop.get("propertyRooms") or [])
    ]
    return {"moneda": _currency_code(prop.get("propertyCurrency")), "tipos": tipos}


def room_type(r: dict[str, Any]) -> dict[str, Any]:
    features = r.get("roomTypeFeatures")
    return _drop_empty(
        {
            "id": r.get("roomTypeID"),
            "tipo": r.get("roomTypeName"),
            "codigo": r.get("roomTypeNameShort"),
            "unidades": _int(r.get("roomTypeUnits")),
            "max_huespedes": _int(r.get("maxGuests")),
            "adultos_incluidos": _int(r.get("adultsIncluded")),
            "ninos_incluidos": _int(r.get("childrenIncluded")),
            "privada": r.get("isPrivate"),
            "caracteristicas": [f for f in features if isinstance(f, str)] if isinstance(features, list) else None,
        }
    )


def room(r: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "id": r.get("roomID"),
            "habitacion": r.get("roomName"),
            "tipo": r.get("roomTypeName"),
            "tipo_id": r.get("roomTypeID"),
            "max_huespedes": _int(r.get("maxGuests")),
            "bloqueada": r.get("roomBlocked"),
            "virtual": True if r.get("isVirtual") else None,
        }
    )


def assignment(a: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "reserva": a.get("reservationID"),
            "huesped": a.get("guestName"),
            "habitaciones": [
                _drop_empty({"habitacion": x.get("roomName"), "tipo": x.get("roomTypeName")})
                for x in (a.get("assigned") or [])
            ],
            "sin_asignar": _int(a.get("unassigned")) or None,
        }
    )


def housekeeping(h: dict[str, Any], show_pii: bool) -> dict[str, Any]:
    return _drop_empty(
        {
            "habitacion": h.get("roomName"),
            "tipo": h.get("roomTypeName"),
            "condicion": CONDICION.get(h.get("roomCondition") or "", h.get("roomCondition")),
            "ocupada": h.get("roomOccupied"),
            "bloqueada": True if h.get("roomBlocked") else None,
            "estado_recepcion": FRONTDESK.get(h.get("frontdeskStatus") or "", h.get("frontdeskStatus")),
            "housekeeper": h.get("housekeeper"),
            "no_molestar": True if h.get("doNotDisturb") else None,
            "rechazo_servicio": True if h.get("refusedService") else None,
            "vacant_pickup": True if h.get("vacantPickup") else None,
            "comentarios": pii.scrub_text(h.get("roomComments"), show_pii),
            "ultimo_cambio": h.get("date"),
        }
    )


def flatten(data: Any) -> list[dict[str, Any]]:
    """Aplana listas anidadas. getSources real devuelve data=[[...]] (una lista por propiedad)."""
    out: list[dict[str, Any]] = []
    for item in data or []:
        if isinstance(item, list):
            out.extend(flatten(item))
        elif isinstance(item, dict):
            out.append(item)
    return out


def source(s: dict[str, Any]) -> dict[str, Any]:
    collect = s.get("paymentCollect")
    return _drop_empty(
        {
            "id": s.get("sourceID"),
            "fuente": s.get("sourceName"),
            "tercero": s.get("isThirdParty"),
            "activa": s.get("status"),
            "comision_pct": _num(s.get("commission")),
            "cobra": {"hotel": "hotel", "channel": "canal"}.get(collect or "", collect),
        }
    )


def rate_plan(r: dict[str, Any], noches: int) -> dict[str, Any]:
    """getRatePlans. Verificado: roomRate/totalRate son el total de la estadía."""
    total = r.get("totalRate") if r.get("totalRate") is not None else r.get("roomRate")
    return _drop_empty(
        {
            "id_tarifa": r.get("rateID"),
            "tipo": r.get("roomTypeName"),
            "plan": r.get("ratePlanNamePublic") or "Tarifa base",
            "plan_interno": r.get("ratePlanNamePrivate"),
            "codigo_promo": r.get("promoCode"),
            "tarifa_estadia": _num(total),
            "tarifa_promedio_noche": _per_night(total, noches),
            "disponibles": _int(r.get("roomsAvailable")),
            "derivada": True if r.get("isDerived") else None,
        }
    )


def _room(x: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "tipo": x.get("roomTypeName"),
            "habitacion": x.get("roomName") or "sin asignar",
            "checkin": x.get("startDate"),
            "checkout": x.get("endDate"),
            "adultos": _int(x.get("adults")),
            "ninos": _int(x.get("children")),
            "total_habitacion": _num(x.get("roomTotal")),
        }
    )


def _guest(g: dict[str, Any], show_pii: bool) -> dict[str, Any]:
    doc_number = g.get("guestDocumentNumber")
    documento = None
    if doc_number:
        documento = " ".join(filter(None, [g.get("guestDocumentType"), pii.document(doc_number, show_pii)]))
    return _drop_empty(
        {
            "nombre": " ".join(filter(None, [g.get("guestFirstName"), g.get("guestLastName")])),
            "principal": bool(g.get("isMainGuest")) or None,
            "email": pii.email(g.get("guestEmail"), show_pii),
            "telefono": pii.phone(g.get("guestCellPhone") or g.get("guestPhone"), show_pii),
            "documento": documento,
            "nacionalidad": g.get("guestNationality") or g.get("guestCountry"),
            "datos_anonimizados": bool(g.get("isAnonymized")) or None,
        }
    )


def reservation_detail(d: dict[str, Any], show_pii: bool) -> dict[str, Any]:
    """Respuesta de getReservation."""
    guests = d.get("guestList") or {}
    guest_items = guests.values() if isinstance(guests, dict) else guests
    rooms = [_room(x) for x in (d.get("assigned") or [])] + [
        _room(x) for x in (d.get("unassigned") or [])
    ]
    return _drop_empty(
        {
            "id": d.get("reservationID"),
            "estado": _estado(d.get("status")),
            "huesped_principal": d.get("guestName"),
            "email_principal": pii.email(d.get("guestEmail"), show_pii),
            "checkin": d.get("startDate"),
            "checkout": d.get("endDate"),
            "hora_llegada_estimada": d.get("estimatedArrivalTime"),
            "fuente": d.get("source"),
            "id_canal": d.get("thirdPartyIdentifier"),
            "total": _num(d.get("total")),
            "saldo": _num(d.get("balance")),
            "plan_comidas": d.get("mealPlans"),
            "fecha_creacion": d.get("dateCreated"),
            "fecha_cancelacion": d.get("dateCancelled"),
            "habitaciones": rooms,
            "huespedes": [_guest(g, show_pii) for g in guest_items if isinstance(g, dict)],
        }
    )
