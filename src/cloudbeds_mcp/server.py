"""Servidor MCP (stdio) de solo lectura para Cloudbeds.

Ejecutar: python -m cloudbeds_mcp.server
IMPORTANTE: nada se escribe a stdout (lo usa JSON-RPC); los logs van a stderr.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter, ValidationError

from . import aggregations as agg
from . import formatters as fmt
from .client import CloudbedsClient
from .config import Settings, configure_logging, load_settings
from .errors import CloudbedsError, ConfigError

logger = logging.getLogger("cloudbeds_mcp.server")

READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)

_client: CloudbedsClient | None = None


def set_client(client: CloudbedsClient | None) -> None:
    """Inyecta un cliente (usado por los tests)."""
    global _client
    _client = client


def _get_client() -> CloudbedsClient:
    global _client
    if _client is None:
        _client = CloudbedsClient(load_settings())
    return _client


def _settings() -> Settings:
    return _get_client().settings


def _today() -> date:
    return datetime.now(_settings().tz).date()


def _error(exc: Exception) -> str:
    if isinstance(exc, ConfigError):
        return f"No se pudo consultar Cloudbeds: falta configuración. {exc}"
    return f"No se pudo consultar Cloudbeds: {exc}"


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE = TypeAdapter(date)


def _parse_fecha(value: str | None, nombre: str) -> date | None:
    """Valida YYYY-MM-DD con pydantic y devuelve un mensaje en español si falla."""
    if value is None or not value.strip():
        return None
    v = value.strip()
    if not _DATE_RE.match(v):
        raise ValueError(f"La fecha de {nombre} '{v}' no tiene el formato YYYY-MM-DD (ejemplo: 2026-10-26).")
    try:
        return _DATE.validate_python(v)
    except ValidationError:
        raise ValueError(f"La fecha de {nombre} '{v}' no existe en el calendario.") from None


# Límite de rango para cualquier consulta con fechas (F5): evita consultas enormes a Cloudbeds.
MAX_RANGE_DAYS = 366


def _check_length(desde: date, hasta: date, nombre: str) -> None:
    if (hasta - desde).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(
            f"El rango de {nombre} no puede superar {MAX_RANGE_DAYS} días; divídelo en consultas más cortas."
        )


def _check_range(desde: date | None, hasta: date | None, nombre: str) -> None:
    if desde and hasta and desde > hasta:
        raise ValueError(f"El rango de {nombre} es inválido: la fecha inicial es posterior a la final.")
    if desde and hasta:
        _check_length(desde, hasta, nombre)


@asynccontextmanager
async def _lifespan(_: FastMCP) -> AsyncIterator[None]:
    try:
        yield
    finally:
        if _client is not None:
            await _client.aclose()


mcp = FastMCP(
    "cloudbeds",
    instructions=(
        "Consulta en modo SOLO LECTURA los datos de Cloudbeds del hotel (ocupación, llegadas, "
        "salidas, reservas, disponibilidad, tarifas, habitaciones, housekeeping y canales). "
        "Los montos están en la moneda del hotel. Las fechas son YYYY-MM-DD en hora de Lima (America/Lima). "
        "Responde en español. Los datos personales de huéspedes pueden venir enmascarados."
    ),
    lifespan=_lifespan,
)

def _fecha_param(desc: str) -> object:
    return Field(description=f"{desc} Formato YYYY-MM-DD (hora de Lima), ej. 2026-10-26.")


@mcp.tool(
    title="Estado del hotel",
    description=(
        "Foto del día en el hotel según el dashboard de Cloudbeds: habitaciones ocupadas, % de "
        "ocupación, in-house, y llegadas/salidas PENDIENTES (las del día que aún no hicieron "
        "check-in/check-out). Para el TOTAL de llegadas o salidas del día (incluidas las ya "
        "realizadas) usa además buscar_reservas con checkin_desde=checkin_hasta=fecha (o "
        "checkout_desde=checkout_hasta=fecha) y explica ambas cifras."
    ),
    annotations=READ_ONLY,
    structured_output=False,
)
async def estado_hotel(
    fecha: Annotated[str | None, _fecha_param("Fecha a consultar; si se omite, hoy.")] = None,
) -> str:
    try:
        dia_param = _parse_fecha(fecha, "consulta")
    except ValueError as exc:
        return str(exc)
    try:
        client = _get_client()
        dia = dia_param or _today()
        body = await client.get(
            "getDashboard", {"propertyID": client.settings.property_id, "date": dia.isoformat()}
        )
        return fmt.to_json(fmt.dashboard(body.get("data") or {}, dia.isoformat()))
    except (CloudbedsError, ConfigError) as exc:
        return _error(exc)


EstadoReserva = Literal["not_confirmed", "confirmed", "canceled", "checked_in", "checked_out", "no_show"]


@mcp.tool(
    title="Buscar reservas",
    description=(
        "Busca reservas y devuelve una lista compacta (id, huésped, check-in, check-out, estado, "
        "tipo de habitación, fuente/canal, saldo). Filtros opcionales: estado, rango de fecha de "
        "check-in, rango de fecha de check-out y apellido del huésped principal. Estados: "
        "not_confirmed=pendiente, confirmed=confirmada, canceled=cancelada, checked_in=en casa, "
        "checked_out=salió, no_show=no se presentó. Para las llegadas de un día usa "
        "checkin_desde=checkin_hasta=ese día; para salidas, checkout_desde=checkout_hasta."
    ),
    annotations=READ_ONLY,
    structured_output=False,
)
async def buscar_reservas(
    estado: Annotated[EstadoReserva | None, Field(description="Estado actual de la reserva.")] = None,
    checkin_desde: Annotated[str | None, _fecha_param("Check-in desde.")] = None,
    checkin_hasta: Annotated[str | None, _fecha_param("Check-in hasta.")] = None,
    checkout_desde: Annotated[str | None, _fecha_param("Check-out desde.")] = None,
    checkout_hasta: Annotated[str | None, _fecha_param("Check-out hasta.")] = None,
    apellido: Annotated[
        str | None, Field(description="Apellido del huésped principal.", min_length=1, max_length=100)
    ] = None,
    max_resultados: Annotated[
        int, Field(description="Máximo de reservas a devolver (1-500). Por defecto 50.", ge=1, le=500)
    ] = 50,
) -> str:
    try:
        ci_desde = _parse_fecha(checkin_desde, "check-in desde")
        ci_hasta = _parse_fecha(checkin_hasta, "check-in hasta")
        co_desde = _parse_fecha(checkout_desde, "check-out desde")
        co_hasta = _parse_fecha(checkout_hasta, "check-out hasta")
        _check_range(ci_desde, ci_hasta, "check-in")
        _check_range(co_desde, co_hasta, "check-out")
    except ValueError as exc:
        return str(exc)
    try:
        client = _get_client()
        params = {
            "propertyID": client.settings.property_id,
            "status": estado,
            "checkInFrom": ci_desde.isoformat() if ci_desde else None,
            "checkInTo": ci_hasta.isoformat() if ci_hasta else None,
            "checkOutFrom": co_desde.isoformat() if co_desde else None,
            "checkOutTo": co_hasta.isoformat() if co_hasta else None,
            "lastName": apellido.strip() if apellido else None,
            "includeAllRooms": True,  # necesario para obtener el tipo de habitación
        }
        limit = min(max_resultados, client.settings.max_results)
        result = await client.get_all("getReservations", params, max_results=limit)
        reservas = [fmt.reservation_summary(r) for r in result["data"]]
        out = {"cantidad": len(reservas), "total_en_cloudbeds": result["total"], "truncado": result["truncado"], "reservas": reservas}
        if result["truncado"]:
            out["nota"] = "Hay más reservas que las mostradas; aumenta max_resultados o acota los filtros."
        return fmt.to_json(out)
    except (CloudbedsError, ConfigError) as exc:
        return _error(exc)


@mcp.tool(
    title="Detalle de reserva",
    description=(
        "Detalle de una reserva por su ID: estado, huéspedes, fechas, habitaciones, fuente, total "
        "y saldo. Los datos personales (email, teléfono, documento) se muestran enmascarados "
        "salvo que la configuración lo permita."
    ),
    annotations=READ_ONLY,
    structured_output=False,
)
async def detalle_reserva(
    reservation_id: Annotated[
        str, Field(description="ID de la reserva en Cloudbeds.", min_length=1, max_length=64)
    ],
) -> str:
    try:
        client = _get_client()
        body = await client.get(
            "getReservation",
            {"propertyID": client.settings.property_id, "reservationID": reservation_id.strip()},
        )
        return fmt.to_json(fmt.reservation_detail(body.get("data") or {}, client.settings.show_pii))
    except (CloudbedsError, ConfigError) as exc:
        return _error(exc)


def _stay(entrada: str | None, salida: str | None) -> tuple[date, date, int]:
    """Fechas de estadía: entrada por defecto hoy; salida por defecto entrada + 1 noche."""
    d_in = _parse_fecha(entrada, "entrada") or _today()
    d_out = _parse_fecha(salida, "salida") or d_in + timedelta(days=1)
    if d_out <= d_in:
        raise ValueError("La fecha de salida debe ser posterior a la de entrada.")
    _check_length(d_in, d_out - timedelta(days=1), "la estadía")
    return d_in, d_out, (d_out - d_in).days


@mcp.tool(
    title="Disponibilidad",
    description=(
        "Tipos de habitación disponibles para vender en un rango de fechas, con cuántas quedan y "
        "la tarifa (total de la estadía y promedio por noche). Por defecto: entrada hoy, salida "
        "mañana, 1 habitación, 1 adulto, 0 niños. Úsala para '¿hay disponibilidad para...?' o "
        "'¿cuánto cuesta una matrimonial el fin de semana?'."
    ),
    annotations=READ_ONLY,
    structured_output=False,
)
async def disponibilidad(
    fecha_entrada: Annotated[str | None, _fecha_param("Check-in; si se omite, hoy.")] = None,
    fecha_salida: Annotated[str | None, _fecha_param("Check-out; si se omite, el día siguiente a la entrada.")] = None,
    habitaciones: Annotated[int, Field(description="Número de habitaciones (1-20).", ge=1, le=20)] = 1,
    adultos: Annotated[int, Field(description="Adultos por habitación (1-20).", ge=1, le=20)] = 1,
    ninos: Annotated[int, Field(description="Niños por habitación (0-20).", ge=0, le=20)] = 0,
) -> str:
    try:
        d_in, d_out, noches = _stay(fecha_entrada, fecha_salida)
    except ValueError as exc:
        return str(exc)
    try:
        client = _get_client()
        body = await client.get(
            "getAvailableRoomTypes",
            {
                "propertyIDs": client.settings.property_id,
                "startDate": d_in.isoformat(),
                "endDate": d_out.isoformat(),
                "rooms": habitaciones,
                "adults": adultos,
                "children": ninos,
            },
        )
        out = {
            "entrada": d_in.isoformat(),
            "salida": d_out.isoformat(),
            "noches": noches,
            "habitaciones": habitaciones,
            "adultos": adultos,
            "ninos": ninos,
            **fmt.available_room_types(body, noches),
        }
        if not out["tipos"]:
            out["nota"] = "No hay tipos de habitación disponibles para esos parámetros."
        return fmt.to_json(out)
    except (CloudbedsError, ConfigError) as exc:
        return _error(exc)


@mcp.tool(
    title="Tipos de habitación",
    description=(
        "Catálogo de tipos de habitación del hotel: nombre, código, cuántas unidades hay, máximo "
        "de huéspedes y características. No indica disponibilidad (para eso usa disponibilidad)."
    ),
    annotations=READ_ONLY,
    structured_output=False,
)
async def tipos_habitacion() -> str:
    try:
        client = _get_client()
        result = await client.get_all("getRoomTypes", {"propertyIDs": client.settings.property_id})
        tipos = [fmt.room_type(r) for r in result["data"]]
        return fmt.to_json(
            {"cantidad_tipos": len(tipos), "total_unidades": sum(t.get("unidades", 0) for t in tipos), "tipos": tipos}
        )
    except (CloudbedsError, ConfigError) as exc:
        return _error(exc)


async def _all_rooms(client: CloudbedsClient, params: dict[str, object]) -> list[dict]:
    """getRooms agrupa por propiedad (data[].rooms[]), así que se pagina contando habitaciones."""
    rooms: list[dict] = []
    page = 1
    while True:
        body = await client.get("getRooms", {**params, "pageNumber": page, "pageSize": 100})
        batch = [r for prop in (body.get("data") or []) for r in (prop.get("rooms") or [])]
        rooms.extend(batch)
        total = body.get("total")
        if not batch or len(batch) < 100 or (isinstance(total, int) and len(rooms) >= total):
            return rooms
        page += 1


@mcp.tool(
    title="Habitaciones",
    description=(
        "Lista de habitaciones físicas (número/nombre, tipo, capacidad, si está bloqueada). "
        "Opcional: filtrar por ID de tipo de habitación (ver tipos_habitacion). Si se indican "
        "fecha_desde y fecha_hasta (noches de fecha_desde a fecha_hasta, hasta exclusiva), "
        "devuelve solo las habitaciones que NO tienen una reserva asignada en esas noches. Ojo: "
        "'sin asignar' NO significa disponible para vender (puede haber reservas sin habitación "
        "asignada todavía y las bloqueadas también aparecen); para vender usa disponibilidad."
    ),
    annotations=READ_ONLY,
    structured_output=False,
)
async def habitaciones(
    tipo_habitacion_id: Annotated[
        str | None, Field(description="ID del tipo de habitación (de tipos_habitacion).", max_length=64)
    ] = None,
    fecha_desde: Annotated[str | None, _fecha_param("Inicio del periodo (requiere fecha_hasta).")] = None,
    fecha_hasta: Annotated[str | None, _fecha_param("Fin del periodo (requiere fecha_desde).")] = None,
) -> str:
    try:
        desde = _parse_fecha(fecha_desde, "desde")
        hasta = _parse_fecha(fecha_hasta, "hasta")
        if bool(desde) != bool(hasta):
            raise ValueError("Para filtrar por periodo indica fecha_desde y fecha_hasta juntas.")
        if desde and hasta and hasta <= desde:  # Cloudbeds rechaza desde == hasta (verificado)
            raise ValueError("fecha_hasta debe ser posterior a fecha_desde (se cuentan noches).")
        if desde and hasta:
            _check_length(desde, hasta - timedelta(days=1), "fechas")
    except ValueError as exc:
        return str(exc)
    try:
        client = _get_client()
        rooms = await _all_rooms(
            client,
            {
                "propertyIDs": client.settings.property_id,
                "roomTypeID": tipo_habitacion_id.strip() if tipo_habitacion_id else None,
                "startDate": desde.isoformat() if desde else None,
                "endDate": hasta.isoformat() if hasta else None,
            },
        )
        out: dict[str, object] = {"cantidad": len(rooms), "habitaciones": [fmt.room(r) for r in rooms]}
        if desde:
            out["filtro"] = (
                f"sin reserva asignada en las noches del {desde.isoformat()} al {hasta.isoformat()} (exclusivo); "  # type: ignore[union-attr]
                "no equivale a disponibles para vender"
            )
            out["bloqueadas_incluidas"] = sum(1 for r in rooms if r.get("roomBlocked"))
        return fmt.to_json(out)
    except (CloudbedsError, ConfigError) as exc:
        return _error(exc)


@mcp.tool(
    title="Asignaciones del día",
    description=(
        "Qué reserva y huésped ocupa cada habitación en una fecha (por defecto hoy), incluidas "
        "las reservas con habitaciones aún sin asignar. Úsala para '¿quién está en la 201?' o "
        "'¿qué reservas faltan asignar hoy?'."
    ),
    annotations=READ_ONLY,
    structured_output=False,
)
async def asignaciones_del_dia(
    fecha: Annotated[str | None, _fecha_param("Fecha a consultar; si se omite, hoy.")] = None,
) -> str:
    try:
        dia_param = _parse_fecha(fecha, "consulta")
    except ValueError as exc:
        return str(exc)
    try:
        client = _get_client()
        dia = dia_param or _today()
        body = await client.get(
            "getReservationAssignments", {"propertyID": client.settings.property_id, "date": dia.isoformat()}
        )
        items = [fmt.assignment(a) for a in (body.get("data") or [])]
        return fmt.to_json(
            {
                "fecha": dia.isoformat(),
                "reservas": len(items),
                "habitaciones_asignadas": sum(len(a.get("habitaciones", [])) for a in items),
                "reservas_con_habitaciones_sin_asignar": sum(1 for a in items if a.get("sin_asignar")),
                "asignaciones": items,
            }
        )
    except (CloudbedsError, ConfigError) as exc:
        return _error(exc)


@mcp.tool(
    title="Estado de housekeeping",
    description=(
        "Estado actual de limpieza de las habitaciones: limpia/sucia, ocupada, bloqueada, estado "
        "de recepción (llegada, salida, stayover, turnover, libre), housekeeper asignado y notas. "
        "Incluye un resumen con conteos. Filtros opcionales: condicion (clean=limpia, "
        "dirty=sucia) y ocupada (true/false)."
    ),
    annotations=READ_ONLY,
    structured_output=False,
)
async def estado_housekeeping(
    condicion: Annotated[
        Literal["clean", "dirty"] | None, Field(description="clean=limpia, dirty=sucia.")
    ] = None,
    ocupada: Annotated[bool | None, Field(description="true=solo ocupadas, false=solo libres.")] = None,
) -> str:
    try:
        client = _get_client()
        # Se piden todas las habitaciones y se filtra aquí: Cloudbeds ignoraba roomOccupied=false
        # (devolvía las ocupadas). Además el campo 'total' no es fiable; se cuentan los elementos.
        result = await client.get_all("getHousekeepingStatus", {"propertyID": client.settings.property_id})
        raw = [
            h
            for h in result["data"]
            if (condicion is None or h.get("roomCondition") == condicion)
            and (ocupada is None or bool(h.get("roomOccupied")) == ocupada)
        ]
        rooms = [fmt.housekeeping(h, client.settings.show_pii) for h in raw]
        resumen = {
            "habitaciones": len(rooms),
            "limpias": sum(1 for r in rooms if r.get("condicion") == "limpia"),
            "sucias": sum(1 for r in rooms if r.get("condicion") == "sucia"),
            "ocupadas": sum(1 for r in rooms if r.get("ocupada")),
            "bloqueadas": sum(1 for r in rooms if r.get("bloqueada")),
            "por_estado_recepcion": dict(Counter(r.get("estado_recepcion") for r in rooms if r.get("estado_recepcion"))),
        }
        return fmt.to_json({"resumen": resumen, "truncado": result["truncado"], "habitaciones": rooms})
    except (CloudbedsError, ConfigError) as exc:
        return _error(exc)


@mcp.tool(
    title="Fuentes de reserva",
    description=(
        "Canales/fuentes de reserva configurados (web, Booking.com, Expedia, walk-in, etc.) con "
        "su ID, si son de terceros, comisión (%) y quién cobra. El ID sirve para entender el "
        "campo 'fuente' de las reservas. Por defecto solo las activas."
    ),
    annotations=READ_ONLY,
    structured_output=False,
)
async def fuentes_reserva(
    solo_activas: Annotated[bool, Field(description="true=solo fuentes activas (por defecto).")] = True,
) -> str:
    try:
        client = _get_client()
        body = await client.get("getSources", {"propertyIDs": client.settings.property_id})
        fuentes = [fmt.source(s) for s in fmt.flatten(body.get("data"))]
        if solo_activas:
            fuentes = [f for f in fuentes if f.get("activa")]
        return fmt.to_json({"cantidad": len(fuentes), "fuentes": fuentes})
    except (CloudbedsError, ConfigError) as exc:
        return _error(exc)


@mcp.tool(
    title="Planes de tarifa",
    description=(
        "Planes de tarifa vigentes para un rango de fechas: tarifa base y planes/promociones por "
        "tipo de habitación, con total de la estadía, promedio por noche y disponibilidad. Por "
        "defecto: entrada hoy, salida mañana."
    ),
    annotations=READ_ONLY,
    structured_output=False,
)
async def planes_tarifa(
    fecha_entrada: Annotated[str | None, _fecha_param("Check-in; si se omite, hoy.")] = None,
    fecha_salida: Annotated[str | None, _fecha_param("Check-out; si se omite, el día siguiente a la entrada.")] = None,
    adultos: Annotated[int | None, Field(description="Adultos (opcional, 1-20).", ge=1, le=20)] = None,
    ninos: Annotated[int | None, Field(description="Niños (opcional, 0-20).", ge=0, le=20)] = None,
) -> str:
    try:
        d_in, d_out, noches = _stay(fecha_entrada, fecha_salida)
    except ValueError as exc:
        return str(exc)
    try:
        client = _get_client()
        body = await client.get(
            "getRatePlans",
            {
                "propertyIDs": client.settings.property_id,
                "startDate": d_in.isoformat(),
                "endDate": d_out.isoformat(),
                "adults": adultos,
                "children": ninos,
            },
        )
        planes = [fmt.rate_plan(r, noches) for r in (body.get("data") or [])]
        return fmt.to_json(
            {"entrada": d_in.isoformat(), "salida": d_out.isoformat(), "noches": noches, "cantidad": len(planes), "planes": planes}
        )
    except (CloudbedsError, ConfigError) as exc:
        return _error(exc)


# ---------- F4: vistas gerenciales ----------

MAX_PERIOD_DAYS = MAX_RANGE_DAYS
AGG_MAX_RESULTS = 5000  # las agregaciones necesitan todas las reservas del periodo
AGG_CONCURRENCY = 4  # páginas en paralelo (el rate limiter mantiene 4 req/s)


def _period(desde: str | None, hasta: str | None) -> tuple[date, date]:
    """Periodo inclusivo. Por defecto, el mes en curso (hora de Lima)."""
    d1 = _parse_fecha(desde, "desde")
    d2 = _parse_fecha(hasta, "hasta")
    if d1 is None and d2 is None:
        hoy = _today()
        d1 = hoy.replace(day=1)
        d2 = (d1 + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    elif d1 is None:
        d1 = d2.replace(day=1)  # type: ignore[union-attr]
    elif d2 is None:
        d2 = d1
    if d2 < d1:  # type: ignore[operator]
        raise ValueError("El periodo es inválido: la fecha 'desde' es posterior a 'hasta'.")
    if (d2 - d1).days + 1 > MAX_PERIOD_DAYS:  # type: ignore[operator]
        raise ValueError(f"El periodo no puede superar {MAX_PERIOD_DAYS} días; divídelo en consultas más cortas.")
    return d1, d2  # type: ignore[return-value]


def _incomplete_note(truncado: bool) -> dict[str, str]:
    if not truncado:
        return {}
    return {"advertencia": f"Se alcanzó el tope de {AGG_MAX_RESULTS} reservas: las cifras están INCOMPLETAS. Acorta el periodo."}


@mcp.tool(
    title="Resumen del día",
    description=(
        "Resumen gerencial de un día (por defecto hoy): ocupación, y llegadas y salidas con su "
        "TOTAL del día, cuántas ya se realizaron y cuántas siguen pendientes, más no-show, "
        "cancelaciones y una lista corta de reservas. Es la mejor herramienta para '¿cómo va el "
        "día?' o '¿cuántas llegadas/salidas hay hoy?'."
    ),
    annotations=READ_ONLY,
    structured_output=False,
)
async def resumen_dia(
    fecha: Annotated[str | None, _fecha_param("Día a resumir; si se omite, hoy.")] = None,
) -> str:
    try:
        dia_param = _parse_fecha(fecha, "consulta")
    except ValueError as exc:
        return str(exc)
    try:
        client = _get_client()
        dia = (dia_param or _today()).isoformat()
        pid = client.settings.property_id
        dash = await client.get("getDashboard", {"propertyID": pid, "date": dia})
        base = {"propertyID": pid, "includeAllRooms": True}
        arr = await client.get_all("getReservations", {**base, "checkInFrom": dia, "checkInTo": dia}, max_results=AGG_MAX_RESULTS)
        dep = await client.get_all("getReservations", {**base, "checkOutFrom": dia, "checkOutTo": dia}, max_results=AGG_MAX_RESULTS)
        out = agg.day_summary(dash.get("data") or {}, arr["data"], dep["data"], dia)
        out.update(_incomplete_note(arr["truncado"] or dep["truncado"]))
        return fmt.to_json(out)
    except (CloudbedsError, ConfigError) as exc:
        return _error(exc)


@mcp.tool(
    title="Resumen de periodo",
    description=(
        "Estadísticas de reservas en un periodo (por defecto el mes en curso): totales por "
        "estado, por fuente/canal y por tipo de habitación, habitaciones y noches reservadas, "
        "estancia media, cancelaciones y no-show. criterio='checkin' (por defecto) toma las "
        "reservas que LLEGAN en el periodo; criterio='creacion' toma las reservas HECHAS en el "
        "periodo (producción/pickup). Fechas inclusivas, máximo 366 días."
    ),
    annotations=READ_ONLY,
    structured_output=False,
)
async def resumen_periodo(
    fecha_desde: Annotated[str | None, _fecha_param("Inicio del periodo (incluido).")] = None,
    fecha_hasta: Annotated[str | None, _fecha_param("Fin del periodo (incluido).")] = None,
    criterio: Annotated[
        Literal["checkin", "creacion"], Field(description="checkin=llegadas del periodo; creacion=reservas hechas en el periodo.")
    ] = "checkin",
) -> str:
    try:
        desde, hasta = _period(fecha_desde, fecha_hasta)
    except ValueError as exc:
        return str(exc)
    try:
        client = _get_client()
        params: dict[str, object] = {"propertyID": client.settings.property_id, "includeAllRooms": True}
        if criterio == "checkin":
            params.update(checkInFrom=desde.isoformat(), checkInTo=hasta.isoformat())
        else:
            params.update(resultsFrom=f"{desde.isoformat()} 00:00:00", resultsTo=f"{hasta.isoformat()} 23:59:59")
        result = await client.get_all("getReservations", params, max_results=AGG_MAX_RESULTS, concurrency=AGG_CONCURRENCY)
        out = {
            "periodo": {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "criterio": criterio},
            **agg.period_summary(result["data"]),
            **_incomplete_note(result["truncado"]),
        }
        if criterio == "checkin":
            out["nota"] = "Las noches cuentan la estadía completa de las reservas que llegan en el periodo, aunque salgan después."
        return fmt.to_json(out)
    except (CloudbedsError, ConfigError) as exc:
        return _error(exc)


@mcp.tool(
    title="Ingresos del periodo",
    description=(
        "Ingresos de HABITACIÓN por fecha de estadía (noches entre fecha_desde y fecha_hasta, "
        "ambas incluidas; por defecto el mes en curso): noches vendidas, ingreso bruto (tarifas "
        "con impuestos), ingreso neto (sin impuestos, incluye ajustes manuales de precio), ADR, "
        "ocupación, RevPAR y desglose por fuente/canal y por tipo de habitación. Excluye "
        "canceladas y no-show (en Cloudbeds tienen total 0). No incluye extras, pagos ni "
        "cobros. Máximo 366 días."
    ),
    annotations=READ_ONLY,
    structured_output=False,
)
async def ingresos_periodo(
    fecha_desde: Annotated[str | None, _fecha_param("Primera noche del periodo (incluida).")] = None,
    fecha_hasta: Annotated[str | None, _fecha_param("Última noche del periodo (incluida).")] = None,
) -> str:
    try:
        desde, hasta = _period(fecha_desde, fecha_hasta)
    except ValueError as exc:
        return str(exc)
    try:
        client = _get_client()
        pid = client.settings.property_id
        co_from, co_to = agg.stay_query_window(desde, hasta)
        result = await client.get_all(
            "getReservationsWithRateDetails",
            {"propertyID": pid, "reservationCheckOutFrom": co_from.isoformat(), "reservationCheckOutTo": co_to.isoformat()},
            max_results=AGG_MAX_RESULTS,
            concurrency=AGG_CONCURRENCY,
        )
        tipos = await client.get_all("getRoomTypes", {"propertyIDs": pid})
        unidades = sum(int(t.get("roomTypeUnits") or 0) for t in tipos["data"]) or None
        currency = next((r.get("propertyCurrency") for r in result["data"] if r.get("propertyCurrency")), None)
        out = {
            "moneda": currency,
            **agg.revenue(result["data"], desde, hasta, unidades),
            "notas": [
                "Bruto = suma de tarifas por noche (impuestos incluidos). Neto = importe de habitación sin impuestos (subTotal) prorrateado por noche; refleja ajustes manuales de precio.",
                "Ocupación y RevPAR usan todas las habitaciones del inventario (no descuentan bloqueos).",
                "Estadías de más de 35 noches que terminan después del periodo podrían no incluirse (la más larga del último año fue de 31).",
            ],
            **_incomplete_note(result["truncado"]),
        }
        return fmt.to_json(out)
    except (CloudbedsError, ConfigError) as exc:
        return _error(exc)


def main() -> None:
    configure_logging()
    logger.info("Iniciando servidor MCP de Cloudbeds (stdio, solo lectura)")
    mcp.run("stdio")


if __name__ == "__main__":
    main()
