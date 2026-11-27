"""Búsqueda de transacciones en la API contable: POST que solo lee, con su lista blanca."""

import json

import pytest
import respx

from cloudbeds_mcp import client as client_mod
from cloudbeds_mcp.client import ACCOUNTING_URL, ALLOWED_ENDPOINTS, ALLOWED_QUERIES, CloudbedsClient
from cloudbeds_mcp.errors import AuthError, CloudbedsError

from .conftest import FAKE_KEY

URL = ACCOUNTING_URL + "transactions"
FILTRO = {"and": [{"field": "service_date", "operator": "greater_than_or_equal", "value": "2026-11-15"}]}


@pytest.fixture
async def client(settings, fake_sleep):
    c = CloudbedsClient(settings, rate=10_000, sleep=fake_sleep)
    yield c
    await c.aclose()


@pytest.fixture
def api():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


async def test_envia_bearer_property_y_filtros(client, api):
    route = api.post(URL).respond(200, json={"transactions": [{"id": "1"}], "nextPageToken": None})
    out = await client.search_transactions(FILTRO)
    assert out == {"data": [{"id": "1"}], "truncado": False}
    req = route.calls.last.request
    assert req.headers["Authorization"] == f"Bearer {FAKE_KEY}"
    assert req.headers["X-Property-ID"] == "12345"
    assert json.loads(req.content) == {"filters": FILTRO, "limit": 1100}


async def test_recorre_paginas_con_page_token(client, api):
    pages = [
        {"transactions": [{"id": "1"}, {"id": "2"}], "nextPageToken": "abc"},
        {"transactions": [{"id": "3"}], "nextPageToken": None},
    ]
    route = api.post(URL).mock(side_effect=[respx.MockResponse(200, json=p) for p in pages])
    out = await client.search_transactions(FILTRO)
    assert [t["id"] for t in out["data"]] == ["1", "2", "3"] and out["truncado"] is False
    assert "pageToken" not in json.loads(route.calls[0].request.content)
    assert json.loads(route.calls[1].request.content)["pageToken"] == "abc"


async def test_tope_de_resultados(client, api):
    api.post(URL).respond(200, json={"transactions": [{"id": str(i)} for i in range(3)], "nextPageToken": "otra"})
    out = await client.search_transactions(FILTRO, max_results=2)
    assert len(out["data"]) == 2 and out["truncado"] is True


async def test_error_400_con_error_details(client, api):
    api.post(URL).respond(400, json={"errorCode": "INVALID_REQUEST", "errorDetails": "Filters cannot be empty."})
    with pytest.raises(CloudbedsError, match="Filters cannot be empty"):
        await client.search_transactions(FILTRO)


async def test_403_indica_el_scope_read_payment(client, api):
    api.post(URL).respond(403, json={"message": "Forbidden"})
    with pytest.raises(CloudbedsError, match="read:payment"):
        await client.search_transactions(FILTRO)


async def test_401_no_reintenta(client, api, fake_sleep):
    route = api.post(URL).respond(401, json={})
    with pytest.raises(AuthError):
        await client.search_transactions(FILTRO)
    assert route.call_count == 1 and fake_sleep.calls == []


async def test_503_reintenta(client, api, fake_sleep):
    route = api.post(URL).mock(side_effect=[respx.MockResponse(503), respx.MockResponse(200, json={"transactions": []})])
    assert (await client.search_transactions(FILTRO))["data"] == []
    assert route.call_count == 2


async def test_respuesta_sin_lista_de_transacciones(client, api):
    api.post(URL).respond(200, json={"data": []})
    with pytest.raises(CloudbedsError, match="transactions"):
        await client.search_transactions(FILTRO)


async def test_sin_property_id_no_consulta(settings, fake_sleep, api):
    from dataclasses import replace

    route = api.route()
    async with CloudbedsClient(replace(settings, property_id=None), rate=10_000, sleep=fake_sleep) as c:
        with pytest.raises(CloudbedsError, match="propertyID"):
            await c.search_transactions(FILTRO)
    assert route.call_count == 0


def test_lista_blanca_de_consultas_y_catalogos():
    assert ALLOWED_QUERIES == {"transactions": "read:payment"}
    assert ALLOWED_ENDPOINTS["getItems"] == "read:item"
    assert ALLOWED_ENDPOINTS["getPaymentMethods"] == "read:payment"
    assert client_mod.ACCOUNTING_URL.startswith("https://")


def test_solo_hay_una_forma_de_hacer_post():
    # Métodos públicos: lectura (get, get_all, search_transactions con URL fija) y write, que solo
    # acepta ALLOWED_WRITES (probado en test_client.py).
    publicos = {n for n in dir(CloudbedsClient) if not n.startswith("_")}
    assert publicos == {"aclose", "get", "get_all", "search_transactions", "write"}
