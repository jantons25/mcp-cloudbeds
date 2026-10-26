import json
from dataclasses import replace
from datetime import datetime

import pytest
import respx

from cloudbeds_mcp import server
from cloudbeds_mcp.client import BASE_URL, CloudbedsClient

TOOLS = {"estado_hotel", "buscar_reservas", "detalle_reserva"}

RESERVA_LISTA = {
    "reservationID": "R100",
    "guestName": "Rosa Quispe",
    "startDate": "2026-10-26",
    "endDate": "2026-10-28",
    "status": "confirmed",
    "adults": "2",
    "children": "0",
    "balance": 150.5,
    "sourceName": "Booking.com",
    "rooms": [
        {"roomTypeName": "Doble", "roomName": "201"},
        {"roomTypeName": "Doble", "roomName": None},
    ],
}

RESERVA_DETALLE = {
    "reservationID": "R100",
    "status": "checked_in",
    "guestName": "Rosa Quispe",
    "guestEmail": "rosa.quispe@gmail.com",
    "startDate": "2026-10-26",
    "endDate": "2026-10-28",
    "source": "Booking.com",
    "total": 420,
    "balance": 0,
    "cardsOnFile": [{"cardID": "c1", "cardNumber": "4242", "cardType": "visa"}],
    "assigned": [
        {"roomTypeName": "Doble", "roomName": "201", "startDate": "2026-10-26", "endDate": "2026-10-28",
         "adults": "2", "children": "0", "roomTotal": "420.00"}
    ],
    "unassigned": [],
    "guestList": {
        "g1": {
            "guestFirstName": "Rosa", "guestLastName": "Quispe", "isMainGuest": True,
            "guestEmail": "rosa.quispe@gmail.com", "guestCellPhone": "+51 987 654 321",
            "guestDocumentType": "dni", "guestDocumentNumber": "45678912",
            "guestAddress": "Av. Siempre Viva 123", "guestBirthdate": "1990-01-01", "guestCountry": "PE",
        }
    },
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


async def test_herramientas_registradas_y_solo_lectura():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    assert TOOLS <= set(tools)
    for name in TOOLS:
        assert tools[name].annotations.readOnlyHint is True
        assert tools[name].annotations.destructiveHint is False
        assert tools[name].description


async def test_estado_hotel_usa_hoy_en_lima(client, api):
    route = api.get("getDashboard").respond(200, json={
        "success": True,
        # tipos tal como los devuelve la API real: arrivals/departures como texto, % con decimales
        "data": {"roomsOccupied": 30, "percentageOccupied": 40.91, "arrivals": "12", "departures": "8", "inHouse": 22},
    })
    out = json.loads(await server.estado_hotel())
    hoy = datetime.now(client.settings.tz).date().isoformat()
    params = route.calls.last.request.url.params
    assert params["date"] == hoy
    assert params["propertyID"] == "12345"
    assert out == {"fecha": hoy, "habitaciones_ocupadas": 30, "porcentaje_ocupacion": 40.91,
                   "llegadas_pendientes": 12, "salidas_pendientes": 8, "in_house": 22}


async def test_estado_hotel_fecha_explicita(client, api):
    route = api.get("getDashboard").respond(200, json={"success": True, "data": {"arrivals": 1}})
    out = json.loads(await server.estado_hotel("2026-12-31"))
    assert route.calls.last.request.url.params["date"] == "2026-12-31"
    assert out["llegadas_pendientes"] == 1


async def test_estado_hotel_error_en_espanol(client, api):
    api.get("getDashboard").respond(200, json={"success": False, "message": "User who approved this connection is not active anymore"})
    out = await server.estado_hotel()
    assert out.startswith("No se pudo consultar Cloudbeds")
    assert "desactivado" in out
    assert "Traceback" not in out


async def test_estado_hotel_scope_faltante(client, api):
    api.get("getDashboard").respond(403, json={"success": False, "message": "Forbidden"})
    out = await server.estado_hotel()
    assert "read:dashboard" in out


async def test_buscar_reservas_filtros_y_formato(client, api):
    route = api.get("getReservations").respond(200, json={"success": True, "data": [RESERVA_LISTA], "total": 1})
    out = json.loads(await server.buscar_reservas(
        estado="confirmed", checkin_desde="2026-10-26", checkin_hasta="2026-10-26", apellido=" Quispe "
    ))
    params = route.calls.last.request.url.params
    assert params["status"] == "confirmed"
    assert params["checkInFrom"] == "2026-10-26" and params["checkInTo"] == "2026-10-26"
    assert params["lastName"] == "Quispe"
    assert params["includeAllRooms"] == "1"
    assert "checkOutFrom" not in params
    assert out["cantidad"] == 1 and out["truncado"] is False
    r = out["reservas"][0]
    assert r == {
        "id": "R100", "huesped": "Rosa Quispe", "checkin": "2026-10-26", "checkout": "2026-10-28",
        "estado": "confirmada", "tipo_habitacion": ["Doble"], "habitacion": ["201"],
        "fuente": "Booking.com", "adultos": 2, "ninos": 0, "saldo": 150.5,
    }


async def test_buscar_reservas_respeta_max_resultados(client, api):
    data = [dict(RESERVA_LISTA, reservationID=str(i)) for i in range(100)]
    api.get("getReservations").respond(200, json={"success": True, "data": data, "total": 400})
    out = json.loads(await server.buscar_reservas(max_resultados=10))
    assert out["cantidad"] == 10
    assert out["truncado"] is True
    assert "nota" in out


async def test_buscar_reservas_rango_invalido_no_llama_api(client, api):
    route = api.route()
    out = await server.buscar_reservas(checkin_desde="2026-11-02", checkin_hasta="2026-11-01")
    assert "inválido" in out
    assert route.call_count == 0


async def test_detalle_reserva_enmascara_pii(client, api):
    route = api.get("getReservation").respond(200, json={"success": True, "data": RESERVA_DETALLE})
    raw = await server.detalle_reserva("R100")
    out = json.loads(raw)
    assert route.calls.last.request.url.params["reservationID"] == "R100"
    assert out["estado"] == "con check-in (en casa)"
    assert out["total"] == 420.0 and out["saldo"] == 0.0
    assert out["email_principal"] == "r***@g***.com"
    g = out["huespedes"][0]
    assert g["telefono"] == "***321"
    assert g["documento"] == "dni ***12"
    # Nunca se exponen tarjetas, direcciones ni fechas de nacimiento
    for secreto in ("rosa.quispe@gmail.com", "45678912", "987 654", "4242", "Siempre Viva", "1990-01-01"):
        assert secreto not in raw


async def test_detalle_reserva_show_pii_true(client, api):
    client.settings = replace(client.settings, show_pii=True)
    api.get("getReservation").respond(200, json={"success": True, "data": RESERVA_DETALLE})
    out = json.loads(await server.detalle_reserva("R100"))
    assert out["email_principal"] == "rosa.quispe@gmail.com"
    assert out["huespedes"][0]["documento"] == "dni 45678912"
    assert "4242" not in json.dumps(out)  # tarjetas nunca


@pytest.mark.parametrize(
    ("fecha", "esperado"),
    [("26/10/2026", "no tiene el formato YYYY-MM-DD"), ("2026-02-30", "no existe en el calendario")],
)
async def test_fecha_invalida_mensaje_en_espanol(client, api, fecha, esperado):
    route = api.route()
    out = await server.estado_hotel(fecha)
    assert esperado in out
    assert route.call_count == 0


async def test_fecha_invalida_en_buscar_reservas(client, api):
    route = api.route()
    out = await server.buscar_reservas(checkout_hasta="mañana")
    assert "check-out hasta" in out and "YYYY-MM-DD" in out
    assert route.call_count == 0


async def test_llamada_via_mcp_con_fecha_texto(client, api):
    api.get("getDashboard").respond(200, json={"success": True, "data": {"arrivals": 4}})
    result = await server.mcp.call_tool("estado_hotel", {"fecha": "2026-10-26"})
    content = result[0] if isinstance(result, tuple) else result
    assert json.loads(content[0].text)["llegadas_pendientes"] == 4


async def test_sin_api_key_mensaje_claro(monkeypatch):
    server.set_client(None)

    def boom():
        from cloudbeds_mcp.errors import ConfigError
        raise ConfigError("Falta CLOUDBEDS_API_KEY.")

    monkeypatch.setattr(server, "load_settings", boom)
    out = await server.estado_hotel()
    assert "falta configuración" in out and "CLOUDBEDS_API_KEY" in out
