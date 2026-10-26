"""Carga y validación de la configuración desde .env.

El .env se busca con ruta ABSOLUTA en la raíz del proyecto (dos niveles por
encima de este paquete), así funciona sin importar el cwd con el que Claude
Desktop lance el servidor.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from .errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"

logger = logging.getLogger("cloudbeds_mcp")


@dataclass(frozen=True)
class Settings:
    api_key: str
    property_id: str | None
    show_pii: bool
    tz: ZoneInfo
    max_results: int
    key_source: str = ".env"  # "keyring" o ".env" (para diagnóstico; nunca la key)

    def __repr__(self) -> str:  # nunca exponer la key
        return (
            f"Settings(api_key=*** ({self.key_source}), property_id={self.property_id!r}, "
            f"show_pii={self.show_pii}, tz={self.tz.key!r}, max_results={self.max_results})"
        )


MAX_RESULTS_CAP = 5000  # tope absoluto de resultados por consulta (F5)

KEYRING_SERVICE = "cloudbeds-mcp"
KEYRING_USER = "CLOUDBEDS_API_KEY"


def keyring_enabled() -> bool:
    return os.getenv("CLOUDBEDS_USE_KEYRING", "true").strip().lower() not in ("false", "0", "no")


def key_from_keyring() -> str | None:
    """Lee la key del Administrador de credenciales (Windows) / Llavero (macOS)."""
    if not keyring_enabled():
        return None
    try:
        import keyring

        value = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception as exc:  # backend no disponible o bloqueado: se usa .env
        logger.warning("No se pudo leer el keyring (%s); se usará .env.", type(exc).__name__)
        return None
    return value.strip() if value and value.strip() else None


def _parse_bool(name: str, value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in ("true", "1", "si", "sí", "yes"):
        return True
    if lowered in ("false", "0", "no", ""):
        return False
    raise ConfigError(f"{name} debe ser true o false (valor actual no válido).")


def load_settings(env_path: Path | None = None) -> Settings:
    """Lee .env (sin sobrescribir variables ya definidas en el entorno) y valida.

    La API key se toma primero del keyring y, si no está, de CLOUDBEDS_API_KEY (.env).
    """
    load_dotenv(env_path or ENV_PATH, override=False)

    api_key = key_from_keyring()
    key_source = "keyring"
    if not api_key:
        api_key = os.getenv("CLOUDBEDS_API_KEY", "").strip()
        key_source = ".env"
    if not api_key:
        raise ConfigError(
            "Falta la API key de Cloudbeds. Guárdala con 'python scripts/guardar_key.py' "
            f"(recomendado) o complétala como CLOUDBEDS_API_KEY en {ENV_PATH}."
        )
    if not api_key.startswith("cbat_"):
        logger.warning("CLOUDBEDS_API_KEY no empieza por 'cbat_'; verifica que sea una API key de Cloudbeds.")

    property_id = os.getenv("CLOUDBEDS_PROPERTY_ID", "").strip() or None

    show_pii = _parse_bool("CLOUDBEDS_SHOW_PII", os.getenv("CLOUDBEDS_SHOW_PII", "false"))

    tz_name = os.getenv("CLOUDBEDS_TZ", "America/Lima").strip() or "America/Lima"
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"CLOUDBEDS_TZ no es una zona horaria válida: {tz_name!r}.") from exc

    raw_max = os.getenv("CLOUDBEDS_MAX_RESULTS", "500").strip() or "500"
    try:
        max_results = int(raw_max)
    except ValueError as exc:
        raise ConfigError("CLOUDBEDS_MAX_RESULTS debe ser un número entero.") from exc
    if not 1 <= max_results <= MAX_RESULTS_CAP:
        raise ConfigError(f"CLOUDBEDS_MAX_RESULTS debe estar entre 1 y {MAX_RESULTS_CAP}.")

    return Settings(
        api_key=api_key,
        property_id=property_id,
        show_pii=show_pii,
        tz=tz,
        max_results=max_results,
        key_source=key_source,
    )


def configure_logging(level: int = logging.INFO) -> None:
    """Envía los logs a stderr (stdout queda reservado para JSON-RPC en stdio).

    Silencia httpx/httpcore a nivel INFO porque registran la URL completa con
    los parámetros de consulta, que pueden contener PII.
    """
    root = logging.getLogger()
    # FastMCP instala un RichHandler que parte las líneas largas y duplica cada mensaje:
    # se reemplaza por un único handler de una línea por evento, auditable (F5).
    for existing in list(root.handlers):
        if not getattr(existing, "_cloudbeds", False):
            root.removeHandler(existing)
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler._cloudbeds = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(level)
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
