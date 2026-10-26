import logging

import httpx
import pytest
import respx

from cloudbeds_mcp.client import BASE_URL, CloudbedsClient, RateLimiter
from cloudbeds_mcp.errors import AuthError, CloudbedsError, NotAllowedError, RateLimitError

from .conftest import FAKE_KEY


@pytest.fixture
async def client(settings, fake_sleep):
    # rate alto para que el limitador no intervenga en estos tests
    c = CloudbedsClient(settings, rate=10_000, sleep=fake_sleep)
    yield c
    await c.aclose()


@pytest.fixture
def api():
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as mock:
        yield mock


async def test_get_ok_envia_headers(client, api):
    route = api.get("getHotels").respond(200, json={"success": True, "data": [{"propertyID": "12345"}]})
    body = await client.get("getHotels")
    assert body["data"][0]["propertyID"] == "12345"
    req = route.calls.last.request
    assert req.headers["x-api-key"] == FAKE_KEY
    assert req.headers["X-PROPERTY-ID"] == "12345"
    assert req.headers["Accept"] == "application/json"
    assert req.method == "GET"


async def test_respuesta_sin_campo_success_es_valida(client, api):
    api.get("userinfo").respond(200, json={"user_id": "1", "first_name": "Ana"})
    body = await client.get("userinfo")
    assert body["first_name"] == "Ana"


async def test_booleanos_y_none_en_parametros(client, api):
    route = api.get("getReservations").respond(200, json={"success": True, "data": []})
    await client.get("getReservations", {"includeGuestsDetails": True, "includeAllRooms": False, "status": None})
    params = route.calls.last.request.url.params
    # Cloudbeds toma "false" como verdadero: los booleanos se envían como "1"/"0"
    assert params["includeGuestsDetails"] == "1"
    assert params["includeAllRooms"] == "0"
    assert "false" not in str(route.calls.last.request.url)
    assert "status" not in params


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("User who approved this connection is not active anymore", "fue desactivado"),
        ("None of the included property id's match with the ones allowed", "no tiene acceso a esa propiedad"),
        ("The property(ies) you are accessing have an invalid status", "no está activa"),
        ("Algo raro", "Cloudbeds rechazó la consulta: Algo raro"),
    ],
)
async def test_success_false_traducido(client, api, message, expected):
    api.get("getHotels").respond(200, json={"success": False, "message": message})
    with pytest.raises(CloudbedsError) as exc:
        await client.get("getHotels")
    assert expected in str(exc.value)


async def test_401_no_reintenta(client, api, fake_sleep):
    route = api.get("getHotels").respond(401, json={"error": "access_denied"})
    with pytest.raises(AuthError):
        await client.get("getHotels")
    assert route.call_count == 1
    assert fake_sleep.calls == []


async def test_403_indica_scope(client, api):
    api.get("getHousekeepingStatus").respond(403, json={"success": False, "message": "Forbidden"})
    with pytest.raises(CloudbedsError) as exc:
        await client.get("getHousekeepingStatus")
    assert "read:housekeeping" in str(exc.value)


async def test_400_no_reintenta(client, api):
    route = api.get("getReservation").respond(400, json={"success": False, "message": "Invalid reservationID"})
    with pytest.raises(CloudbedsError) as exc:
        await client.get("getReservation", {"reservationID": "x"})
    assert route.call_count == 1
    assert "HTTP 400" in str(exc.value)


async def test_429_respeta_retry_after(client, api, fake_sleep):
    route = api.get("getHotels")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, json={"success": True, "data": []}),
    ]
    await client.get("getHotels")
    assert route.call_count == 2
    assert len(fake_sleep.calls) == 1
    assert 2.0 <= fake_sleep.calls[0] <= 2.3


async def test_429_sin_retry_after_usa_1s(client, api, fake_sleep):
    route = api.get("getHotels")
    route.side_effect = [httpx.Response(429), httpx.Response(200, json={"success": True})]
    await client.get("getHotels")
    assert 1.0 <= fake_sleep.calls[0] <= 1.3


async def test_429_agota_reintentos(client, api):
    route = api.get("getHotels").respond(429, headers={"Retry-After": "0"})
    with pytest.raises(RateLimitError):
        await client.get("getHotels")
    assert route.call_count == 4  # 1 intento + 3 reintentos


async def test_503_reintenta_y_se_recupera(client, api, fake_sleep):
    route = api.get("getDashboard")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, json={"success": True, "data": {"arrivals": 3}}),
    ]
    body = await client.get("getDashboard")
    assert body["data"]["arrivals"] == 3
    assert fake_sleep.calls == [0.5]


async def test_5xx_backoff_exponencial_y_falla(client, api, fake_sleep):
    route = api.get("getDashboard").respond(502)
    with pytest.raises(CloudbedsError) as exc:
        await client.get("getDashboard")
    assert route.call_count == 4
    assert fake_sleep.calls == [0.5, 1.0, 2.0]
    assert "HTTP 502" in str(exc.value)


async def test_timeout_reintenta(client, api, fake_sleep):
    route = api.get("getHotels")
    route.side_effect = [httpx.ReadTimeout("lento"), httpx.Response(200, json={"success": True})]
    await client.get("getHotels")
    assert fake_sleep.calls == [0.5]


async def test_respuesta_no_json(client, api):
    api.get("getHotels").respond(200, text="<html>error</html>")
    with pytest.raises(CloudbedsError, match="no es JSON"):
        await client.get("getHotels")


async def test_request_id_en_el_error(client, api):
    api.get("getHotels").respond(200, json={"success": False, "message": "x"}, headers={"X-Request-ID": "req-42"})
    with pytest.raises(CloudbedsError) as exc:
        await client.get("getHotels")
    assert exc.value.request_id == "req-42"
    assert "req-42" in str(exc.value)


async def test_paginacion_dos_paginas(client, api):
    page1 = [{"reservationID": str(i)} for i in range(100)]
    page2 = [{"reservationID": str(i)} for i in range(100, 150)]
    route = api.get("getReservations")
    route.side_effect = [
        httpx.Response(200, json={"success": True, "data": page1, "count": 100, "total": 150}),
        httpx.Response(200, json={"success": True, "data": page2, "count": 50, "total": 150}),
    ]
    result = await client.get_all("getReservations", {"status": "confirmed"})
    assert len(result["data"]) == 150
    assert result["total"] == 150
    assert result["truncado"] is False
    pages = [c.request.url.params["pageNumber"] for c in route.calls]
    assert pages == ["1", "2"]
    assert route.calls[0].request.url.params["pageSize"] == "100"
    assert route.calls[0].request.url.params["status"] == "confirmed"


async def test_paginacion_truncada_por_max_results(client, api):
    page = [{"reservationID": str(i)} for i in range(100)]
    route = api.get("getReservations")
    route.side_effect = [
        httpx.Response(200, json={"success": True, "data": page, "total": 300}),
        httpx.Response(200, json={"success": True, "data": page, "total": 300}),
    ]
    result = await client.get_all("getReservations", max_results=120)
    assert len(result["data"]) == 120
    assert result["truncado"] is True
    assert route.call_count == 2


async def test_paginacion_una_pagina_incompleta(client, api):
    route = api.get("getHotels").respond(200, json={"success": True, "data": [{"propertyID": "1"}]})
    result = await client.get_all("getHotels")
    assert result["data"] == [{"propertyID": "1"}]
    assert result["truncado"] is False
    assert route.call_count == 1


async def test_endpoint_fuera_de_lista_blanca(client, api):
    route = api.route()  # cualquier petición
    for endpoint in ("postReservation", "putReservation", "deleteGuest", "getPayments"):
        with pytest.raises(NotAllowedError):
            await client.get(endpoint)
    assert route.call_count == 0


def test_no_existen_metodos_de_escritura(settings):
    for name in ("post", "put", "patch", "delete"):
        assert not hasattr(CloudbedsClient, name)


def test_https_obligatorio(settings):
    with pytest.raises(ValueError):
        CloudbedsClient(settings, base_url="http://api.cloudbeds.com/api/v1.3/")


async def test_logs_sin_key_ni_parametros(client, api, caplog):
    api.get("getReservations").respond(
        200, json={"success": True, "data": []}, headers={"X-Request-ID": "req-7"}
    )
    with caplog.at_level(logging.DEBUG):
        await client.get("getReservations", {"lastName": "Quispe", "firstName": "Rosa"})
    text = caplog.text
    assert FAKE_KEY not in text
    assert "Quispe" not in text and "Rosa" not in text
    assert "endpoint=getReservations" in text
    assert "status=200" in text and "success=True" in text and "request_id=req-7" in text


async def test_rate_limiter_espacia_peticiones():
    now = [0.0]
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(4, clock=lambda: now[0], sleep=sleep)
    for _ in range(5):
        await limiter.acquire()
    assert waits == pytest.approx([0.25, 0.25, 0.25, 0.25])
    # 5 peticiones ocupan 1.0 s: nunca más de 4 por segundo
    assert now[0] == pytest.approx(1.0)


def _page_responder(total, size=100):
    def handler(request):
        n = int(request.url.params["pageNumber"])
        start = (n - 1) * size
        data = [{"id": i} for i in range(start, min(start + size, total))]
        return httpx.Response(200, json={"success": True, "data": data, "total": total})
    return handler


async def test_paginacion_concurrente_conserva_orden(client, api):
    route = api.get("getReservationsWithRateDetails")
    route.side_effect = _page_responder(350)
    result = await client.get_all("getReservationsWithRateDetails", max_results=5000, concurrency=4)
    assert [x["id"] for x in result["data"]] == list(range(350))
    assert result["truncado"] is False
    assert sorted(int(c.request.url.params["pageNumber"]) for c in route.calls) == [1, 2, 3, 4]


async def test_paginacion_concurrente_respeta_max_results(client, api):
    route = api.get("getReservationsWithRateDetails")
    route.side_effect = _page_responder(1000)
    result = await client.get_all("getReservationsWithRateDetails", max_results=250, concurrency=4)
    assert len(result["data"]) == 250 and result["truncado"] is True
    assert route.call_count == 3  # no pide páginas más allá del tope


async def test_paginacion_concurrente_una_sola_pagina(client, api):
    route = api.get("getReservationsWithRateDetails")
    route.side_effect = _page_responder(40)
    result = await client.get_all("getReservationsWithRateDetails", concurrency=4)
    assert len(result["data"]) == 40 and route.call_count == 1
