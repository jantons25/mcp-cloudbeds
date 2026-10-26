"""Guarda la API key de Cloudbeds en el Administrador de credenciales (Windows) o Llavero (macOS).

Uso (desde la raíz del proyecto):
    Windows: .\\.venv\\Scripts\\python.exe scripts\\guardar_key.py           guardar / reemplazar
             .\\.venv\\Scripts\\python.exe scripts\\guardar_key.py --estado  ver de dónde se carga
             .\\.venv\\Scripts\\python.exe scripts\\guardar_key.py --borrar  quitarla del keyring
    macOS:   ./.venv/bin/python scripts/guardar_key.py [--estado | --borrar]

La key se escribe sin eco (no se ve en pantalla), se verifica contra Cloudbeds antes de
guardarla y nunca se imprime.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import re
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import keyring  # noqa: E402

from cloudbeds_mcp.client import CloudbedsClient  # noqa: E402
from cloudbeds_mcp.config import (  # noqa: E402
    ENV_PATH,
    KEYRING_SERVICE,
    KEYRING_USER,
    key_from_keyring,
    load_settings,
)
from cloudbeds_mcp.errors import CloudbedsError, ConfigError  # noqa: E402


def _env_has_key() -> bool:
    if not ENV_PATH.exists():
        return False
    # [ \t]* y no \s*: \s también acepta el salto de línea y "vería" la línea siguiente
    return bool(re.search(r"^CLOUDBEDS_API_KEY=[ \t]*\S", ENV_PATH.read_text(encoding="utf-8"), re.M))


def _clear_env_key() -> None:
    text = ENV_PATH.read_text(encoding="utf-8")
    ENV_PATH.write_text(re.sub(r"^CLOUDBEDS_API_KEY=.*$", "CLOUDBEDS_API_KEY=", text, flags=re.M), encoding="utf-8")


async def _verify(api_key: str) -> str:
    """Comprueba la key con userinfo usando el resto de la configuración de .env."""
    try:
        base = load_settings()
    except ConfigError:
        base = None
    if base is None:  # aún no hay key en ningún lado: construir una configuración mínima
        import os

        os.environ["CLOUDBEDS_API_KEY"] = api_key
        base = load_settings()
    settings = replace(base, api_key=api_key)
    async with CloudbedsClient(settings) as client:
        user = await client.get("userinfo")
    return " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or "-"


def estado() -> int:
    print(f"Backend de keyring: {keyring.get_keyring().__class__.__name__}")
    print(f"Key en keyring ({KEYRING_SERVICE}/{KEYRING_USER}): {'sí' if key_from_keyring() else 'no'}")
    print(f"Key en .env ({ENV_PATH}): {'sí' if _env_has_key() else 'no'}")
    try:
        print(f"El servidor usará la key de: {load_settings().key_source}")
    except ConfigError as exc:
        print(f"[CONFIG] {exc}")
    return 0


def borrar() -> int:
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        print("Key eliminada del keyring. El servidor volverá a usar .env si tiene una.")
    except keyring.errors.PasswordDeleteError:
        print("No había ninguna key guardada en el keyring.")
    return 0


def guardar() -> int:
    api_key = getpass.getpass("Pega la API key de Cloudbeds (no se mostrará) y pulsa Enter: ").strip()
    if not api_key:
        print("No se ingresó ninguna key. No se guardó nada.")
        return 1
    if not api_key.startswith("cbat_"):
        print("Aviso: la key no empieza por 'cbat_'. Se verificará igualmente.")
    try:
        name = asyncio.run(_verify(api_key))
    except CloudbedsError as exc:
        print(f"[ERROR] La key no funcionó, no se guardó: {exc}")
        return 1
    except ConfigError as exc:
        print(f"[CONFIG] Revisa .env antes de guardar la key: {exc}")
        return 1
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, api_key)
    print(f"Key verificada (autorizada por: {name}) y guardada en el keyring.")
    if _env_has_key():
        answer = input(f"¿Borrar la key de {ENV_PATH.name} para que solo quede en el keyring? (s/N): ").strip().lower()
        if answer in ("s", "si", "sí"):
            _clear_env_key()
            print(f"Key borrada de {ENV_PATH.name} (el resto de la configuración se mantiene).")
        else:
            print(f"Se mantiene también en {ENV_PATH.name}. El keyring tiene prioridad.")
    print("Reinicia Claude Desktop para que el servidor use la key del keyring.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Gestiona la API key de Cloudbeds en el keyring del sistema.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--estado", action="store_true", help="muestra de dónde se carga la key (sin mostrarla)")
    group.add_argument("--borrar", action="store_true", help="elimina la key del keyring")
    args = parser.parse_args()
    if args.estado:
        return estado()
    if args.borrar:
        return borrar()
    return guardar()


if __name__ == "__main__":
    sys.exit(main())
