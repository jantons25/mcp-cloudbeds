"""Agrega el servidor 'cloudbeds' a la config de Claude Desktop (Windows y macOS).

Uso (desde la raíz del proyecto):
    Windows: .\\.venv\\Scripts\\python.exe scripts\\configurar_claude.py            muestra qué haría
             .\\.venv\\Scripts\\python.exe scripts\\configurar_claude.py --aplicar  escribe la config
    macOS:   ./.venv/bin/python scripts/configurar_claude.py [--aplicar]
Opcional: --config <ruta> para indicar el archivo a mano.

Detecta el archivo que Claude Desktop realmente lee, guarda un backup, conserva el resto de la
configuración y verifica que el servidor arranque antes de escribir.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cloudbeds_mcp.desktop_config import apply, find_config, server_entry, venv_python  # noqa: E402


def _check_server(entry: dict) -> str | None:
    """Comprueba con el Python del entorno virtual que el paquete se importa. None = OK."""
    python = Path(entry["command"])
    if not python.exists():
        return f"No existe el Python del entorno virtual: {python}. Crea el entorno con 'python -m venv .venv'."
    env = {**os.environ, **entry["env"]}
    proc = subprocess.run(
        [str(python), "-c", "import cloudbeds_mcp.server"], cwd=str(Path.home()), env=env,
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        last = (proc.stderr.strip().splitlines() or ["error desconocido"])[-1]
        return f"El servidor no se pudo importar: {last}. ¿Instalaste 'pip install -r requirements.txt'?"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Configura Claude Desktop para usar el MCP de Cloudbeds.")
    parser.add_argument("--aplicar", action="store_true", help="escribe la config (sin esto solo muestra qué haría)")
    parser.add_argument("--config", type=Path, help="ruta explícita de claude_desktop_config.json")
    args = parser.parse_args()

    entry = server_entry(ROOT)
    if args.config:
        path, candidates = args.config, [args.config]
    else:
        path, candidates = find_config(os.environ, Path.home())
    if path is None:
        print("Hay varias carpetas de datos de Claude; indica cuál con --config:")
        for c in candidates:
            print(f"  {c}")
        return 2

    print(f"Config de Claude Desktop: {path}{'' if path.exists() else ' (se creará)'}")
    print(f"Python del servidor:      {venv_python(ROOT)}")
    problem = _check_server(entry)
    if problem:
        print(f"[ERROR] {problem}")
        return 1
    print("El servidor se importa correctamente.")

    if path.exists():
        try:
            current = json.loads(path.read_bytes().decode("utf-8-sig") or "{}")
        except ValueError:
            print("[ERROR] La config actual no es un JSON válido. Corrígela o restaura un backup antes de continuar.")
            return 1
        if (current.get("mcpServers") or {}).get("cloudbeds") == entry:
            print("Ya está configurado. No hay cambios.")
            return 0

    if not args.aplicar:
        print("\nSe agregaría este servidor (el resto de la config se conserva):")
        print(json.dumps({"cloudbeds": entry}, indent=2, ensure_ascii=False))
        print("\nEjecuta de nuevo con --aplicar para escribirlo.")
        return 0

    changed, backup = apply(path, entry)
    if backup:
        print(f"Backup guardado: {backup}")
    print("Configuración escrita." if changed else "Ya estaba configurado.")
    print("Ahora cierra Claude Desktop por completo (ícono de la bandeja → Salir) y vuelve a abrirlo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
