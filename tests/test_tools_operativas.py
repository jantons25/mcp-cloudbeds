"""Tests de las herramientas operativas (F3), con las formas reales observadas en la API."""

import json
from datetime import datetime, timedelta

import httpx
import pytest
import respx

from cloudbeds_mcp import pii, server
from cloudbeds_mcp.client import BASE_URL, CloudbedsClient

F3_TOOLS = {
    "disponibilidad", "tipos_habitacion", "habitaciones", "asignaciones_del_dia",
    "estado_housekeeping", "fuentes_reserva", "planes_tarifa",
}


@pytest.fixture
async def client(settings, fake_sleep):
    c = CloudbedsClient(settings, rate=10_000, sleep=fake_sleep)
    server.set_client(c)
    yield c
    server.set_client(None)
    await c.aclose()


@pytest.fixture
def api():
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as mock:
        yield mock


def hoy(client):
    return datetime.now(client.settings.tz).date()


async def test_herramientas_f3_registradas_solo_lectura():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    assert F3_TOOLS <= set(tools)
    for name in F3_TOOLS:
        assert tools[name].annotations.readOnlyHint is True


# ---------- disponibilidad ----------

AVAIL = {
    "success": True,
    "data": [{
        "propertyID": "12345",
        "propertyCurrency": {"currencyCode": "PEN", "currencySymbol": "S/."},
        "propertyRooms": [
            {"roomTypeName": "Habitación Matrimonial", "roomsAvailable": 3, "roomRate": 660,
             "ratePlanNamePublic": "default", "maxGuests": "2", "roomTypePhotos": [{"image": "x"}]},
        ],
    }],
    "roomCount": 1, "count": 1, "total": 1,
}


async def test_disponibilidad_por_defecto_hoy_manana(client, api):
    route = api.get("getAvailableRoomTypes").respond(200, json=AVAIL)
    out = json.loads(await server.disponibilidad())
    p = route.calls.last.request.url.params
    assert p["startDate"] == hoy(client).isoformat()
    assert p["endDate"] == (hoy(client) + timedelta(days=1)).isoformat()
    assert (p["rooms"], p["adults"], p["children"]) == ("1", "1", "0")
    assert p["propertyIDs"] == "12345"
    assert out["noches"] == 1 and out["moneda"] == "PEN"


async def test_disponibilidad_tarifa_es_total_de_estadia(client, api):
    api.get("getAvailableRoomTypes").respond(200, json=AVAIL)
    out = json.loads(await server.disponibilidad("2026-11-02", "2026-11-05", adultos=2))
    tipo = out["tipos"][0]
    assert out["noches"] == 3
    assert tipo == {"tipo": "Habitación Matrimonial", "disponibles": 3, "tarifa_estadia": 660.0,
                    "tarifa_promedio_noche": 220.0, "plan_tarifa": "default", "max_huespedes": 2}


async def test_disponibilidad_sin_resultados(client, api):
    api.get("getAvailableRoomTypes").respond(200, json={"success": True, "data": [{"propertyRooms": []}]})
    out = json.loads(await server.disponibilidad("2026-11-02", "2026-11-03"))
    assert out["tipos"] == [] and "nota" in out


async def test_disponibilidad_salida_antes_de_entrada(client, api):
    route = api.route()
    out = await server.disponibilidad("2026-11-05", "2026-11-05")
    assert "posterior" in out and route.call_count == 0


# ---------- tipos_habitacion ----------

async def test_tipos_habitacion(client, api):
    route = api.get("getRoomTypes").respond(200, json={"success": True, "count": 2, "total": 2, "data": [
        {"roomTypeID": "1", "roomTypeName": "Individual", "roomTypeNameShort": "HI", "roomTypeUnits": 4,
         "maxGuests": 1, "isPrivate": True, "roomsAvailable": 0, "roomTypeFeatures": ["wifi", "tv"]},
        {"roomTypeID": "2", "roomTypeName": "Doble", "roomTypeNameShort": "HD", "roomTypeUnits": 3, "maxGuests": 4},
    ]})
    out = json.loads(await server.tipos_habitacion())
    assert route.calls.last.request.url.params["propertyIDs"] == "12345"
    assert out["cantidad_tipos"] == 2 and out["total_unidades"] == 7
    assert out["tipos"][0]["caracteristicas"] == ["wifi", "tv"]
    assert "roomsAvailable" not in json.dumps(out) and "disponibles" not in out["tipos"][0]


# ---------- habitaciones ----------

ROOMS = {"success": True, "count": 2, "total": 2, "data": [{"propertyID": "12345", "rooms": [
    {"roomID": "1-0", "roomName": "HI(104)", "roomTypeName": "Individual", "roomTypeID": "1",
     "maxGuests": 1, "roomBlocked": False, "isVirtual": False},
    {"roomID": "2-0", "roomName": "HD(201)", "roomTypeName": "Doble", "roomTypeID": "2",
     "maxGuests": 4, "roomBlocked": True, "isVirtual": False},
]}]}


async def test_habitaciones_aplana_por_propiedad(client, api):
    route = api.get("getRooms").respond(200, json=ROOMS)
    out = json.loads(await server.habitaciones())
    assert out["cantidad"] == 2
    assert out["habitaciones"][1] == {"id": "2-0", "habitacion": "HD(201)", "tipo": "Doble", "tipo_id": "2",
                                      "max_huespedes": 4, "bloqueada": True}
    assert route.call_count == 1  # total alcanzado: no pide más páginas


async def test_habitaciones_sin_asignar_en_periodo(client, api):
    route = api.get("getRooms").respond(200, json=ROOMS)
    out = json.loads(await server.habitaciones("2", "2026-11-01", "2026-11-03"))
    p = route.calls.last.request.url.params
    assert (p["roomTypeID"], p["startDate"], p["endDate"]) == ("2", "2026-11-01", "2026-11-03")
    assert "no equivale a disponibles" in out["filtro"]
    assert out["bloqueadas_incluidas"] == 1


async def test_habitaciones_periodo_incompleto(client, api):
    route = api.route()
    out = await server.habitaciones(fecha_desde="2026-11-01")
    assert "juntas" in out and route.call_count == 0


async def test_habitaciones_periodo_misma_fecha(client, api):
    route = api.route()
    out = await server.habitaciones(fecha_desde="2026-11-01", fecha_hasta="2026-11-01")
    assert "posterior" in out and route.call_count == 0


# ---------- asignaciones_del_dia ----------

async def test_asignaciones_del_dia(client, api):
    route = api.get("getReservationAssignments").respond(200, json={"success": True, "data": [
        {"reservationID": "R1", "guestName": "Rosa Quispe", "unassigned": None,
         "assigned": [{"roomName": "HM(105)", "roomTypeName": "Matrimonial", "isRoomLocked": False}]},
        {"reservationID": "R2", "guestName": "Luis Rojas", "unassigned": 1},
    ]})
    out = json.loads(await server.asignaciones_del_dia())
    assert route.calls.last.request.url.params["date"] == hoy(client).isoformat()
    assert out["reservas"] == 2 and out["habitaciones_asignadas"] == 1
    assert out["reservas_con_habitaciones_sin_asignar"] == 1
    assert out["asignaciones"][0]["habitaciones"] == [{"habitacion": "HM(105)", "tipo": "Matrimonial"}]
    assert out["asignaciones"][1]["sin_asignar"] == 1


# ---------- estado_housekeeping ----------

def hk(i, condicion="dirty", ocupada=False, fd="unused", **extra):
    return {"roomID": f"1-{i}", "roomName": f"H{i}", "roomTypeName": "Doble", "roomCondition": condicion,
            "roomOccupied": ocupada, "roomBlocked": False, "frontdeskStatus": fd, "housekeeper": "",
            "doNotDisturb": False, "refusedService": False, "vacantPickup": False, "roomComments": "",
            "date": "2026-10-26 08:00:00", **extra}


async def test_housekeeping_resumen_y_total_no_fiable(client, api):
    data = [hk(0, "clean", True, "stayover"), hk(1, "dirty", True, "check-out"), hk(2, "dirty", False, "unused")]
    route = api.get("getHousekeepingStatus")
    # La API real informa total=42 con solo 22 habitaciones; aquí total=10 con 3 elementos.
    route.side_effect = [httpx.Response(200, json={"success": True, "data": data, "count": 10, "total": 10})]
    out = json.loads(await server.estado_housekeeping())
    assert route.call_count == 1
    assert out["resumen"] == {"habitaciones": 3, "limpias": 1, "sucias": 2, "ocupadas": 2, "bloqueadas": 0,
                              "por_estado_recepcion": {"continúa (stayover)": 1, "salida": 1, "libre": 1}}
    assert out["habitaciones"][0]["condicion"] == "limpia"


HK_MIX = [hk(0, "dirty", True, "stayover"), hk(1, "dirty", False, "unused"),
          hk(2, "clean", False, "unused"), hk(3, "clean", True, "check-out")]


async def test_housekeeping_filtra_en_el_servidor(client, api):
    # Regresión: Cloudbeds devolvía las ocupadas con roomOccupied=false. Ahora no se envían
    # filtros y se filtra localmente, aunque Cloudbeds devuelva todo.
    route = api.get("getHousekeepingStatus").respond(200, json={"success": True, "data": HK_MIX})
    out = json.loads(await server.estado_housekeeping(condicion="dirty", ocupada=False))
    p = route.calls.last.request.url.params
    assert "roomOccupied" not in p and "roomCondition" not in p
    assert [h["habitacion"] for h in out["habitaciones"]] == ["H1"]
    assert out["resumen"]["habitaciones"] == 1 and out["resumen"]["ocupadas"] == 0


@pytest.mark.parametrize(
    ("kwargs", "esperadas"),
    [
        ({"ocupada": False}, ["H1", "H2"]),
        ({"ocupada": True}, ["H0", "H3"]),
        ({"condicion": "clean"}, ["H2", "H3"]),
        ({"condicion": "clean", "ocupada": True}, ["H3"]),
        ({}, ["H0", "H1", "H2", "H3"]),
    ],
)
async def test_housekeeping_combinaciones_de_filtro(client, api, kwargs, esperadas):
    api.get("getHousekeepingStatus").respond(200, json={"success": True, "data": HK_MIX})
    out = json.loads(await server.estado_housekeeping(**kwargs))
    assert [h["habitacion"] for h in out["habitaciones"]] == esperadas
    assert out["resumen"]["habitaciones"] == len(esperadas)


async def test_housekeeping_comentarios_sin_pii(client, api):
    api.get("getHousekeepingStatus").respond(200, json={"success": True, "data": [
        hk(0, roomComments="Llamar al huésped al +51 987 654 321 o rosa@gmail.com"),
    ]})
    raw = await server.estado_housekeeping()
    assert "987 654" not in raw and "rosa@gmail.com" not in raw
    assert "***321" in raw and "r***@g***.com" in raw


def test_scrub_text():
    assert pii.scrub_text("DNI 45678912, cel 987654321", False) == "DNI ***912, cel ***321"
    assert pii.scrub_text("hab. 201 lista", False) == "hab. 201 lista"
    assert pii.scrub_text("tel 987654321", True) == "tel 987654321"


# ---------- fuentes_reserva ----------

async def test_fuentes_reserva_data_anidada_y_activas(client, api):
    # Forma real verificada: data = [[...]] (una lista por propiedad), comisión como texto
    api.get("getSources").respond(200, json={"success": True, "count": 3, "data": [[
        {"sourceID": "s-1", "sourceName": "Website/Booking Engine", "isThirdParty": False, "status": True,
         "commission": "0.00000", "paymentCollect": "hotel", "taxes": [], "fees": []},
        {"sourceID": "ss-2-0", "sourceName": "Booking.com", "isThirdParty": True, "status": True,
         "commission": "15.00000", "paymentCollect": "channel"},
        {"sourceID": "s-3", "sourceName": "Antigua", "isThirdParty": False, "status": False, "commission": "0"},
    ]]})
    out = json.loads(await server.fuentes_reserva())
    assert out["cantidad"] == 2
    assert out["fuentes"][1] == {"id": "ss-2-0", "fuente": "Booking.com", "tercero": True, "activa": True,
                                 "comision_pct": 15.0, "cobra": "canal"}
    todas = json.loads(await server.fuentes_reserva(solo_activas=False))
    assert todas["cantidad"] == 3


# ---------- planes_tarifa ----------

async def test_planes_tarifa(client, api):
    route = api.get("getRatePlans").respond(200, json={"success": True, "data": [
        {"rateID": "10", "roomTypeName": "Suite", "roomRate": 1584, "totalRate": 1584, "roomsAvailable": 1,
         "isDerived": False, "ratePlanNamePublic": None},
        {"rateID": "11", "roomTypeName": "Suite", "roomRate": 945, "totalRate": 945, "roomsAvailable": 1,
         "isDerived": False, "ratePlanNamePublic": "ZENTRALOVE", "ratePlanNamePrivate": "ZENTRALOVE",
         "promoCode": "ZENTRALOVE"},
    ]})
    out = json.loads(await server.planes_tarifa("2026-11-02", "2026-11-05", adultos=2))
    p = route.calls.last.request.url.params
    assert (p["startDate"], p["endDate"], p["adults"]) == ("2026-11-02", "2026-11-05", "2")
    assert "children" not in p
    assert out["noches"] == 3 and out["cantidad"] == 2
    assert out["planes"][0]["plan"] == "Tarifa base"
    assert out["planes"][0]["tarifa_promedio_noche"] == 528.0
    assert out["planes"][1]["codigo_promo"] == "ZENTRALOVE"


# ---------- scopes faltantes ----------

SCOPE_CASES = [
    ("disponibilidad", "getAvailableRoomTypes", "read:room", {}),
    ("tipos_habitacion", "getRoomTypes", "read:room", {}),
    ("habitaciones", "getRooms", "read:room", {}),
    ("asignaciones_del_dia", "getReservationAssignments", "read:reservation", {}),
    ("estado_housekeeping", "getHousekeepingStatus", "read:housekeeping", {}),
    ("fuentes_reserva", "getSources", "read:reservation", {}),
    ("planes_tarifa", "getRatePlans", "read:rate", {}),
]


@pytest.mark.parametrize(("tool", "endpoint", "scope", "kwargs"), SCOPE_CASES)
async def test_scope_faltante_http_403(client, api, tool, endpoint, scope, kwargs):
    api.get(endpoint).respond(403, json={"success": False, "message": "Forbidden"})
    out = await getattr(server, tool)(**kwargs)
    assert out.startswith("No se pudo consultar Cloudbeds")
    assert scope in out and "recrearla" in out


@pytest.mark.parametrize(("tool", "endpoint", "scope", "kwargs"), SCOPE_CASES)
async def test_scope_faltante_success_false(client, api, tool, endpoint, scope, kwargs):
    api.get(endpoint).respond(200, json={"success": False, "message": "Insufficient scope for this method"})
    out = await getattr(server, tool)(**kwargs)
    assert scope in out


# ---------- límite de rango de fechas (F5) ----------

@pytest.mark.parametrize(
    ("tool", "kwargs"),
    [
        ("buscar_reservas", {"checkin_desde": "2026-01-01", "checkin_hasta": "2027-01-02"}),
        ("buscar_reservas", {"checkout_desde": "2026-01-01", "checkout_hasta": "2027-06-01"}),
        ("disponibilidad", {"fecha_entrada": "2026-01-01", "fecha_salida": "2027-01-03"}),
        ("planes_tarifa", {"fecha_entrada": "2026-01-01", "fecha_salida": "2027-01-03"}),
        ("habitaciones", {"fecha_desde": "2026-01-01", "fecha_hasta": "2027-01-03"}),
        ("resumen_periodo", {"fecha_desde": "2026-01-01", "fecha_hasta": "2027-01-02"}),
        ("ingresos_periodo", {"fecha_desde": "2026-01-01", "fecha_hasta": "2027-01-02"}),
    ],
)
async def test_rango_mayor_a_366_dias_se_rechaza_sin_llamar_api(client, api, tool, kwargs):
    route = api.route()
    out = await getattr(server, tool)(**kwargs)
    assert "no puede superar 366 días" in out
    assert route.call_count == 0


@pytest.mark.parametrize(
    ("tool", "kwargs", "endpoint"),
    [
        ("buscar_reservas", {"checkin_desde": "2026-01-01", "checkin_hasta": "2027-01-01"}, "getReservations"),
        ("disponibilidad", {"fecha_entrada": "2026-01-01", "fecha_salida": "2027-01-02"}, "getAvailableRoomTypes"),
    ],
)
async def test_rango_de_366_dias_se_permite(client, api, tool, kwargs, endpoint):
    api.get(endpoint).respond(200, json={"success": True, "data": []})
    out = await getattr(server, tool)(**kwargs)
    assert "no puede superar" not in out
    assert json.loads(out)  # respuesta normal en JSON
