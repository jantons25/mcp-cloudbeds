"""Ubica el claude_desktop_config.json que Claude Desktop realmente lee y agrega el servidor.

Verificado en Windows (Claude Desktop 3.6556): las versiones recientes guardan sus datos en
%LOCALAPPDATA%\\Claude-Data\\claude_<id>\\ y dejan un marcador .user-data-left.* en la ubicación
anterior, cuya config se ignora.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

SERVER_NAME = "cloudbeds"


def venv_python(project_root: Path, platform: str = sys.platform) -> Path:
    if platform.startswith("win"):
        return project_root / ".venv" / "Scripts" / "python.exe"
    return project_root / ".venv" / "bin" / "python"


def server_entry(project_root: Path, platform: str = sys.platform) -> dict[str, Any]:
    """Sin "cwd": Claude Desktop 3.6556 lo borra al reescribir su config (verificado).
    El paquete se encuentra por PYTHONPATH y el .env por ruta absoluta."""
    return {
        "command": str(venv_python(project_root, platform)),
        "args": ["-m", "cloudbeds_mcp.server"],
        "env": {"PYTHONPATH": str(project_root / "src")},
    }


def candidate_config_dirs(env: Mapping[str, str], home: Path, platform: str = sys.platform) -> list[Path]:
    """Carpetas de config en orden de prioridad; la primera que exista es la que lee la app."""
    if platform == "darwin":
        return [home / "Library" / "Application Support" / "Claude"]
    if not platform.startswith("win"):
        return [home / ".config" / "Claude"]
    dirs: list[Path] = []
    local, roaming = env.get("LOCALAPPDATA"), env.get("APPDATA")
    if local:
        data = Path(local) / "Claude-Data"
        if data.is_dir():
            dirs += sorted(p for p in data.glob("claude_*") if p.is_dir())
        packages = Path(local) / "Packages"
        if packages.is_dir():
            for pkg in sorted(packages.glob("Claude_*")):
                legacy = pkg / "LocalCache" / "Roaming" / "Claude"
                if legacy.is_dir() and not any(legacy.glob(".user-data-left*")):
                    dirs.append(legacy)
    if roaming:
        legacy = Path(roaming) / "Claude"
        if not (legacy.is_dir() and any(legacy.glob(".user-data-left*"))):
            dirs.append(legacy)
    return dirs


def find_config(env: Mapping[str, str], home: Path, platform: str = sys.platform) -> tuple[Path | None, list[Path]]:
    """Devuelve (config elegida, candidatas). None si hay varias carpetas Claude-Data (ambiguo)."""
    dirs = candidate_config_dirs(env, home, platform)
    data_dirs = [d for d in dirs if d.parent.name == "Claude-Data"]
    if len(data_dirs) > 1:
        return None, [d / "claude_desktop_config.json" for d in data_dirs]
    existing = [d for d in dirs if d.is_dir()]
    chosen = (existing or dirs or [None])[0]
    return (chosen / "claude_desktop_config.json" if chosen else None), [d / "claude_desktop_config.json" for d in dirs]


def merge(config: dict[str, Any], entry: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Agrega o reemplaza mcpServers.cloudbeds sin tocar el resto. Devuelve (config, cambió)."""
    servers = config.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    if servers.get(SERVER_NAME) == entry:
        return config, False
    new = dict(config)
    new["mcpServers"] = {**servers, SERVER_NAME: entry}
    return new, True


def apply(path: Path, entry: dict[str, Any]) -> tuple[bool, Path | None]:
    """Escribe la config (con backup si existía). Devuelve (cambió, ruta del backup)."""
    raw = path.read_bytes() if path.exists() else b""
    bom = raw.startswith(b"\xef\xbb\xbf")
    current = json.loads(raw.decode("utf-8-sig")) if raw.strip() else {}
    new, changed = merge(current, entry)
    if not changed:
        return False, None
    backup = None
    if path.exists():
        backup = path.with_name(f"claude_desktop_config.backup-{datetime.now():%Y%m%d-%H%M%S}.json")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(new, indent=2, ensure_ascii=False) + "\n"
    path.write_bytes(("﻿" if bom else "").encode("utf-8") + text.encode("utf-8"))
    json.loads(path.read_bytes().decode("utf-8-sig"))  # verificación de JSON válido
    return True, backup
