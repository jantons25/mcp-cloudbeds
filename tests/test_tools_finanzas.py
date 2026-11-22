"""Herramientas extras_periodo, pagos_periodo y resumen_financiero (un hotel y la red)."""

import json
from zoneinfo import ZoneInfo

import pytest
import respx

from cloudbeds_mcp import server
from cloudbeds_mcp.client import ACCOUNTING_URL, BASE_URL, CloudbedsClient
from cloudbeds_mcp.config import Hotel, HotelsConfig, Settings
from cloudbeds_mcp.hotels import HotelRegistry

LIMA = ZoneInfo("America/Lima")
TX_URL = ACCOUNTING_URL + "transactions"
KEYS = {"111": "cbat_KEY_BALTA", "222": "cbat_KEY_PLAZA"}

ITEMS = [{"itemID": "1", "name": "Lavandería", "categoryName": "Otros"},
         {"itemID": "2", "name": "Agua San Luis", "categoryName": "Minibar"}]
METODOS = {"methods": [{"name": "Efectivo", "method": "cash"}, {"name": "Yape", "method": "Yape"}]}


def tx(kind, amount, desc, **extra):
    return {"externalRelationKind": kind, "amount": amount, "currencyScale": 2, "currency": "PEN",
            "description": desc, "serviceDate": "2026-11-15", "businessDate": "2026-11-15",
            "transactionDatetimePropertyTime": "2026-11-15T10:00:00", **extra}


TRANS = {
    "111": [tx("ITEM", 25.0, "Lavandería"), tx("ITEM", 6.0, "Agua San Luis"),
            tx("ROOM", 100.0, "Noche", internalTransactionCode="1000"),
            tx("PAYMENT", -129.0, "Pago Yape de Rosa Quispe", internalTransactionCode="9000")],
    "222": [tx("ITEM", 50.0, "Lavandería"), tx("PAYMENT", -40.0, "Efectivo")],
}


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
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def cloudbeds(api):
    """Simula la API v1.3 (catálogos) y la contable, cada hotel con su key y propertyID."""
    def catalogo(data):
        def handler(request):
            pid = request.url.params["propertyID"]
            assert request.headers["x-api-key"] == KEYS[pid]
            return respx.MockResponse(200, json={"success": True, "data": data})
        return handler

    def transacciones(request):
        pid = request.headers["X-Property-ID"]
        assert request.headers["Authorization"] == f"Bearer {KEYS[pid]}"
        return respx.MockResponse(200, json={"transactions": TRANS[pid], "nextPageToken": None})

    return {
        "items": api.get(BASE_URL + "getItems").mock(side_effect=catalogo(ITEMS)),
        "metodos": api.get(BASE_URL + "getPaymentMethods").mock(side_effect=catalogo(METODOS)),
        "tx": api.post(TX_URL).mock(side_effect=transacciones),
    }


async def test_extras_un_hotel(registry, cloudbeds):
    out = json.loads(await server.extras_periodo("2026-11-15", "2026-11-16", hotel="Balta"))
    assert out["hotel"] == {"alias": "balta", "nombre": "Zentra Balta"}
    assert out["periodo"] == {"desde": "2026-11-15", "hasta": "2026-11-16", "dias": 2}
    assert out["moneda"] == "PEN"
    assert out["total"]["importe"] == 31.0
    assert out["por_rubro"] == {"Otros": {"importe": 25.0, "movimientos": 1, "unidades": 1.0},
                                "Minibar": {"importe": 6.0, "movimientos": 1, "unidades": 1.0}}
    filtros = json.loads(cloudbeds["tx"].calls.last.request.content)["filters"]
    assert filtros == {"and": [
        {"field": "service_date", "operator": "greater_than_or_equal", "value": "2026-11-15"},
        {"field": "service_date", "operator": "less_than_or_equal", "value": "2026-11-16"},
    ]}


async def test_catalogos_se_guardan_un_dia(registry, cloudbeds):
    await server.extras_periodo("2026-11-15", "2026-11-15", hotel="balta")
    await server.extras_periodo("2026-11-15", "2026-11-15", agrupar="dia", hotel="balta")
    await server.pagos_periodo("2026-11-15", "2026-11-15", hotel="balta")
    await server.pagos_periodo("2026-11-15", "2026-11-15", hotel="balta")
    assert cloudbeds["items"].call_count == 1 and cloudbeds["metodos"].call_count == 1
    assert cloudbeds["tx"].call_count == 4


async def test_pagos_un_hotel_sin_datos_personales(registry, cloudbeds):
    raw = await server.pagos_periodo("2026-11-15", "2026-11-15", hotel="balta")
    out = json.loads(raw)
    assert out["total"]["neto"] == 129.0 and out["por_medio"]["Yape"]["pagos"] == 1
    assert out["criterio_fecha"].startswith("día en que se registró")
    assert "Rosa" not in raw and "Quispe" not in raw
    filtros = json.loads(cloudbeds["tx"].calls.last.request.content)["filters"]["and"]
    assert filtros[0] == {"field": "transaction_datetime", "operator": "greater_than_or_equal", "value": "2026-11-15T05:00:00Z"}
    assert filtros[1] == {"field": "transaction_datetime", "operator": "less_than", "value": "2026-11-16T05:00:00Z"}


async def test_pagos_por_dia_contable_pide_margen(registry, cloudbeds):
    out = json.loads(await server.pagos_periodo("2026-11-15", "2026-11-15", fecha="contable", hotel="balta"))
    assert out["criterio_fecha"] == "día contable (cierre de caja)"
    filtros = json.loads(cloudbeds["tx"].calls.last.request.content)["filters"]["and"]
    assert filtros[0]["value"] == "2026-11-12T05:00:00Z" and filtros[1]["value"] == "2026-11-19T05:00:00Z"


async def test_resumen_financiero_un_hotel(registry, cloudbeds):
    out = json.loads(await server.resumen_financiero("2026-11-15", "2026-11-15", hotel="balta"))
    assert out["cargos"]["total"] == 131.0
    assert out["cargos"]["por_tipo"]["Habitación"]["por_codigo"] == {"1000": 100.0}
    assert out["pagos_aplicados"]["neto"] == 129.0 and out["cargos_menos_pagos"] == 2.0


@pytest.mark.parametrize("tool", [server.extras_periodo, server.pagos_periodo, server.resumen_financiero])
async def test_red_suma_hoteles_y_avisa_el_que_falta(registry, cloudbeds, tool):
    out = json.loads(await tool("2026-11-15", "2026-11-15", hotel="la red"))
    assert out["red"]["hoteles_incluidos"] == ["Zentra Balta", "Zentra Plaza"]
    assert "Zentra San José" in out["advertencia"]
    assert set(out["hoteles"]) == {"balta", "plaza"}
    assert out["total_red"]["moneda"] == "PEN"


async def test_red_totales(registry, cloudbeds):
    ext = json.loads(await server.extras_periodo("2026-11-15", "2026-11-15", hotel="red"))["total_red"]
    assert ext["total"]["importe"] == 81.0 and ext["por_rubro"]["Otros"]["importe"] == 75.0
    assert ext["periodo"]["dias"] == 1
    pag = json.loads(await server.pagos_periodo("2026-11-15", "2026-11-15", hotel="red"))["total_red"]
    assert pag["total"]["neto"] == 169.0 and list(pag["por_medio"]) == ["Yape", "Efectivo"]


async def test_red_con_un_hotel_caido(registry, api):
    api.get(BASE_URL + "getItems").respond(200, json={"success": True, "data": ITEMS})

    def transacciones(request):
        if request.headers["X-Property-ID"] == "222":
            return respx.MockResponse(403, json={"message": "Forbidden"})
        return respx.MockResponse(200, json={"transactions": TRANS["111"]})

    api.post(TX_URL).mock(side_effect=transacciones)
    out = json.loads(await server.extras_periodo("2026-11-15", "2026-11-15", hotel="red"))
    assert "read:payment" in out["hoteles"]["plaza"]["error"]
    assert out["total_red"]["total"]["importe"] == 31.0
    assert "Zentra Plaza (error al consultar)" in out["advertencia"]


@pytest.mark.parametrize("tool", [server.extras_periodo, server.pagos_periodo, server.resumen_financiero])
async def test_periodo_invalido_no_consulta(registry, api, tool):
    route = api.route()
    out = await tool("2026-11-20", "2026-11-10", hotel="balta")
    assert "inválido" in out and route.call_count == 0
    out = await tool("2025-01-01", "2026-11-10", hotel="balta")
    assert "366 días" in out


async def test_sin_hotel_pide_elegir(registry, api):
    route = api.route()
    out = await server.pagos_periodo("2026-11-15", "2026-11-15")
    assert out.startswith("Indica de qué hotel") and route.call_count == 0


async def test_herramientas_registradas_como_solo_lectura():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    for name in ("extras_periodo", "pagos_periodo", "resumen_financiero"):
        assert tools[name].annotations.readOnlyHint is True
        assert "hotel" in tools[name].inputSchema["properties"]
    assert tools["pagos_periodo"].inputSchema["properties"]["fecha"]["enum"] == ["pago", "contable"]
