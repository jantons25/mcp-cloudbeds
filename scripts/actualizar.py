"""Actualiza el MCP de Cloudbeds a la última versión del repositorio (git pull).

Uso (desde la raíz del proyecto):
    Windows: .\\.venv\\Scripts\\python.exe scripts\\actualizar.py            actualiza
             .\\.venv\\Scripts\\python.exe scripts\\actualizar.py --probar   actualiza y prueba la conexión
    macOS:   ./.venv/bin/python scripts/actualizar.py [--probar]

No toca .env, hoteles.json ni las keys del keyring. Si hay archivos del proyecto modificados
en esta PC, se detiene sin cambiar nada. Al terminar hay que reiniciar Claude desde la bandeja.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cloudbeds_mcp.updater import run_update  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Actualiza el MCP de Cloudbeds con git pull.")
    parser.add_argument("--probar", action="store_true", help="ejecuta la prueba de conexión al terminar")
    args = parser.parse_args()
    return run_update(ROOT, python=Path(sys.executable), probar=args.probar)


if __name__ == "__main__":
    sys.exit(main())
