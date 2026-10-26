"""Registro de hoteles: resuelve el hotel que pide el usuario y entrega su cliente.

El gerente nombra los hoteles como quiere ("Balta", "Zentra Plaza", "san jose") y usa
"red" para los tres. La comparación ignora mayúsculas, tildes, signos, la palabra
"hotel", artículos y la marca (las palabras comunes a todos los nombres, ej. "Zentra").

Los clientes HTTP se crean la primera vez que se usan. Los hoteles que comparten API key
comparten también el RateLimiter, porque el límite de Cloudbeds es por key.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from typing import Any

from .client import CloudbedsClient, RateLimiter
from .config import Catalog, Hotel, HotelsConfig, Settings
from .errors import ConfigError, HotelError

# Palabras que no distinguen un hotel de otro.
_IGNORADAS = frozenset({"hotel", "hoteles", "el", "la", "los", "las", "de", "del", "en"})

# Formas de referirse a todos los hoteles a la vez (se comparan ya normalizadas).
NOMBRES_RED = (
    "red", "la red", "toda la red", "todos", "todas", "todo", "todos los hoteles",
    "grupo", "todo el grupo", "los tres", "los 3", "consolidado",
)
RED = "red"  # valor canónico que se le sugiere al modelo

ClientFactory = Callable[..., CloudbedsClient]


def normalizar(texto: str, ignorar: Iterable[str] = ()) -> tuple[str, ...]:
    """Palabras significativas: minúsculas, sin tildes ni signos y sin palabras ignoradas."""
    plano = unicodedata.normalize("NFKD", texto)
    plano = "".join(c for c in plano if not unicodedata.combining(c)).lower()
    extra = frozenset(ignorar)
    return tuple(t for t in re.findall(r"[a-z0-9]+", plano) if t not in _IGNORADAS and t not in extra)


def palabras_de_marca(nombres: Iterable[str]) -> frozenset[str]:
    """Palabras presentes en TODOS los nombres (ej. 'zentra'); no sirven para distinguirlos.

    Si quitarlas dejara algún nombre vacío, no se quita ninguna.
    """
    tokens = [set(normalizar(n)) for n in nombres]
    if len(tokens) < 2:
        return frozenset()
    comunes = set.intersection(*tokens)
    if any(not (t - comunes) for t in tokens):
        return frozenset()
    return frozenset(comunes)


def _formas(tokens: tuple[str, ...]) -> set[str]:
    """Una frase normalizada se compara separada por espacios y pegada ('san jose' / 'sanjose')."""
    return {" ".join(tokens), "".join(tokens)} - {""}


def _lista(pares: Iterable[tuple[str, str | None]]) -> str:
    return ", ".join(f"{nombre} ({alias})" if nombre else alias for alias, nombre in pares)


def descripcion_parametro(pares: list[tuple[str, str | None]], admite_red: bool = True) -> str:
    """Texto del parámetro `hotel` de las herramientas, con la lista de hoteles configurados."""
    if len(pares) <= 1:
        return "Hotel a consultar. Hay un solo hotel configurado: puedes omitir este parámetro."
    hoteles = "; ".join(f"'{alias}' = {nombre or alias}" for alias, nombre in pares)
    if admite_red:
        red = f"Usa '{RED}' para todos los hoteles (el usuario dice 'la red', 'todos' o 'el grupo')."
    else:
        red = (
            "Esta consulta es de UN hotel: si el usuario la pide para la red o para todos, "
            "consulta cada hotel por separado."
        )
    return (
        f"Hotel a consultar (alias o nombre): {hoteles}. El usuario suele decir solo el nombre "
        f"corto, sin la marca. {red} Si el usuario no indica el hotel y la conversación no lo "
        "deja claro, PREGÚNTALE antes de consultar."
    )


def descripcion_desde_catalogo(catalog: Catalog | None, admite_red: bool = True) -> str:
    """Igual que descripcion_parametro, pero sin keys: sirve al registrar las herramientas."""
    pares = [(h.alias, h.nombre) for h in catalog.hoteles] if catalog else []
    return descripcion_parametro(pares, admite_red)


class HotelRegistry:
    def __init__(self, config: HotelsConfig, client_factory: ClientFactory = CloudbedsClient) -> None:
        if not config.hoteles:
            raise ConfigError("No hay hoteles configurados.")
        self.config = config
        self._hotels: dict[str, Hotel] = {h.alias: h for h in config.hoteles}
        self._factory = client_factory
        self._clients: dict[str, CloudbedsClient] = {}
        self._limiters: dict[str, RateLimiter] = {}

        self._marca = palabras_de_marca(h.nombre for h in config.hoteles if h.nombre)
        self._red = set().union(*(_formas(self._norm(p)) for p in (*NOMBRES_RED, *config.nombres_red)))
        self._formas_hotel: dict[str, set[str]] = {}
        self._tokens_hotel: dict[str, set[str]] = {}
        for h in config.hoteles:
            frases = [self._norm(h.alias)] + [self._norm(n) for n in (h.nombre, *h.otros_nombres) if n]
            self._formas_hotel[h.alias] = set().union(*(_formas(f) for f in frases))
            self._tokens_hotel[h.alias] = {t for f in frases for t in f}
        self._validar_nombres()

    @classmethod
    def single(cls, client: CloudbedsClient) -> HotelRegistry:
        """Registro de un solo hotel a partir de un cliente ya creado (tests y modo legacy)."""
        registry = cls(HotelsConfig(hoteles=(Hotel.from_settings(client.settings),)))
        registry._clients[client.settings.hotel_alias] = client
        return registry

    # ---------- consulta ----------

    @property
    def multi(self) -> bool:
        return len(self._hotels) > 1

    @property
    def hoteles(self) -> list[Hotel]:
        return list(self._hotels.values())

    def es_red(self, texto: str | None) -> bool:
        if texto is None:
            return False
        return bool(_formas(self._norm(texto)) & self._red)

    def hotel(self, texto: str | None) -> Hotel:
        """El hotel al que se refiere `texto` (alias, nombre o nombre corto)."""
        if not self.multi:
            unico = self.hoteles[0]
            # Sin nombre configurado (modo legacy) no hay con qué comparar: se usa el único hotel.
            if not unico.nombre or texto is None or not texto.strip() or self.es_red(texto):
                return unico
            return self._hotels[self._buscar(texto)]  # evita responder con otro hotel por error
        if texto is None or not texto.strip():
            if self.config.predeterminado:
                return self._hotels[self.config.predeterminado]
            raise HotelError(f"Indica de qué hotel quieres la información. {self._ayuda()}")
        if self.es_red(texto):
            raise HotelError(
                f"Esta consulta es de un solo hotel; no se puede pedir para '{texto.strip()}'. "
                f"Indica uno: {self._ayuda()}"
            )
        return self._hotels[self._buscar(texto)]

    def client(self, texto: str | None) -> CloudbedsClient:
        """Cliente de UN hotel. 'red' es un error (las consultas operativas son de un hotel)."""
        return self._client_for(self.hotel(texto))

    def clients(self, texto: str | None) -> list[CloudbedsClient]:
        """Cliente(s) de la consulta: todos los hoteles disponibles si es 'red', si no uno."""
        if self.multi and self.es_red(texto):
            return [self._client_for(h) for h in self.hoteles if h.disponible]
        return [self.client(texto)]

    def no_disponibles(self) -> list[Hotel]:
        return [h for h in self.hoteles if not h.disponible]

    def describe(self) -> list[dict[str, Any]]:
        """Lista de hoteles para mostrar, sin secretos."""
        out = []
        for h in self.hoteles:
            item: dict[str, Any] = {
                "alias": h.alias,
                "nombre": h.nombre,
                "property_id": h.property_id,
                "zona_horaria": h.tz.key,
                "moneda": h.moneda,
                "disponible": h.disponible,
            }
            if h.motivo:
                item["motivo"] = h.motivo
            out.append(item)
        return out

    def descripcion_parametro(self, admite_red: bool = True) -> str:
        return descripcion_parametro([(h.alias, h.nombre) for h in self.hoteles], admite_red)

    async def aclose(self) -> None:
        clients, self._clients = list(self._clients.values()), {}
        for c in clients:
            await c.aclose()

    # ---------- interno ----------

    def _norm(self, texto: str) -> tuple[str, ...]:
        return normalizar(texto, self._marca)

    def _ayuda(self) -> str:
        return f"Hoteles: {_lista((h.alias, h.nombre) for h in self.hoteles)}. Para todos usa '{RED}'."

    def _validar_nombres(self) -> None:
        for alias, formas in self._formas_hotel.items():
            if formas & self._red:
                raise ConfigError(f"hoteles.json: un nombre del hotel '{alias}' coincide con una palabra reservada para toda la red.")
            for otro, formas_otro in self._formas_hotel.items():
                if otro < alias and formas & formas_otro:
                    raise ConfigError(f"hoteles.json: los hoteles '{otro}' y '{alias}' comparten un nombre; no se podrían distinguir.")

    def _buscar(self, texto: str) -> str:
        crudo = texto.strip().lower()
        if crudo in self._hotels:
            return crudo
        q = self._norm(texto)
        if not q:
            raise HotelError(f"'{texto.strip()}' no identifica un hotel. {self._ayuda()}")
        buscadas = _formas(q)
        exactos = [a for a, formas in self._formas_hotel.items() if buscadas & formas]
        candidatos = exactos or [a for a, tokens in self._tokens_hotel.items() if set(q) <= tokens]
        if len(candidatos) == 1:
            return candidatos[0]
        if candidatos:
            nombres = _lista((a, self._hotels[a].nombre) for a in candidatos)
            raise HotelError(f"'{texto.strip()}' puede ser más de un hotel: {nombres}. Indica cuál.")
        raise HotelError(f"No encontré el hotel '{texto.strip()}'. {self._ayuda()}")

    def _client_for(self, hotel: Hotel) -> CloudbedsClient:
        if hotel.settings is None:
            raise HotelError(hotel.motivo or f"El hotel {hotel.nombre or hotel.alias} no está disponible.")
        client = self._clients.get(hotel.alias)
        if client is None:
            client = self._factory(hotel.settings, limiter=self._limiter_for(hotel.settings))
            self._clients[hotel.alias] = client
        return client

    def _limiter_for(self, settings: Settings) -> RateLimiter:
        # La key solo se usa como clave del diccionario en memoria; nunca se registra.
        limiter = self._limiters.get(settings.api_key)
        if limiter is None:
            limiter = self._limiters[settings.api_key] = RateLimiter()
        return limiter
