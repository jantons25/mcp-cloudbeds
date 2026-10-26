"""Consolidado de la red (fase 4): funciones merge_* y herramientas con hotel='red'."""

import json
from zoneinfo import ZoneInfo

import pytest
import respx

from cloudbeds_mcp import aggregations as agg
from cloudbeds_mcp import server
from cloudbeds_mcp.client import BASE_URL, CloudbedsClient
from cloudbeds_mcp.config import Hotel, HotelsConfig, Settings
from cloudbeds_mcp.hotels import HotelRegistry

LIMA = ZoneInfo("America/Lima")


# ---------- merge_* ----------

def test_merge_dashboards_recalcula_ocupacion():
    out = agg.merge_dashboards({
        "balta": {"fecha": "2026-10-26", "habitaciones_ocupadas": 10, "porcentaje_ocupacion": 50.0, "llegadas_pendientes": 2,
                  "salidas_pendientes": 1, "in_house": 18, "habitaciones_hotel": 20},
        "plaza": {"fecha": "2026-10-26", "habitaciones_ocupadas": 6, "porcentaje_ocupacion": 40.0, "llegadas_pendientes": None,
                  "salidas_pendientes": 3, "in_house": 9, "habitaciones_hotel": 15},
    })
    assert out == {"fecha": "2026-10-26", "habitaciones_red": 35, "habitaciones_ocupadas": 16,
                   "porcentaje_ocupacion": 45.71,  # 16/35, no el promedio 45 de 50 % y 40 %
                   "llegadas_pendientes": 2, "salidas_pendientes": 4, "in_house": 27}


def test_merge_dashboards_sin_inventario_completo_no_da_porcentaje():
    out = agg.merge_dashboards({
        "a": {"fecha": "2026-10-26", "habitaciones_ocupadas": 3, "habitaciones_hotel": 10},
        "b": {"fecha": "2026-10-27", "habitaciones_ocupadas": 4, "habitaciones_hotel": None},
    })
    assert out["habitaciones_red"] is None and out["porcentaje_ocupacion"] is None
    assert out["habitaciones_ocupadas"] == 7
    assert out["fechas_por_hotel"] == {"a": "2026-10-26", "b": "2026-10-27"}  # zonas horarias distintas


def test_merge_day_summaries():
    def dia(ocup, ih, lleg, sal, units):
        return {"fecha": "2026-10-26", "habitaciones_hotel": units,
                "ocupacion": {"habitaciones_ocupadas": ocup, "porcentaje_ocupacion": 1.0, "in_house": ih},
                "llegadas": {"total": lleg, "ya_ingresaron": 1, "pendientes": lleg - 1, "pendientes_segun_dashboard": lleg - 1,
                             "no_show": 0, "canceladas": 1, "lista": [{"id": "x"}]},
                "salidas": {"total": sal, "ya_salieron": sal, "pendientes": 0, "pendientes_segun_dashboard": 0, "lista": []}}
    out = agg.merge_day_summaries({"a": dia(9, 8, 5, 3, 22), "b": dia(4, 6, 2, 1, 10)})
    assert out["ocupacion"] == {"habitaciones_red": 32, "habitaciones_ocupadas": 13, "porcentaje_ocupacion": 40.62, "in_house": 14}
    assert out["llegadas"] == {"total": 7, "ya_ingresaron": 2, "pendientes": 5, "pendientes_segun_dashboard": 5, "no_show": 0, "canceladas": 2}
    assert out["salidas"]["total"] == 4
    assert "lista" not in out["llegadas"]  # las listas quedan por hotel


def test_merge_period_summaries():
    a = {"periodo": {"desde": "2026-10-01"}, "reservas_total": 4, "reservas_validas": 3, "por_estado": {"confirmada": 3, "cancelada": 1},
         "por_fuente": {"Booking.com": 2, "Website": 1}, "por_tipo_habitacion": {"Doble": 3}, "habitaciones_reservadas": 3,
         "noches_reservadas": 6, "cancelaciones": {"cantidad": 1, "porcentaje": 25.0}, "no_show": 0}
    b = {"periodo": {"desde": "2026-10-01"}, "reservas_total": 6, "reservas_validas": 6, "por_estado": {"confirmada": 6},
         "por_fuente": {"Website": 5, "Expedia": 1}, "por_tipo_habitacion": {"Doble": 2, "Suite": 4}, "habitaciones_reservadas": 6,
         "noches_reservadas": 12, "cancelaciones": {"cantidad": 0, "porcentaje": 0.0}, "no_show": 1}
    out = agg.merge_period_summaries({"a": a, "b": b})
    assert out["reservas_total"] == 10 and out["reservas_validas"] == 9
    assert out["por_fuente"] == {"Website": 6, "Booking.com": 2, "Expedia": 1}
    assert list(out["por_fuente"]) == ["Website", "Booking.com", "Expedia"]  # de mayor a menor
    assert out["por_tipo_habitacion"] == {"Doble": 5, "Suite": 4}
    assert out["estancia_media_noches"] == 2.0
    assert out["cancelaciones"] == {"cantidad": 1, "porcentaje": 10.0}
    assert out["no_show"] == 1 and out["periodo"] == {"desde": "2026-10-01"}


def rev(moneda, noches, bruto, neto, units):
    return {"moneda": moneda, "periodo": {"desde": "2026-10-01", "hasta": "2026-10-31", "dias": 31},
            "reservas_con_noches_en_periodo": 3, "noches_vendidas": noches, "ingreso_habitacion_bruto": bruto,
            "ingreso_habitacion_neto": neto, "adr_bruto": bruto / noches, "habitaciones_hotel": units,
            "por_fuente": {"Website": {"noches": noches, "ingreso_bruto": bruto, "ingreso_neto": neto}},
            "por_tipo_habitacion": {"Doble": {"noches": noches, "ingreso_bruto": bruto}},
            "excluidas_sin_ingreso": {"canceladas": 1, "no_show": 0}}


def test_merge_revenue_misma_moneda():
    out = agg.merge_revenue({"a": rev("PEN", 100, 20000.0, 17000.0, 10), "b": rev("PEN", 50, 5000.0, 4000.0, 5)})
    assert out["moneda"] == "PEN"
    assert out["noches_vendidas"] == 150 and out["habitaciones_red"] == 15
    assert out["ingreso_habitacion_bruto"] == 25000.0 and out["ingreso_habitacion_neto"] == 21000.0
    assert out["adr_bruto"] == 166.67  # 25000/150, no el promedio de 200 y 100
    assert out["ocupacion_pct"] == 32.3  # 150 / (15 hab * 31 días)
    assert out["revpar_neto"] == 45.16  # 21000 / 465
    assert out["por_fuente"]["Website"] == {"noches": 150, "ingreso_bruto": 25000.0, "ingreso_neto": 21000.0}
    assert out["excluidas_sin_ingreso"] == {"canceladas": 2, "no_show": 0}


@pytest.mark.parametrize("monedas", [("PEN", "USD"), ("PEN", None)])
def test_merge_revenue_nunca_suma_monedas_distintas(monedas):
    out = agg.merge_revenue({"a": rev(monedas[0], 100, 20000.0, 17000.0, 10), "b": rev(monedas[1], 50, 5000.0, 4000.0, 5)})
    assert out["moneda"] is None and "NO se suman" in out["advertencia_moneda"]
    assert "ingreso_habitacion_bruto" not in out and "adr_bruto" not in out and "revpar_neto" not in out
    assert out["noches_vendidas"] == 150 and out["ocupacion_pct"] == 32.3  # lo que no es dinero sí se suma
    assert out["por_fuente"] == {"Website": {"noches": 150}}


# ---------- herramientas con hotel="red" ----------

KEYS = {"111": "cbat_KEY_BALTA", "222": "cbat_KEY_PLAZA"}
DASH = {
    "111": {"roomsOccupied": "10", "percentageOccupied": "50", "arrivals": "2", "departures": "1", "inHouse": "18"},
    "222": {"roomsOccupied": "6", "percentageOccupied": "40", "arrivals": "1", "departures": "3", "inHouse": "9"},
}
UNITS = {"111": [{"roomTypeUnits": 12}, {"roomTypeUnits": 8}], "222": [{"roomTypeUnits": 15}]}


def _settings(alias, nombre, pid, moneda="PEN"):
    return Settings(api_key=KEYS[pid], property_id=pid, show_pii=False, tz=LIMA, max_results=500,
                    key_source="keyring", hotel_alias=alias, hotel_name=nombre, currency=moneda)


@pytest.fixture
async def registry(fake_sleep):
    hoteles = (
        Hotel.from_settings(_settings("balta", "Zentra Balta", "111")),
        Hotel.from_settings(_settings("plaza", "Zentra Plaza", "222")),
        Hotel(alias="san_jose", nombre="Zentra San José", property_id="333", tz=LIMA, moneda="PEN",
              motivo="No hay API key de Zentra San José en esta PC."),
    )
    reg = HotelRegistry(
        HotelsConfig(hoteles=hoteles, modo="multi"),
        client_factory=lambda s, *, limiter: CloudbedsClient(s, rate=10_000, sleep=fake_sleep),
    )
    server.set_registry(reg)
    yield reg
    server.set_registry(None)
    await reg.aclose()


@pytest.fixture
def api():
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as mock:
        yield mock


def pid_of(request):
    return request.url.params.get("propertyID") or request.url.params.get("propertyIDs")


def check_key(request):
    # cada hotel consulta con SU key
    assert request.headers["x-api-key"] == KEYS[pid_of(request)]


def per_hotel(api, endpoint, data_by_pid, paged=False, fail=()):
    def handler(request):
        check_key(request)
        pid = pid_of(request)
        if pid in fail:
            return respx.MockResponse(401, json={"success": False})
        data = data_by_pid[pid]
        body = {"success": True, "data": data}
        if paged:
            body["total"] = len(data)
        return respx.MockResponse(200, json=body)
    return api.get(endpoint).mock(side_effect=handler)


async def test_estado_hotel_red(registry, api):
    per_hotel(api, "getDashboard", DASH)
    tipos = per_hotel(api, "getRoomTypes", UNITS, paged=True)
    out = json.loads(await server.estado_hotel(fecha="2026-10-26", hotel="red"))

    assert out["red"]["hoteles_incluidos"] == ["Zentra Balta", "Zentra Plaza"]
    assert out["red"]["hoteles_no_incluidos"] == ["Zentra San José (sin API key en esta PC)"]
    assert "NO incluye: Zentra San José" in out["advertencia"]
    t = out["total_red"]
    assert (t["habitaciones_red"], t["habitaciones_ocupadas"], t["porcentaje_ocupacion"]) == (35, 16, 45.71)
    assert (t["llegadas_pendientes"], t["salidas_pendientes"], t["in_house"]) == (3, 4, 27)
    assert out["hoteles"]["balta"]["nombre"] == "Zentra Balta"
    assert out["hoteles"]["balta"]["habitaciones_ocupadas"] == 10 and out["hoteles"]["plaza"]["habitaciones_hotel"] == 15
    assert list(out) == ["red", "total_red", "hoteles", "advertencia"]

    await server.estado_hotel(fecha="2026-10-26", hotel="todos")
    assert tipos.call_count == 2  # el inventario se guarda un día por hotel


async def test_resumen_dia_red_con_un_hotel_caido(registry, api):
    per_hotel(api, "getDashboard", DASH, fail=("222",))
    per_hotel(api, "getRoomTypes", UNITS, paged=True)
    reservas = [{"reservationID": "R1", "status": "checked_in"}, {"reservationID": "R2", "status": "confirmed"}]
    per_hotel(api, "getReservations", {"111": reservas, "222": []}, paged=True)
    out = json.loads(await server.resumen_dia("2026-10-26", hotel="toda la red"))

    assert "inválida" in out["hoteles"]["plaza"]["error"]
    assert out["red"]["hoteles_incluidos"] == ["Zentra Balta"]
    assert "Zentra Plaza (error al consultar)" in out["advertencia"]
    t = out["total_red"]
    assert t["fecha"] == "2026-10-26"
    assert t["llegadas"]["total"] == 2 and t["llegadas"]["ya_ingresaron"] == 1
    assert t["ocupacion"] == {"habitaciones_red": 20, "habitaciones_ocupadas": 10, "porcentaje_ocupacion": 50.0, "in_house": 18}
    assert out["hoteles"]["balta"]["llegadas"]["lista"][0]["id"] == "R1"


async def test_ocupacion_red_sin_inventario_no_descarta_el_hotel(registry, api):
    per_hotel(api, "getDashboard", DASH)
    per_hotel(api, "getRoomTypes", UNITS, paged=True, fail=("222",))
    out = json.loads(await server.estado_hotel(fecha="2026-10-26", hotel="red"))
    assert out["red"]["hoteles_incluidos"] == ["Zentra Balta", "Zentra Plaza"]
    assert out["total_red"]["habitaciones_ocupadas"] == 16
    assert out["total_red"]["porcentaje_ocupacion"] is None


async def test_buscar_reservas_red(registry, api):
    route = per_hotel(api, "getReservations", {
        "111": [], "222": [{"reservationID": "R9", "guestName": "Juan Pérez", "status": "checked_in"}],
    }, paged=True)
    out = json.loads(await server.buscar_reservas(apellido="Pérez", hotel="red"))
    assert out["total_red"] == {"cantidad": 1, "hoteles_con_resultados": ["plaza"]}
    assert out["hoteles"]["plaza"]["reservas"][0]["huesped"] == "Juan Pérez"
    assert {c.request.url.params["lastName"] for c in route.calls} == {"Pérez"}


async def test_resumen_periodo_red(registry, api):
    reservas = {"111": [{"status": "confirmed", "sourceName": "Website", "startDate": "2026-10-02", "endDate": "2026-10-04"}],
                "222": [{"status": "canceled", "sourceName": "Website"},
                        {"status": "confirmed", "sourceName": "Expedia", "startDate": "2026-10-05", "endDate": "2026-10-06"}]}
    per_hotel(api, "getReservations", reservas, paged=True)
    out = json.loads(await server.resumen_periodo("2026-10-01", "2026-10-31", hotel="grupo"))
    t = out["total_red"]
    assert t["reservas_total"] == 3 and t["noches_reservadas"] == 3
    assert t["cancelaciones"] == {"cantidad": 1, "porcentaje": 33.3}
    assert t["periodo"] == {"desde": "2026-10-01", "hasta": "2026-10-31", "criterio": "checkin"}


async def test_ingresos_periodo_red(registry, api):
    res = {"111": [{"status": "checked_out", "propertyCurrency": "PEN", "sourceName": "Website",
                    "detailedRates": {"2026-10-10": 200}, "balanceDetailed": {"subTotal": 170}}],
           "222": [{"status": "checked_out", "propertyCurrency": "PEN", "sourceName": "Website",
                    "detailedRates": {"2026-10-11": 100, "2026-10-12": 100}, "balanceDetailed": {"subTotal": 160}}]}
    per_hotel(api, "getReservationsWithRateDetails", res, paged=True)
    per_hotel(api, "getRoomTypes", UNITS, paged=True)
    out = json.loads(await server.ingresos_periodo("2026-10-01", "2026-10-31", hotel="red"))
    t = out["total_red"]
    assert t["moneda"] == "PEN" and t["noches_vendidas"] == 3
    assert t["ingreso_habitacion_bruto"] == 400.0 and t["ingreso_habitacion_neto"] == 330.0
    assert t["adr_bruto"] == 133.33 and t["habitaciones_red"] == 35
    assert out["hoteles"]["plaza"]["ingreso_habitacion_bruto"] == 200.0


async def test_ingresos_red_con_monedas_distintas(registry, api):
    res = {"111": [{"status": "checked_out", "propertyCurrency": "PEN", "detailedRates": {"2026-10-10": 200}}],
           "222": [{"status": "checked_out", "propertyCurrency": "USD", "detailedRates": {"2026-10-11": 100}}]}
    per_hotel(api, "getReservationsWithRateDetails", res, paged=True)
    per_hotel(api, "getRoomTypes", UNITS, paged=True)
    out = json.loads(await server.ingresos_periodo("2026-10-01", "2026-10-31", hotel="red"))
    assert out["total_red"]["moneda"] is None and "ingreso_habitacion_bruto" not in out["total_red"]
    assert out["hoteles"]["balta"]["moneda"] == "PEN" and out["hoteles"]["plaza"]["moneda"] == "USD"


async def test_periodo_invalido_en_red_no_llama_api(registry, api):
    route = api.route()
    out = await server.ingresos_periodo("2026-10-31", "2026-10-01", hotel="red")
    assert "posterior" in out and route.call_count == 0


async def test_un_hotel_con_herramienta_de_red_responde_normal(registry, api):
    per_hotel(api, "getDashboard", DASH)
    out = json.loads(await server.estado_hotel(fecha="2026-10-26", hotel="Plaza"))
    assert out["hotel"] == {"alias": "plaza", "nombre": "Zentra Plaza"}
    assert "red" not in out and "habitaciones_hotel" not in out


async def test_red_sin_hotel_sigue_pidiendo_elegir(registry, api):
    route = api.route()
    assert (await server.resumen_dia()).startswith("Indica de qué hotel")
    assert route.call_count == 0


async def test_red_con_un_solo_hotel_es_consulta_normal(settings, api, fake_sleep):
    c = CloudbedsClient(settings, rate=10_000, sleep=fake_sleep)
    server.set_client(c)
    try:
        api.get("getDashboard").respond(200, json={"success": True, "data": {"roomsOccupied": "3"}})
        out = json.loads(await server.estado_hotel(fecha="2026-10-26", hotel="red"))
    finally:
        server.set_client(None)
        await c.aclose()
    assert out["habitaciones_ocupadas"] == 3 and "total_red" not in out


async def test_red_sin_ningun_hotel_que_responda(registry, api):
    per_hotel(api, "getDashboard", DASH, fail=("111", "222"))
    out = json.loads(await server.estado_hotel(fecha="2026-10-26", hotel="red"))
    assert "total_red" not in out and out["red"]["hoteles_incluidos"] == []
    assert set(out["hoteles"]) == {"balta", "plaza"}
