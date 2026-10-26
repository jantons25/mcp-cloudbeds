"""Tests de las vistas gerenciales (F4): lógica de agregación y herramientas."""

import json
from datetime import date

import httpx
import pytest
import respx

from cloudbeds_mcp import aggregations as agg
from cloudbeds_mcp import server
from cloudbeds_mcp.client import BASE_URL, CloudbedsClient


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


def room(tipo, rates, status="checked_out", ci=None, co=None):
    return {"roomTypeName": tipo, "roomStatus": status, "detailedRoomRates": rates,
            "roomCheckIn": ci, "roomCheckOut": co}


def rwrd(rid, status, source, rooms, sub_total, deleted=False):
    rates: dict[str, float] = {}
    for x in rooms:
        for d, v in x["detailedRoomRates"].items():
            rates[d] = rates.get(d, 0) + v
    return {"reservationID": rid, "status": status, "sourceName": source, "isDeleted": deleted,
            "propertyCurrency": "PEN", "detailedRates": rates, "rooms": rooms,
            "balanceDetailed": {"subTotal": sub_total}}


# Octubre: 1 al 31. Tarifas con impuestos (subTotal = tarifa / 1.12).
RES = [
    # 2 noches dentro del periodo
    rwrd("A", "checked_out", "Booking.com", [room("Doble", {"2026-10-10": 112.0, "2026-10-11": 112.0})], 200.0),
    # cruza el borde: 30/10, 31/10 dentro; 01/11 fuera
    rwrd("B", "checked_in", "Website", [room("Suite", {"2026-10-30": 224.0, "2026-10-31": 224.0, "2026-11-01": 224.0})], 600.0),
    # ajuste manual: tarifa 200, cobrado 300 (subTotal 278.57 como en la API real)
    rwrd("C", "checked_in", "Website", [room("Doble", {"2026-10-15": 200.0})], 278.57),
    # cancelada y no-show: conservan tarifas pero no generan ingreso
    rwrd("D", "canceled", "Booking.com", [room("Doble", {"2026-10-12": 291.54}, status="canceled")], 0),
    rwrd("E", "no_show", "Expedia", [room("Suite", {"2026-10-20": 630.0})], 0),
    # multi-habitación con una habitación cancelada
    rwrd("F", "checked_out", "Booking.com", [room("Doble", {"2026-10-05": 100.0}),
                                             room("Suite", {"2026-10-05": 150.0}, status="cancelled")], 89.29),
    # fuera del periodo y borrada
    rwrd("G", "confirmed", "Website", [room("Doble", {"2026-11-10": 112.0})], 100.0),
    rwrd("H", "checked_out", "Website", [room("Doble", {"2026-10-08": 112.0})], 100.0, deleted=True),
]


def test_revenue_ingresos_y_exclusiones():
    out = agg.revenue(RES, date(2026, 10, 1), date(2026, 10, 31), unidades=22)
    # A: 224 | B: 448 de 672 | C: 200 | F: 100 (la Suite cancelada no cuenta)
    assert out["noches_vendidas"] == 2 + 2 + 1 + 1
    assert out["ingreso_habitacion_bruto"] == 972.0
    # neto: A 200 | B 600*448/672=400 | C 278.57 | F: 89.29*100/250... (factor sobre tarifas activas)
    assert out["reservas_con_noches_en_periodo"] == 4
    assert out["excluidas_sin_ingreso"] == {"canceladas": 1, "no_show": 1}
    assert out["adr_bruto"] == round(972 / 6, 2)
    assert out["periodo"] == {"desde": "2026-10-01", "hasta": "2026-10-31", "dias": 31}
    assert out["ocupacion_pct"] == round(100 * 6 / (22 * 31), 1)


def test_revenue_neto_prorratea_subtotal_con_ajuste_manual():
    out = agg.revenue([RES[1], RES[2]], date(2026, 10, 1), date(2026, 10, 31), unidades=None)
    # B: 600 * (448/672) = 400 ; C: ajuste manual 278.57 > tarifa 200
    assert out["ingreso_habitacion_neto"] == round(400 + 278.57, 2)
    assert out["ocupacion_pct"] is None and out["revpar_neto"] is None


def test_revenue_desglose_por_fuente_y_tipo():
    out = agg.revenue(RES, date(2026, 10, 1), date(2026, 10, 31), unidades=22)
    assert out["por_fuente"]["Website"]["noches"] == 3
    assert out["por_fuente"]["Website"]["ingreso_bruto"] == 648.0
    assert out["por_fuente"]["Booking.com"]["noches"] == 3
    assert "Expedia" not in out["por_fuente"]  # solo tenía un no-show
    assert out["por_tipo_habitacion"]["Doble"]["noches"] == 4
    assert out["por_tipo_habitacion"]["Suite"] == {"noches": 2, "ingreso_bruto": 448.0}
    assert list(out["por_fuente"]) == ["Website", "Booking.com"] or list(out["por_fuente"]) == ["Booking.com", "Website"]


def test_revenue_un_solo_dia():
    out = agg.revenue(RES, date(2026, 10, 31), date(2026, 10, 31), unidades=22)
    assert out["noches_vendidas"] == 1 and out["ingreso_habitacion_bruto"] == 224.0


def test_revenue_sin_rooms_usa_detailed_rates():
    r = {"status": "checked_out", "sourceName": "Walk-in", "detailedRates": {"2026-10-01": 50, "2026-10-02": 50},
         "rooms": [], "balanceDetailed": {"subTotal": 89.29}}
    out = agg.revenue([r], date(2026, 10, 1), date(2026, 10, 1), unidades=None)
    assert out["noches_vendidas"] == 1 and out["ingreso_habitacion_neto"] == round(89.29 / 2, 2)


def test_stay_query_window():
    assert agg.stay_query_window(date(2026, 10, 1), date(2026, 10, 31)) == (date(2026, 10, 2), date(2026, 12, 6))


# ---------- period_summary ----------

RESERVAS = [
    {"reservationID": "1", "status": "checked_out", "sourceName": "Booking.com", "startDate": "2026-10-01",
     "endDate": "2026-10-04", "rooms": [{"roomTypeName": "Doble", "roomCheckIn": "2026-10-01", "roomCheckOut": "2026-10-04", "roomStatus": "checked_out"}]},
    {"reservationID": "2", "status": "confirmed", "sourceName": "Website", "startDate": "2026-10-02",
     "endDate": "2026-10-03", "rooms": [
         {"roomTypeName": "Doble", "roomCheckIn": "2026-10-02", "roomCheckOut": "2026-10-03", "roomStatus": "not_checked_in"},
         {"roomTypeName": "Suite", "roomCheckIn": "2026-10-02", "roomCheckOut": "2026-10-03", "roomStatus": "not_checked_in"}]},
    {"reservationID": "3", "status": "canceled", "sourceName": "Booking.com", "startDate": "2026-10-05", "endDate": "2026-10-07",
     "rooms": [{"roomTypeName": "Suite", "roomStatus": "cancelled"}]},
    {"reservationID": "4", "status": "no_show", "sourceName": "Expedia", "startDate": "2026-10-06", "endDate": "2026-10-07"},
]


def test_period_summary():
    out = agg.period_summary(RESERVAS)
    assert out["reservas_total"] == 4 and out["reservas_validas"] == 2
    assert out["por_estado"] == {"con check-out": 1, "confirmada": 1, "cancelada": 1, "no show": 1}
    assert out["por_fuente"] == {"Booking.com": 1, "Website": 1}
    assert out["por_tipo_habitacion"] == {"Doble": 2, "Suite": 1}
    assert out["habitaciones_reservadas"] == 3
    assert out["noches_reservadas"] == 3 + 1 + 1
    assert out["estancia_media_noches"] == round(5 / 3, 2)
    assert out["cancelaciones"] == {"cantidad": 1, "porcentaje": 25.0}
    assert out["no_show"] == 1


def test_period_summary_vacio():
    out = agg.period_summary([])
    assert out["reservas_total"] == 0 and out["cancelaciones"]["porcentaje"] is None


# ---------- day_summary ----------

def test_day_summary_totales_y_pendientes():
    arrivals = [
        {"reservationID": "a1", "status": "checked_in", "guestName": "X"},
        {"reservationID": "a2", "status": "confirmed", "guestName": "Y"},
        {"reservationID": "a3", "status": "canceled"},
        {"reservationID": "a4", "status": "no_show"},
    ]
    departures = [{"reservationID": "d1", "status": "checked_out"}, {"reservationID": "d2", "status": "checked_in"}]
    dash = {"roomsOccupied": 9, "percentageOccupied": 40.91, "arrivals": "1", "departures": "1", "inHouse": 8}
    out = agg.day_summary(dash, arrivals, departures, "2026-10-26")
    ll = out["llegadas"]
    assert (ll["total"], ll["ya_ingresaron"], ll["pendientes"], ll["no_show"], ll["canceladas"]) == (2, 1, 1, 1, 1)
    assert ll["pendientes_segun_dashboard"] == 1  # texto "1" normalizado
    assert [x["id"] for x in ll["lista"]] == ["a1", "a2"]
    sal = out["salidas"]
    assert (sal["total"], sal["ya_salieron"], sal["pendientes"]) == (2, 1, 1)
    assert out["ocupacion"] == {"habitaciones_ocupadas": 9, "porcentaje_ocupacion": 40.91, "in_house": 8}


def test_day_summary_recorta_lista():
    arrivals = [{"reservationID": str(i), "status": "confirmed"} for i in range(30)]
    out = agg.day_summary({}, arrivals, [], "2026-10-26", limit=20)
    assert out["llegadas"]["total"] == 30 and len(out["llegadas"]["lista"]) == 20
    assert out["lista_recortada"] is True


# ---------- periodo y herramientas ----------

def test_period_por_defecto_mes_en_curso(client, monkeypatch):
    monkeypatch.setattr(server, "_today", lambda: date(2026, 2, 14))
    assert server._period(None, None) == (date(2026, 2, 1), date(2026, 2, 28))
    assert server._period(None, "2026-03-10") == (date(2026, 3, 1), date(2026, 3, 10))
    assert server._period("2026-03-10", None) == (date(2026, 3, 10), date(2026, 3, 10))


@pytest.mark.parametrize(
    ("desde", "hasta", "msg"),
    [("2026-10-31", "2026-10-01", "posterior"), ("2026-01-01", "2027-01-02", "366"), ("31/10/2026", None, "YYYY-MM-DD")],
)
async def test_periodo_invalido_no_llama_api(client, api, desde, hasta, msg):
    route = api.route()
    for tool in (server.resumen_periodo, server.ingresos_periodo):
        out = await tool(desde, hasta)
        assert msg in out
    assert route.call_count == 0


async def test_ingresos_periodo_consulta_y_respuesta(client, api):
    rw = api.get("getReservationsWithRateDetails").respond(200, json={"success": True, "data": RES, "total": len(RES)})
    api.get("getRoomTypes").respond(200, json={"success": True, "data": [{"roomTypeUnits": 13}, {"roomTypeUnits": 9}], "total": 2})
    out = json.loads(await server.ingresos_periodo("2026-10-01", "2026-10-31"))
    p = rw.calls.last.request.url.params
    assert (p["reservationCheckOutFrom"], p["reservationCheckOutTo"]) == ("2026-10-02", "2026-12-06")
    assert p["propertyID"] == "12345"
    assert out["moneda"] == "PEN" and out["habitaciones_hotel"] == 22
    assert out["ingreso_habitacion_bruto"] == 972.0
    assert "advertencia" not in out


async def test_ingresos_periodo_advierte_si_trunca(client, api, monkeypatch):
    monkeypatch.setattr(server, "AGG_MAX_RESULTS", 2)
    api.get("getReservationsWithRateDetails").respond(200, json={"success": True, "data": RES[:2], "total": 50})
    api.get("getRoomTypes").respond(200, json={"success": True, "data": [], "total": 0})
    out = json.loads(await server.ingresos_periodo("2026-10-01", "2026-10-31"))
    assert "INCOMPLETAS" in out["advertencia"]


async def test_resumen_periodo_criterios(client, api):
    route = api.get("getReservations").respond(200, json={"success": True, "data": RESERVAS, "total": 4})
    out = json.loads(await server.resumen_periodo("2026-10-01", "2026-10-31"))
    p = route.calls.last.request.url.params
    assert (p["checkInFrom"], p["checkInTo"], p["includeAllRooms"]) == ("2026-10-01", "2026-10-31", "1")
    assert out["periodo"]["criterio"] == "checkin" and out["reservas_total"] == 4 and "nota" in out

    await server.resumen_periodo("2026-10-01", "2026-10-31", criterio="creacion")
    p = route.calls.last.request.url.params
    assert (p["resultsFrom"], p["resultsTo"]) == ("2026-10-01 00:00:00", "2026-10-31 23:59:59")
    assert "checkInFrom" not in p


async def test_resumen_dia_consulta_dashboard_llegadas_y_salidas(client, api):
    api.get("getDashboard").respond(200, json={"success": True, "data": {"roomsOccupied": 9, "arrivals": "2", "departures": "1"}})
    route = api.get("getReservations")
    route.side_effect = [
        httpx.Response(200, json={"success": True, "data": [{"reservationID": "a", "status": "confirmed"}], "total": 1}),
        httpx.Response(200, json={"success": True, "data": [{"reservationID": "d", "status": "checked_out"}], "total": 1}),
    ]
    out = json.loads(await server.resumen_dia("2026-10-26"))
    p_arr, p_dep = (c.request.url.params for c in route.calls)
    assert (p_arr["checkInFrom"], p_arr["checkInTo"]) == ("2026-10-26", "2026-10-26")
    assert (p_dep["checkOutFrom"], p_dep["checkOutTo"]) == ("2026-10-26", "2026-10-26")
    assert out["llegadas"]["pendientes"] == 1 and out["salidas"]["ya_salieron"] == 1


async def test_herramientas_f4_registradas_solo_lectura():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    for name in ("resumen_dia", "resumen_periodo", "ingresos_periodo"):
        assert tools[name].annotations.readOnlyHint is True
