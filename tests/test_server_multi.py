"""Servidor con varios hoteles (fase 2): selección por nombre, aislamiento de keys y tz por hotel."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import respx

from cloudbeds_mcp import config, server
from cloudbeds_mcp.client import BASE_URL, CloudbedsClient
from cloudbeds_mcp.config import Catalog, Hotel, HotelEntry, HotelsConfig, Settings, keyring_user
from cloudbeds_mcp.hotels import HotelRegistry

# Zonas con 25 h de diferencia: "hoy" nunca coincide entre Balta y Plaza.
TZ_BALTA = ZoneInfo("Pacific/Pago_Pago")  # UTC-11
TZ_PLAZA = ZoneInfo("Pacific/Kiritimati")  # UTC+14

KEYS = {"balta": "cbat_KEY_BALTA", "plaza": "cbat_KEY_PLAZA"}


def _settings(alias, nombre, pid, tz):
    return Settings(
        api_key=KEYS[alias], property_id=pid, show_pii=False, tz=tz, max_results=500,
        key_source="keyring", hotel_alias=alias, hotel_name=nombre, currency="PEN",
    )


@pytest.fixture
async def registry(fake_sleep):
    hoteles = (
        Hotel.from_settings(_settings("balta", "Zentra Balta", "111", TZ_BALTA)),
        Hotel.from_settings(_settings("plaza", "Zentra Plaza", "222", TZ_PLAZA)),
        Hotel(alias="san_jose", nombre="Zentra San José", property_id="333", tz=ZoneInfo("America/Lima"),
              moneda="PEN", motivo="No hay API key de Zentra San José en esta PC."),
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


def ok(data=None, total=None):
    body = {"success": True, "data": data if data is not None else []}
    if total is not None:
        body["total"] = total
    return body


# Las 13 herramientas con los argumentos mínimos para llamarlas.
TOOLS = [
    (server.estado_hotel, {}),
    (server.buscar_reservas, {}),
    (server.detalle_reserva, {"reservation_id": "R1"}),
    (server.disponibilidad, {}),
    (server.tipos_habitacion, {}),
    (server.habitaciones, {}),
    (server.asignaciones_del_dia, {}),
    (server.estado_housekeeping, {}),
    (server.fuentes_reserva, {}),
    (server.planes_tarifa, {}),
    (server.resumen_dia, {}),
    (server.resumen_periodo, {}),
    (server.ingresos_periodo, {}),
]
TOOL_IDS = [t.__name__ for t, _ in TOOLS]
# Herramientas que aceptan hotel="red" (fase 4); el resto son de un solo hotel.
RED_TOOLS = {"estado_hotel", "buscar_reservas", "resumen_dia", "resumen_periodo", "ingresos_periodo"}
UNO = [(t, k) for t, k in TOOLS if t.__name__ not in RED_TOOLS]
UNO_IDS = [t.__name__ for t, _ in UNO]


@pytest.mark.parametrize(("tool", "kwargs"), TOOLS, ids=TOOL_IDS)
async def test_sin_hotel_con_varios_pide_elegir_sin_llamar_api(registry, api, tool, kwargs):
    route = api.route()
    out = await tool(**kwargs)
    assert out.startswith("Indica de qué hotel")
    assert "Zentra Balta (balta)" in out and "Zentra Plaza (plaza)" in out
    assert route.call_count == 0


@pytest.mark.parametrize(("tool", "kwargs"), UNO, ids=UNO_IDS)
async def test_red_en_consulta_de_un_hotel(registry, api, tool, kwargs):
    route = api.route()
    out = await tool(**kwargs, hotel="la red")
    assert "Esta consulta es de un solo hotel" in out
    assert route.call_count == 0


@pytest.mark.parametrize(("tool", "kwargs"), TOOLS, ids=TOOL_IDS)
async def test_hotel_sin_key(registry, api, tool, kwargs):
    route = api.route()
    out = await tool(**kwargs, hotel="San José")
    assert out == "No hay API key de Zentra San José en esta PC."
    assert route.call_count == 0


@pytest.mark.parametrize(("texto", "alias", "pid"), [("Plaza", "plaza", "222"), ("zentra balta", "balta", "111")])
async def test_cada_hotel_usa_su_key_y_property_id(registry, api, texto, alias, pid):
    route = api.get("getDashboard").respond(200, json=ok({"roomsOccupied": 3}))
    out = json.loads(await server.estado_hotel(hotel=texto))
    req = route.calls.last.request
    assert req.headers["x-api-key"] == KEYS[alias]
    assert req.headers["X-PROPERTY-ID"] == pid and req.url.params["propertyID"] == pid
    assert list(out)[0] == "hotel"  # la etiqueta va primero
    assert out["hotel"]["alias"] == alias


async def test_todas_las_herramientas_etiquetan_el_hotel(registry, api):
    for endpoint in ("getDashboard", "getReservation", "getAvailableRoomTypes", "getReservationAssignments",
                     "getSources", "getRatePlans"):
        api.get(endpoint).respond(200, json=ok({} if endpoint in ("getDashboard", "getReservation") else []))
    for endpoint in ("getReservations", "getRoomTypes", "getRooms", "getHousekeepingStatus",
                     "getReservationsWithRateDetails"):
        api.get(endpoint).respond(200, json=ok([], total=0))
    for tool, kwargs in TOOLS:
        out = json.loads(await tool(**kwargs, hotel="plaza"))
        assert out["hotel"] == {"alias": "plaza", "nombre": "Zentra Plaza"}, tool.__name__
    sent_keys = {c.request.headers["x-api-key"] for c in api.calls}
    assert sent_keys == {KEYS["plaza"]}


@pytest.mark.parametrize(("texto", "tz"), [("balta", TZ_BALTA), ("plaza", TZ_PLAZA)])
async def test_hoy_segun_la_zona_del_hotel(registry, api, texto, tz):
    route = api.get("getDashboard").respond(200, json=ok({}))
    out = json.loads(await server.estado_hotel(hotel=texto))
    hoy = datetime.now(tz).date().isoformat()
    assert route.calls.last.request.url.params["date"] == hoy and out["fecha"] == hoy


async def test_periodo_por_defecto_segun_la_zona_del_hotel(registry, api):
    route = api.get("getReservations").respond(200, json=ok([], total=0))
    out = json.loads(await server.resumen_periodo(hotel="plaza"))
    inicio = datetime.now(TZ_PLAZA).date().replace(day=1).isoformat()
    assert out["periodo"]["desde"] == inicio
    assert route.calls.last.request.url.params["checkInFrom"] == inicio


async def test_ingresos_usa_la_moneda_de_config_si_no_hay_reservas(registry, api):
    api.get("getReservationsWithRateDetails").respond(200, json=ok([], total=0))
    api.get("getRoomTypes").respond(200, json=ok([{"roomTypeUnits": 10}], total=1))
    out = json.loads(await server.ingresos_periodo("2026-10-01", "2026-10-31", hotel="balta"))
    assert out["moneda"] == "PEN"


async def test_ninguna_key_aparece_en_logs_ni_en_respuestas(registry, api, caplog):
    caplog.set_level("DEBUG")
    api.get("getDashboard").respond(401, json={"success": False, "message": "bad key"})
    outs = [await server.estado_hotel(hotel=h) for h in ("balta", "plaza", "san jose", None, "red")]
    outs.append(await server.hoteles())
    texto = caplog.text + "".join(outs)
    assert all(k not in texto for k in KEYS.values())


# ---------- herramienta hoteles ----------

async def test_hoteles_lista_sin_llamar_api(registry, api):
    route = api.route()
    out = json.loads(await server.hoteles())
    assert out["cantidad"] == 3
    assert [h["alias"] for h in out["hoteles"]] == ["balta", "plaza", "san_jose"]
    assert [h["disponible"] for h in out["hoteles"]] == [True, True, False]
    assert out["hoteles"][2]["motivo"].startswith("No hay API key")
    assert "pregúntale" in out["nota"]
    assert route.call_count == 0


async def test_hoteles_verificar(registry, api):
    def details(request):
        pid = request.url.params["propertyID"]
        if pid == "222":
            return respx.MockResponse(401, json={"success": False})
        return respx.MockResponse(200, json=ok({"propertyName": "Zentra Balta", "propertyCurrency": {"currencyCode": "USD"}}))

    route = api.get("getHotelDetails").mock(side_effect=details)
    out = json.loads(await server.hoteles(verificar=True))
    balta, plaza, sj = out["hoteles"]
    assert balta["verificado"] is True and balta["nombre_en_cloudbeds"] == "Zentra Balta"
    assert balta["moneda"] == "USD" and "PEN" in balta["advertencia"]
    assert plaza["verificado"] is False and "inválida" in plaza["error"]
    assert "verificado" not in sj  # sin key no se consulta
    assert route.call_count == 2


async def test_hoteles_legacy_sin_etiqueta_ni_nota(settings, api, fake_sleep):
    c = CloudbedsClient(settings, rate=10_000, sleep=fake_sleep)
    server.set_client(c)
    try:
        out = json.loads(await server.hoteles())
    finally:
        server.set_client(None)
        await c.aclose()
    assert out["cantidad"] == 1 and out["hoteles"][0]["alias"] == "principal"
    assert "nota" not in out


async def test_hoteles_con_error_de_config(monkeypatch):
    server.set_registry(None)

    def boom():
        raise config.ConfigError("Ningún hotel de hoteles.json tiene API key en esta PC.")

    monkeypatch.setattr(server, "_load_registry", boom)
    assert "falta configuración" in await server.hoteles()


@pytest.mark.parametrize(("value", "esperado"), [({"currencyCode": "PEN"}, "PEN"), ([{"currencyCode": "USD"}], "USD"), ("EUR", "EUR"), ([], None), (None, None)])
def test_currency_code(value, esperado):
    assert server._currency_code(value) == esperado


# ---------- registro de las herramientas ----------

async def test_todas_las_herramientas_tienen_parametro_hotel():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    assert "hoteles" in tools and tools["hoteles"].annotations.readOnlyHint is True
    for name in TOOL_IDS:
        props = tools[name].inputSchema["properties"]
        assert "hotel" in props, name
        assert props["hotel"]["description"], name
        assert "hotel" not in tools[name].inputSchema.get("required", []), name


def test_instrucciones_con_varios_hoteles():
    cat = Catalog(hoteles=(HotelEntry("balta", "Zentra Balta", "1"), HotelEntry("plaza", "Zentra Plaza", "2")))
    texto = server._instructions(cat)
    assert "Zentra Balta ('balta')" in texto and "PREGÚNTALE" in texto and "la red" in texto
    assert "hora de Lima" not in texto
    assert "Hay" not in server._instructions(None)


# ---------- carga real desde hoteles.json ----------

async def test_carga_registro_desde_hoteles_json(monkeypatch, tmp_path, memory_keyring, api):
    for var in ("CLOUDBEDS_API_KEY", "CLOUDBEDS_PROPERTY_ID", "CLOUDBEDS_TZ", "CLOUDBEDS_USE_KEYRING"):
        monkeypatch.delenv(var, raising=False)
    path = tmp_path / "hoteles.json"
    path.write_text(json.dumps({"hoteles": [
        {"alias": "balta", "nombre": "Zentra Balta", "property_id": "111"},
        {"alias": "san_jose", "nombre": "Zentra San José", "property_id": "333"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(config, "HOTELES_PATH", path)
    monkeypatch.setattr(config, "ENV_PATH", tmp_path / ".env")  # no leer el .env real
    memory_keyring.set_password(config.KEYRING_SERVICE, keyring_user("san_jose"), "cbat_KEY_SJ")
    route = api.get("getDashboard").respond(200, json=ok({}))
    server.set_registry(None)
    try:
        out = json.loads(await server.estado_hotel(hotel="san jose"))
        assert "No hay API key de Zentra Balta" in await server.estado_hotel(hotel="Balta")
    finally:
        await server._get_registry().aclose()
        server.set_registry(None)
    assert out["hotel"]["nombre"] == "Zentra San José"
    assert route.calls.last.request.headers["x-api-key"] == "cbat_KEY_SJ"


def test_catalogo_invalido_al_arrancar_no_tumba_el_servidor(monkeypatch, tmp_path, caplog):
    path = tmp_path / "hoteles.json"
    path.write_text("{roto", encoding="utf-8")
    monkeypatch.setattr(config, "HOTELES_PATH", path)
    assert server._catalog_at_import() is None
    assert "hoteles.json no es válido" in caplog.text


async def test_lifespan_cierra_el_registro(registry):
    clients = registry.clients("red")
    async with server._lifespan(server.mcp):
        pass
    assert all(c._http.is_closed for c in clients)
