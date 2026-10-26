"""Carga y validación de la configuración desde .env y hoteles.json.

El .env y hoteles.json se buscan con ruta ABSOLUTA en la raíz del proyecto (dos
niveles por encima de este paquete), así funciona sin importar el cwd con el
que Claude Desktop lance el servidor.

- Sin hoteles.json: modo legacy, un solo hotel configurado en .env (como siempre).
- Con hoteles.json: varios hoteles. El JSON no tiene secretos; la key de cada
  hotel va en el keyring (usuario CLOUDBEDS_API_KEY:<alias>).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from .errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
HOTELES_PATH = PROJECT_ROOT / "hoteles.json"

LEGACY_ALIAS = "principal"

logger = logging.getLogger("cloudbeds_mcp")


@dataclass(frozen=True)
class Settings:
    api_key: str
    property_id: str | None
    show_pii: bool
    tz: ZoneInfo
    max_results: int
    key_source: str = ".env"  # "keyring", ".env" o "env" (para diagnóstico; nunca la key)
    hotel_alias: str = LEGACY_ALIAS
    hotel_name: str | None = None
    currency: str | None = None

    def __repr__(self) -> str:  # nunca exponer la key
        return (
            f"Settings(hotel={self.hotel_alias!r}, nombre={self.hotel_name!r}, "
            f"api_key=*** ({self.key_source}), property_id={self.property_id!r}, "
            f"show_pii={self.show_pii}, tz={self.tz.key!r}, max_results={self.max_results}, "
            f"moneda={self.currency!r})"
        )


@dataclass(frozen=True)
class HotelEntry:
    """Un hotel de hoteles.json (sin secretos)."""

    alias: str
    nombre: str
    property_id: str
    tz: ZoneInfo | None = None  # None = CLOUDBEDS_TZ
    moneda: str | None = None
    otros_nombres: tuple[str, ...] = ()


@dataclass(frozen=True)
class Catalog:
    """Contenido validado de hoteles.json."""

    hoteles: tuple[HotelEntry, ...]
    predeterminado: str | None = None
    nombres_red: tuple[str, ...] = ()


@dataclass(frozen=True)
class Hotel:
    """Hotel listo para usar. `settings` es None si en esta PC no hay key para él."""

    alias: str
    nombre: str | None
    property_id: str | None
    tz: ZoneInfo
    moneda: str | None = None
    otros_nombres: tuple[str, ...] = ()
    settings: Settings | None = None
    motivo: str | None = None  # por qué no está disponible

    @property
    def disponible(self) -> bool:
        return self.settings is not None

    @classmethod
    def from_settings(cls, settings: Settings) -> Hotel:
        return cls(
            alias=settings.hotel_alias,
            nombre=settings.hotel_name,
            property_id=settings.property_id,
            tz=settings.tz,
            moneda=settings.currency,
            settings=settings,
        )


@dataclass(frozen=True)
class HotelsConfig:
    hoteles: tuple[Hotel, ...]
    predeterminado: str | None = None
    nombres_red: tuple[str, ...] = ()
    modo: str = "legacy"  # "legacy" (solo .env) o "multi" (hoteles.json)


MAX_RESULTS_CAP = 5000  # tope absoluto de resultados por consulta (F5)

KEYRING_SERVICE = "cloudbeds-mcp"
KEYRING_USER = "CLOUDBEDS_API_KEY"


def keyring_enabled() -> bool:
    return os.getenv("CLOUDBEDS_USE_KEYRING", "true").strip().lower() not in ("false", "0", "no")


def keyring_user(alias: str | None = None) -> str:
    """Usuario del keyring: la key legacy o la de un hotel concreto."""
    return f"{KEYRING_USER}:{alias}" if alias else KEYRING_USER


def env_key_var(alias: str) -> str:
    return f"CLOUDBEDS_API_KEY_{alias.upper()}"


def key_from_keyring(user: str = KEYRING_USER) -> str | None:
    """Lee la key del Administrador de credenciales (Windows) / Llavero (macOS)."""
    if not keyring_enabled():
        return None
    try:
        import keyring

        value = keyring.get_password(KEYRING_SERVICE, user)
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

    api_key, key_source = _legacy_key()
    if not api_key:
        raise ConfigError(
            "Falta la API key de Cloudbeds. Guárdala con 'python scripts/guardar_key.py' "
            f"(recomendado) o complétala como CLOUDBEDS_API_KEY en {ENV_PATH}."
        )
    _warn_prefix(api_key, "CLOUDBEDS_API_KEY")

    property_id = os.getenv("CLOUDBEDS_PROPERTY_ID", "").strip() or None
    show_pii, tz, max_results = _global_options()

    return Settings(
        api_key=api_key,
        property_id=property_id,
        show_pii=show_pii,
        tz=tz,
        max_results=max_results,
        key_source=key_source,
    )


def _legacy_key() -> tuple[str | None, str]:
    """Key de la instalación de un solo hotel: keyring y, si no está, CLOUDBEDS_API_KEY."""
    api_key = key_from_keyring()
    if api_key:
        return api_key, "keyring"
    return os.getenv("CLOUDBEDS_API_KEY", "").strip() or None, ".env"


def _hotel_key(alias: str) -> tuple[str | None, str]:
    """Key propia de un hotel: keyring CLOUDBEDS_API_KEY:<alias> y luego CLOUDBEDS_API_KEY_<ALIAS>."""
    api_key = key_from_keyring(keyring_user(alias))
    if api_key:
        return api_key, "keyring"
    return os.getenv(env_key_var(alias), "").strip() or None, "env"


def _warn_prefix(api_key: str, origen: str) -> None:
    if not api_key.startswith("cbat_"):
        logger.warning("%s no empieza por 'cbat_'; verifica que sea una API key de Cloudbeds.", origen)


def _parse_tz(name: str, origen: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"{origen} no es una zona horaria válida: {name!r}.") from exc


def _global_options() -> tuple[bool, ZoneInfo, int]:
    """Opciones de .env comunes a todos los hoteles: PII, zona horaria por defecto y tope de resultados."""
    show_pii = _parse_bool("CLOUDBEDS_SHOW_PII", os.getenv("CLOUDBEDS_SHOW_PII", "false"))

    tz = _parse_tz(os.getenv("CLOUDBEDS_TZ", "America/Lima").strip() or "America/Lima", "CLOUDBEDS_TZ")

    raw_max = os.getenv("CLOUDBEDS_MAX_RESULTS", "500").strip() or "500"
    try:
        max_results = int(raw_max)
    except ValueError as exc:
        raise ConfigError("CLOUDBEDS_MAX_RESULTS debe ser un número entero.") from exc
    if not 1 <= max_results <= MAX_RESULTS_CAP:
        raise ConfigError(f"CLOUDBEDS_MAX_RESULTS debe estar entre 1 y {MAX_RESULTS_CAP}.")
    return show_pii, tz, max_results


# ---------- hoteles.json ----------

ALIAS_RE = re.compile(r"^[a-z0-9_]{1,32}$")
PROPERTY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_TOP_FIELDS = {"hoteles", "predeterminado", "nombres_red"}
_HOTEL_FIELDS = {"alias", "nombre", "property_id", "tz", "moneda", "otros_nombres"}
_SECRET_HINTS = ("key", "token", "secret", "password", "clave")


def _check_fields(data: dict[str, Any], allowed: set[str], donde: str) -> None:
    # Las claves que empiezan por "_" son comentarios y se ignoran.
    for name in data:
        if name.startswith("_") or name in allowed:
            continue
        if any(h in name.lower() for h in _SECRET_HINTS):
            raise ConfigError(
                f"{donde}: el campo '{name}' no está permitido. Las API keys nunca van en hoteles.json; "
                "se guardan en el keyring con 'python scripts/agregar_hotel.py'."
            )
        raise ConfigError(f"{donde}: campo desconocido '{name}'. Campos válidos: {', '.join(sorted(allowed))}.")


def _text_list(value: Any, donde: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ConfigError(f"{donde} debe ser una lista de textos no vacíos.")
    return tuple(v.strip() for v in value)


def _parse_hotel(raw: Any, n: int) -> HotelEntry:
    donde = f"hoteles.json, hotel #{n}"
    if not isinstance(raw, dict):
        raise ConfigError(f"{donde}: cada hotel debe ser un objeto JSON.")
    _check_fields(raw, _HOTEL_FIELDS, donde)

    alias = raw.get("alias")
    if not isinstance(alias, str) or not ALIAS_RE.match(alias):
        raise ConfigError(
            f"{donde}: 'alias' es obligatorio y solo admite minúsculas, números y '_' (máx. 32), ej. 'san_jose'."
        )
    donde = f"hoteles.json, hotel '{alias}'"

    nombre = raw.get("nombre")
    if not isinstance(nombre, str) or not nombre.strip() or len(nombre) > 100:
        raise ConfigError(f"{donde}: 'nombre' es obligatorio (máx. 100 caracteres).")

    pid = raw.get("property_id")
    pid = str(pid).strip() if isinstance(pid, (str, int)) and not isinstance(pid, bool) else ""
    if not PROPERTY_ID_RE.match(pid):
        raise ConfigError(f"{donde}: 'property_id' es obligatorio (el propertyID de Cloudbeds).")

    tz = raw.get("tz")
    if tz is not None and not isinstance(tz, str):
        raise ConfigError(f"{donde}: 'tz' debe ser un texto, ej. 'America/Lima'.")
    zone = _parse_tz(tz.strip(), f"{donde}: 'tz'") if tz and tz.strip() else None

    moneda = raw.get("moneda")
    if moneda is not None:
        moneda = str(moneda).strip().upper()
        if not CURRENCY_RE.match(moneda):
            raise ConfigError(f"{donde}: 'moneda' debe ser un código de 3 letras, ej. 'PEN'.")

    return HotelEntry(
        alias=alias,
        nombre=nombre.strip(),
        property_id=pid,
        tz=zone,
        moneda=moneda or None,
        otros_nombres=_text_list(raw.get("otros_nombres"), f"{donde}: 'otros_nombres'"),
    )


def load_catalog(path: Path | None = None) -> Catalog | None:
    """Lee y valida hoteles.json. Devuelve None si no existe (modo legacy). No lee secretos."""
    path = path or HOTELES_PATH
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"hoteles.json no es un JSON válido ({exc.msg}, línea {exc.lineno}).") from None
    except OSError as exc:
        raise ConfigError(f"No se pudo leer hoteles.json ({type(exc).__name__}).") from None

    if not isinstance(raw, dict):
        raise ConfigError("hoteles.json debe ser un objeto con la lista 'hoteles'.")
    _check_fields(raw, _TOP_FIELDS, "hoteles.json")
    lista = raw.get("hoteles")
    if not isinstance(lista, list) or not lista:
        raise ConfigError("hoteles.json debe tener una lista 'hoteles' con al menos un hotel.")

    hoteles = tuple(_parse_hotel(h, i) for i, h in enumerate(lista, start=1))
    for campo in ("alias", "property_id"):
        valores = [getattr(h, campo) for h in hoteles]
        repetidos = sorted({v for v in valores if valores.count(v) > 1})
        if repetidos:
            raise ConfigError(f"hoteles.json: '{campo}' repetido: {', '.join(repetidos)}.")

    predeterminado = raw.get("predeterminado")
    if predeterminado is not None and predeterminado not in {h.alias for h in hoteles}:
        raise ConfigError("hoteles.json: 'predeterminado' debe ser el alias de uno de los hoteles.")

    return Catalog(
        hoteles=hoteles,
        predeterminado=predeterminado,
        nombres_red=_text_list(raw.get("nombres_red"), "hoteles.json: 'nombres_red'"),
    )


def load_hotels(env_path: Path | None = None, hoteles_path: Path | None = None) -> HotelsConfig:
    """Carga todos los hoteles con su key.

    Sin hoteles.json es idéntico a load_settings() (un hotel con alias 'principal').
    Con hoteles.json, la key de cada hotel se busca en: keyring CLOUDBEDS_API_KEY:<alias>,
    variable CLOUDBEDS_API_KEY_<ALIAS> y, solo para el hotel cuyo property_id coincide con
    CLOUDBEDS_PROPERTY_ID (o si hay uno solo), la key legacy. Un hotel sin key queda como
    no disponible; si ninguno tiene key es un error de configuración.
    """
    catalog = load_catalog(hoteles_path)
    if catalog is None:
        return HotelsConfig(hoteles=(Hotel.from_settings(load_settings(env_path)),))

    load_dotenv(env_path or ENV_PATH, override=False)
    show_pii, default_tz, max_results = _global_options()
    legacy_pid = os.getenv("CLOUDBEDS_PROPERTY_ID", "").strip() or None

    hoteles: list[Hotel] = []
    for e in catalog.hoteles:
        tz = e.tz or default_tz
        api_key, source = _hotel_key(e.alias)
        if not api_key and (len(catalog.hoteles) == 1 or e.property_id == legacy_pid):
            api_key, source = _legacy_key()
        base = {"alias": e.alias, "nombre": e.nombre, "property_id": e.property_id, "tz": tz,
                "moneda": e.moneda, "otros_nombres": e.otros_nombres}
        if not api_key:
            motivo = (
                f"No hay API key de {e.nombre} en esta PC. Agrégala con "
                f"'python scripts/agregar_hotel.py --alias {e.alias}'."
            )
            logger.warning("Hotel %s sin API key: no estará disponible.", e.alias)
            hoteles.append(Hotel(**base, motivo=motivo))
            continue
        _warn_prefix(api_key, f"La API key de {e.alias}")
        settings = Settings(
            api_key=api_key,
            property_id=e.property_id,
            show_pii=show_pii,
            tz=tz,
            max_results=max_results,
            key_source=source,
            hotel_alias=e.alias,
            hotel_name=e.nombre,
            currency=e.moneda,
        )
        hoteles.append(Hotel(**base, settings=settings))

    if not any(h.disponible for h in hoteles):
        raise ConfigError(
            "Ningún hotel de hoteles.json tiene API key en esta PC. "
            "Agrégalas con 'python scripts/agregar_hotel.py'."
        )
    return HotelsConfig(
        hoteles=tuple(hoteles),
        predeterminado=catalog.predeterminado,
        nombres_red=catalog.nombres_red,
        modo="multi",
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
