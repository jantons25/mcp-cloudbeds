"""Cliente HTTP de SOLO LECTURA para la API v1.3 de Cloudbeds.

- Solo existe `get` / `get_all`; no hay métodos de escritura.
- Solo se permiten los endpoints de ALLOWED_ENDPOINTS.
- Token bucket a 4 req/s (el límite de Cloudbeds es 5 req/s).
- Reintentos: 429 respeta Retry-After + jitter; 5xx/timeout con backoff exponencial.
- Valida `success: false` aunque llegue con HTTP 200.
- Logs a stderr sin key ni parámetros (pueden contener PII).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from . import __version__
from .config import Settings
from .errors import AuthError, CloudbedsError, NotAllowedError, RateLimitError, translate_message

BASE_URL = "https://api.cloudbeds.com/api/v1.3/"

# Lista blanca (sección 4 del plan): endpoint -> scope requerido.
ALLOWED_ENDPOINTS: dict[str, str | None] = {
    "userinfo": None,
    "getHotels": "read:hotel",
    "getHotelDetails": "read:hotel",
    "getDashboard": "read:dashboard",
    "getReservations": "read:reservation",
    "getReservation": "read:reservation",
    "getAvailableRoomTypes": "read:room",
    "getRoomTypes": "read:room",
    "getRooms": "read:room",
    "getReservationAssignments": "read:reservation",
    "getHousekeepingStatus": "read:housekeeping",
    "getSources": "read:reservation",
    "getRatePlans": "read:rate",
    "getReservationsWithRateDetails": "read:reservation",
}

REQUESTS_PER_SECOND = 4.0
TIMEOUT_SECONDS = 15.0
MAX_RETRIES = 3
BACKOFF_SECONDS = (0.5, 1.0, 2.0)
DEFAULT_RETRY_AFTER = 1.0
MAX_JITTER = 0.3
MAX_PAGE_SIZE = 100

logger = logging.getLogger("cloudbeds_mcp.client")

# httpx/httpcore registran en INFO la URL completa con la query (posible PII).
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

Sleep = Callable[[float], Awaitable[None]]


class RateLimiter:
    """Token bucket asíncrono con capacidad 1: separa cada petición 1/rate segundos.

    Con capacidad 1 nunca hay ráfagas, así que en cualquier ventana de 1 s
    salen como máximo `rate` peticiones.
    """

    def __init__(
        self,
        rate: float = REQUESTS_PER_SECOND,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._interval = 1.0 / rate
        self._clock = clock
        self._sleep = sleep
        self._next_slot = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            wait = self._next_slot - now
            if wait > 0:
                await self._sleep(wait)
                now = self._next_slot
            self._next_slot = now + self._interval


def _parse_retry_after(value: str | None) -> float:
    if not value:
        return DEFAULT_RETRY_AFTER
    try:
        return max(0.0, float(value))
    except ValueError:
        return DEFAULT_RETRY_AFTER  # formato HTTP-date: usar el valor por defecto


# Palabras que, en un success:false, sugieren falta de permisos/scope.
_SCOPE_WORDS = ("scope", "permission", "not authorized", "unauthorized", "access denied", "access_denied", "forbidden")


def _scope_hint(endpoint: str) -> str:
    scope = ALLOWED_ENDPOINTS.get(endpoint)
    if scope:
        return f" Es probable que a la API key le falte el scope '{scope}'; los scopes no se agregan a una key existente, hay que recrearla."
    return ""


class CloudbedsClient:
    def __init__(
        self,
        settings: Settings,
        *,
        base_url: str = BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        rate: float = REQUESTS_PER_SECOND,
        sleep: Sleep = asyncio.sleep,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("La API de Cloudbeds solo se consume por HTTPS.")
        headers = {
            "x-api-key": settings.api_key,
            "Accept": "application/json",
            "User-Agent": f"cloudbeds-mcp/{__version__}",
        }
        if settings.property_id:
            headers["X-PROPERTY-ID"] = settings.property_id
        self.settings = settings
        self._sleep = sleep
        self._limiter = RateLimiter(rate, sleep=sleep)
        self._http = httpx.AsyncClient(
            base_url=base_url, headers=headers, timeout=timeout, transport=transport
        )

    async def __aenter__(self) -> CloudbedsClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """GET a un endpoint de la lista blanca. Devuelve el JSON ya validado."""
        if endpoint not in ALLOWED_ENDPOINTS:
            raise NotAllowedError(
                f"El endpoint '{endpoint}' no está en la lista blanca de solo lectura."
            )
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        for key, value in clean.items():
            # Verificado contra la API real: Cloudbeds toma como verdadero cualquier texto
            # distinto de "0" (incluido "false"), así que los booleanos van como "1"/"0".
            if isinstance(value, bool):
                clean[key] = "1" if value else "0"

        attempt = 0
        while True:
            await self._limiter.acquire()
            start = time.perf_counter()
            try:
                response = await self._http.get(endpoint, params=clean)
            except httpx.TimeoutException:
                self._log(endpoint, "timeout", None, start, None)
                if attempt < MAX_RETRIES:
                    await self._sleep(BACKOFF_SECONDS[attempt])
                    attempt += 1
                    continue
                raise CloudbedsError(
                    "Cloudbeds no respondió a tiempo tras varios intentos. Intenta de nuevo en unos minutos."
                ) from None
            except httpx.HTTPError as exc:
                self._log(endpoint, "error_red", None, start, None)
                raise CloudbedsError(
                    f"No se pudo conectar con Cloudbeds ({type(exc).__name__}). Revisa la conexión a internet."
                ) from None

            request_id = response.headers.get("X-Request-ID")
            status = response.status_code

            if status == 429:
                self._log(endpoint, status, None, start, request_id)
                if attempt < MAX_RETRIES:
                    wait = _parse_retry_after(response.headers.get("Retry-After"))
                    await self._sleep(wait + random.uniform(0, MAX_JITTER))
                    attempt += 1
                    continue
                raise RateLimitError(
                    "Cloudbeds limitó las consultas por exceso de peticiones. Espera un minuto e inténtalo de nuevo.",
                    request_id=request_id,
                )

            if status >= 500:
                self._log(endpoint, status, None, start, request_id)
                if attempt < MAX_RETRIES:
                    await self._sleep(BACKOFF_SECONDS[attempt])
                    attempt += 1
                    continue
                raise CloudbedsError(
                    f"Cloudbeds devolvió un error interno (HTTP {status}) tras varios intentos. Intenta más tarde.",
                    request_id=request_id,
                )

            body = self._json(response)
            success = body.get("success") if isinstance(body, dict) else None
            self._log(endpoint, status, success, start, request_id)

            if status == 401:
                raise AuthError(
                    "La API key de Cloudbeds es inválida, está ausente o fue revocada. "
                    "Revisa CLOUDBEDS_API_KEY en .env o genera una key nueva.",
                    request_id=request_id,
                )
            if status == 403:
                raise CloudbedsError(
                    "Cloudbeds denegó el acceso a esta consulta." + _scope_hint(endpoint),
                    request_id=request_id,
                )
            if status >= 400:
                detail = translate_message(body.get("message") if isinstance(body, dict) else None)
                raise CloudbedsError(f"Petición rechazada (HTTP {status}). {detail}", request_id=request_id)

            if body is None:
                raise CloudbedsError(
                    "Cloudbeds devolvió una respuesta que no es JSON.", request_id=request_id
                )
            if success is False:
                message = body.get("message")
                text = translate_message(message)
                if any(w in str(message).lower() for w in _SCOPE_WORDS):
                    text += _scope_hint(endpoint)
                raise CloudbedsError(text, request_id=request_id)
            return body

    async def get_all(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        max_results: int | None = None,
        page_size: int = MAX_PAGE_SIZE,
        concurrency: int = 1,
    ) -> dict[str, Any]:
        """Recorre pageNumber hasta completar `total` o llegar a `max_results`.

        Con concurrency > 1, si la primera página informa `total`, el resto de páginas se
        pide en paralelo (el rate limiter sigue espaciando los inicios a 4 req/s). Útil en
        endpoints lentos como getReservationsWithRateDetails (~4,5 s por página).

        Devuelve {"data": [...], "total": int | None, "truncado": bool}.
        """
        limit = max_results or self.settings.max_results
        size = max(1, min(page_size, MAX_PAGE_SIZE))
        items: list[Any] = []
        total: int | None = None
        page = 1
        more_available = False

        async def fetch(n: int) -> tuple[list[Any], int | None]:
            body = await self.get(endpoint, {**(params or {}), "pageNumber": n, "pageSize": size})
            data = body.get("data") or []
            if not isinstance(data, list):
                raise CloudbedsError(f"Respuesta inesperada de {endpoint}: 'data' no es una lista.")
            return data, body["total"] if isinstance(body.get("total"), int) else None

        first, total = await fetch(1)
        if concurrency > 1 and total is not None and len(first) == size and total > size:
            last = -(-min(total, limit) // size)  # techo
            sem = asyncio.Semaphore(concurrency)

            async def bounded(n: int) -> list[Any]:
                async with sem:
                    return (await fetch(n))[0]

            pages = await asyncio.gather(*(bounded(n) for n in range(2, last + 1)))
            items = first + [x for p in pages for x in p]
            return {"data": items[:limit], "total": total, "truncado": total > limit or len(items) > limit}

        while True:
            if page == 1:
                data = first
            else:
                data, page_total = await fetch(page)
                if page_total is not None:
                    total = page_total
            items.extend(data)

            if len(items) >= limit:
                more_available = len(items) > limit or (
                    total > limit if total is not None else len(data) == size
                )
                break
            if not data or len(data) < size or (total is not None and len(items) >= total):
                break
            page += 1

        return {"data": items[:limit], "total": total, "truncado": more_available}

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _log(
        endpoint: str, status: int | str, success: Any, start: float, request_id: str | None
    ) -> None:
        latency_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "endpoint=%s status=%s success=%s latency_ms=%.0f request_id=%s",
            endpoint,
            status,
            success,
            latency_ms,
            request_id or "-",
        )
