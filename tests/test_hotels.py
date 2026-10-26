from dataclasses import replace
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from cloudbeds_mcp.client import BASE_URL, CloudbedsClient, RateLimiter
from cloudbeds_mcp.config import Hotel, HotelsConfig, Settings
from cloudbeds_mcp.errors import ConfigError, HotelError
from cloudbeds_mcp.hotels import (
    HotelRegistry,
    descripcion_desde_catalogo,
    normalizar,
    palabras_de_marca,
)

LIMA = ZoneInfo("America/Lima")


def settings(alias, nombre, pid, key):
    return Settings(
        api_key=key, property_id=pid, show_pii=False, tz=LIMA, max_results=500,
        key_source="keyring", hotel_alias=alias, hotel_name=nombre, currency="PEN",
    )


def hotel(alias, nombre, pid, key="cbat_x", otros=(), disponible=True):
    s = settings(alias, nombre, pid, key)
    if not disponible:
        return Hotel(alias=alias, nombre=nombre, property_id=pid, tz=LIMA, moneda="PEN", otros_nombres=otros,
                     motivo=f"No hay API key de {nombre} en esta PC.")
    return replace(Hotel.from_settings(s), otros_nombres=otros)


class FakeClient:
    def __init__(self, settings, *, limiter=None):
        self.settings = settings
        self.limiter = limiter
        self.closed = False

    async def aclose(self):
        self.closed = True


def zentra(**kw):
    hoteles = (
        hotel("balta", "Zentra Balta", "111", "cbat_b"),
        hotel("plaza", "Zentra Plaza", "222", "cbat_p"),
        hotel("san_jose", "Zentra San José", "333", "cbat_s"),
    )
    return HotelRegistry(HotelsConfig(hoteles=hoteles, modo="multi", **kw), client_factory=FakeClient)


# ---------- normalización ----------

def test_normalizar_quita_tildes_signos_y_palabras_vacias():
    assert normalizar("  Hotel  ZENTRA San José! ") == ("zentra", "san", "jose")
    assert normalizar("el de la Plaza", ignorar={"zentra"}) == ("plaza",)
    assert normalizar("san_jose") == ("san", "jose")


def test_palabras_de_marca():
    assert palabras_de_marca(["Zentra Balta", "Zentra Plaza", "Zentra San José"]) == {"zentra"}
    assert palabras_de_marca(["Zentra Balta"]) == set()  # un solo hotel: no hay marca que quitar
    assert palabras_de_marca(["Zentra", "Zentra Plaza"]) == set()  # quitarla dejaría un nombre vacío


# ---------- resolución por nombre ----------

@pytest.mark.parametrize(
    ("texto", "alias"),
    [
        ("balta", "balta"),
        ("Balta", "balta"),
        ("Zentra Balta", "balta"),
        ("hotel balta", "balta"),
        ("el Balta", "balta"),
        ("PLAZA", "plaza"),
        ("zentra plaza", "plaza"),
        ("San José", "san_jose"),
        ("san jose", "san_jose"),
        ("SAN JOSÉ", "san_jose"),
        ("sanjose", "san_jose"),
        ("san_jose", "san_jose"),
        ("Zentra San Jose", "san_jose"),
        ("San", "san_jose"),  # palabra contenida en un solo nombre
        ("José", "san_jose"),
    ],
)
def test_resuelve_hotel_por_nombre(texto, alias):
    assert zentra().hotel(texto).alias == alias


def test_otros_nombres():
    reg = HotelRegistry(
        HotelsConfig(
            hoteles=(hotel("balta", "Zentra Balta", "1", otros=("el de Balta", "Centro")), hotel("plaza", "Zentra Plaza", "2")),
            modo="multi",
        ),
        client_factory=FakeClient,
    )
    assert reg.hotel("centro").alias == "balta"


@pytest.mark.parametrize("texto", ["red", "la red", "Toda la red", "todos", "TODOS LOS HOTELES", "grupo", "los tres", "los 3", "consolidado"])
def test_palabras_de_red(texto):
    reg = zentra()
    assert reg.es_red(texto)
    assert [c.settings.hotel_alias for c in reg.clients(texto)] == ["balta", "plaza", "san_jose"]


def test_nombres_red_adicionales():
    reg = zentra(nombres_red=("cadena",))
    assert reg.es_red("la cadena") and not zentra().es_red("la cadena")


def test_red_no_vale_en_consulta_de_un_solo_hotel():
    with pytest.raises(HotelError, match="Esta consulta es de un solo hotel"):
        zentra().client("red")


def test_hotel_omitido_con_varios_pide_elegir():
    with pytest.raises(HotelError) as exc:
        zentra().client(None)
    msg = str(exc.value)
    assert msg.startswith("Indica de qué hotel")
    assert "Zentra Balta (balta)" in msg and "Zentra San José (san_jose)" in msg and "'red'" in msg
    with pytest.raises(HotelError, match="Indica de qué hotel"):
        zentra().client("   ")


def test_predeterminado_opcional():
    assert zentra(predeterminado="plaza").hotel(None).alias == "plaza"


def test_no_encontrado():
    with pytest.raises(HotelError, match="No encontré el hotel 'Miraflores'.*Zentra Plaza"):
        zentra().hotel("Miraflores")


@pytest.mark.parametrize("texto", ["Zentra", "hotel", "el"])
def test_texto_sin_palabras_utiles(texto):
    with pytest.raises(HotelError, match="no identifica un hotel"):
        zentra().hotel(texto)


def test_ambiguo():
    reg = HotelRegistry(
        HotelsConfig(
            hoteles=(hotel("plaza_norte", "Plaza Norte", "1"), hotel("plaza_sur", "Plaza Sur", "2"), hotel("balta", "Balta", "3")),
            modo="multi",
        ),
        client_factory=FakeClient,
    )
    with pytest.raises(HotelError, match="puede ser más de un hotel: Plaza Norte .*Plaza Sur"):
        reg.hotel("plaza")
    assert reg.hotel("plaza sur").alias == "plaza_sur"


def test_palabra_comun_a_todos_no_identifica():
    reg = HotelRegistry(
        HotelsConfig(hoteles=(hotel("plaza_norte", "Plaza Norte", "1"), hotel("plaza_sur", "Plaza Sur", "2")), modo="multi"),
        client_factory=FakeClient,
    )
    with pytest.raises(HotelError, match="'plaza' no identifica un hotel. Hoteles: Plaza Norte"):
        reg.hotel("plaza")


# ---------- validación de nombres ----------

def test_nombre_de_hotel_reservado_para_la_red():
    with pytest.raises(ConfigError, match="palabra reservada"):
        HotelRegistry(HotelsConfig(hoteles=(hotel("red", "Red", "1"), hotel("b", "B", "2")), modo="multi"))


def test_dos_hoteles_con_el_mismo_nombre():
    with pytest.raises(ConfigError, match="comparten un nombre"):
        HotelRegistry(
            HotelsConfig(
                hoteles=(hotel("a", "Zentra Balta", "1", otros=("centro",)), hotel("b", "Zentra Plaza", "2", otros=("Centro",))),
                modo="multi",
            )
        )


def test_registro_vacio():
    with pytest.raises(ConfigError):
        HotelRegistry(HotelsConfig(hoteles=()))


# ---------- un solo hotel ----------

def test_legacy_un_hotel_acepta_cualquier_texto(settings):
    reg = HotelRegistry(HotelsConfig(hoteles=(Hotel.from_settings(settings),)), client_factory=FakeClient)
    assert not reg.multi
    assert reg.hotel(None).alias == "principal"
    assert reg.hotel("Balta").alias == "principal"
    assert reg.clients("red")[0].settings is settings


def test_un_hotel_con_nombre_no_responde_por_otro():
    reg = HotelRegistry(HotelsConfig(hoteles=(hotel("balta", "Zentra Balta", "1"),), modo="multi"), client_factory=FakeClient)
    assert reg.hotel(None).alias == "balta"
    assert reg.hotel("balta").alias == "balta"
    assert reg.hotel("red").alias == "balta"
    with pytest.raises(HotelError, match="No encontré el hotel 'Plaza'"):
        reg.hotel("Plaza")


def test_single_reutiliza_el_cliente(settings):
    client = FakeClient(settings)
    reg = HotelRegistry.single(client)
    assert reg.client(None) is client and reg.clients("red") == [client]


# ---------- clientes, limiter y disponibilidad ----------

def test_clientes_perezosos_y_reutilizados():
    reg = zentra()
    assert reg._clients == {}
    c1 = reg.client("balta")
    assert reg.client("Zentra Balta") is c1
    assert list(reg._clients) == ["balta"]


def test_limiter_compartido_solo_con_la_misma_key():
    hoteles = (
        hotel("a", "Hotel A", "1", "cbat_comun"),
        hotel("b", "Hotel B", "2", "cbat_comun"),
        hotel("c", "Hotel C", "3", "cbat_otra"),
    )
    reg = HotelRegistry(HotelsConfig(hoteles=hoteles, modo="multi"), client_factory=FakeClient)
    a, b, c = (reg.client(x) for x in "abc")
    assert isinstance(a.limiter, RateLimiter)
    assert a.limiter is b.limiter
    assert c.limiter is not a.limiter


def test_hotel_sin_key():
    hoteles = (hotel("balta", "Zentra Balta", "1"), hotel("plaza", "Zentra Plaza", "2", disponible=False))
    reg = HotelRegistry(HotelsConfig(hoteles=hoteles, modo="multi"), client_factory=FakeClient)
    with pytest.raises(HotelError, match="No hay API key de Zentra Plaza"):
        reg.client("plaza")
    assert [c.settings.hotel_alias for c in reg.clients("red")] == ["balta"]
    assert [h.alias for h in reg.no_disponibles()] == ["plaza"]


def test_describe_sin_secretos():
    hoteles = (hotel("balta", "Zentra Balta", "1", "cbat_SECRETA"), hotel("plaza", "Zentra Plaza", "2", disponible=False))
    reg = HotelRegistry(HotelsConfig(hoteles=hoteles, modo="multi"))
    d = reg.describe()
    assert d[0] == {"alias": "balta", "nombre": "Zentra Balta", "property_id": "1", "zona_horaria": "America/Lima", "moneda": "PEN", "disponible": True}
    assert d[1]["disponible"] is False and "motivo" in d[1]
    assert "cbat_SECRETA" not in repr(d)


async def test_aclose_cierra_todos():
    reg = zentra()
    clients = reg.clients("red")
    await reg.aclose()
    assert all(c.closed for c in clients)
    assert reg._clients == {}


# ---------- descripción del parámetro ----------

def test_descripcion_parametro_lista_hoteles_y_red():
    texto = zentra().descripcion_parametro()
    assert "'balta' = Zentra Balta" in texto and "'san_jose' = Zentra San José" in texto
    assert "'red'" in texto and "PREGÚNTALE" in texto


def test_descripcion_sin_catalogo():
    assert "un solo hotel" in descripcion_desde_catalogo(None)


# ---------- integración con CloudbedsClient real ----------

@respx.mock
async def test_cada_hotel_usa_su_key_y_property_id(fake_sleep):
    route = respx.get(f"{BASE_URL}getDashboard").mock(return_value=httpx.Response(200, json={"success": True, "data": {}}))
    reg = HotelRegistry(
        HotelsConfig(
            hoteles=(hotel("balta", "Zentra Balta", "111", "cbat_b"), hotel("plaza", "Zentra Plaza", "222", "cbat_p")),
            modo="multi",
        ),
        client_factory=lambda s, *, limiter: CloudbedsClient(s, limiter=limiter, sleep=fake_sleep),
    )
    try:
        for texto in ("Plaza", "Balta"):
            c = reg.client(texto)
            await c.get("getDashboard", {"propertyID": c.settings.property_id})
    finally:
        await reg.aclose()
    sent = [(r.request.headers["x-api-key"], r.request.headers["X-PROPERTY-ID"], r.request.url.params["propertyID"]) for r in route.calls]
    assert sent == [("cbat_p", "222", "222"), ("cbat_b", "111", "111")]


async def test_client_acepta_limiter_externo(settings):
    limiter = RateLimiter()
    async with CloudbedsClient(settings, limiter=limiter) as c:
        assert c._limiter is limiter
