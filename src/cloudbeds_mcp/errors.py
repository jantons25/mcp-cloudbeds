"""Errores del cliente Cloudbeds con mensajes claros en español."""

from __future__ import annotations


class CloudbedsError(Exception):
    """Error genérico al consultar Cloudbeds."""

    def __init__(self, message: str, *, request_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.request_id = request_id

    def __str__(self) -> str:
        if self.request_id:
            return f"{self.message} (X-Request-ID: {self.request_id})"
        return self.message


class AuthError(CloudbedsError):
    """API key inválida, ausente o revocada (HTTP 401). No se reintenta."""


class RateLimitError(CloudbedsError):
    """Se superó el límite de peticiones (HTTP 429) tras agotar los reintentos."""


class NotAllowedError(CloudbedsError):
    """Endpoint o método fuera de la lista blanca de solo lectura."""


class ConfigError(Exception):
    """Configuración incompleta o inválida en .env."""


# Mensajes success:false documentados por Cloudbeds -> explicación en español.
_KNOWN_MESSAGES: list[tuple[str, str]] = [
    (
        "user who approved this connection is not active anymore",
        "El usuario de Cloudbeds que creó la API key fue desactivado. "
        "Hay que generar una key nueva con una cuenta activa e institucional.",
    ),
    (
        "none of the included property id",
        "La API key no tiene acceso a esa propiedad. "
        "Revisa CLOUDBEDS_PROPERTY_ID en .env o los permisos de la key.",
    ),
    (
        "have an invalid status",
        "La propiedad no está activa en Cloudbeds. Consulta con el administrador de la cuenta.",
    ),
]


def translate_message(message: str | None) -> str:
    """Traduce un mensaje success:false de Cloudbeds a un texto claro en español."""
    original = (message or "").strip()
    lowered = original.lower()
    for needle, spanish in _KNOWN_MESSAGES:
        if needle in lowered:
            return spanish
    if not original:
        return "Cloudbeds rechazó la consulta sin indicar el motivo."
    return f"Cloudbeds rechazó la consulta: {original}"
