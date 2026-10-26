"""Actualiza la instalación con `git pull` (lo usa scripts/actualizar.py).

Pensado para la PC del gerente: no toca nada si hay cambios locales en archivos del
repositorio, solo avanza en línea recta (--ff-only), reinstala dependencias si cambió
requirements.txt y comprueba que el servidor se importe antes de pedir el reinicio.
.env y hoteles.json no están en git, así que la configuración de la PC se conserva.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .desktop_config import venv_python

Runner = Callable[..., subprocess.CompletedProcess]
Printer = Callable[[str], Any]

REINICIO = (
    "Para usar la versión nueva, cierra Claude por completo: clic derecho en el ícono de la "
    "bandeja → Salir (en macOS, Cmd+Q), y vuelve a abrirlo."
)


def _git(root: Path, runner: Runner, *args: str) -> subprocess.CompletedProcess:
    return runner(["git", "-C", str(root), *args], capture_output=True, text=True)


def _last_line(text: str) -> str:
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    return lines[-1] if lines else "error desconocido"


def run_update(
    root: Path,
    *,
    python: Path | None = None,
    probar: bool = False,
    runner: Runner = subprocess.run,
    out: Printer = print,
) -> int:
    """Devuelve 0 si quedó actualizado (o ya lo estaba) y 1 si algo impidió actualizar."""
    try:
        repo = _git(root, runner, "rev-parse", "--show-toplevel")
    except FileNotFoundError:
        out("[ERROR] Git no está instalado. Instálalo desde https://git-scm.com y vuelve a intentarlo.")
        return 1
    # La carpeta del proyecto debe ser la raíz del clon, no estar dentro de otro repositorio.
    if repo.returncode != 0 or Path(repo.stdout.strip()).resolve() != root.resolve():
        out(f"[ERROR] {root} no es un clon de git. Reinstala con 'git clone' (CHECKLIST_INSTALACION.md, sección B).")
        return 1

    cambios = _git(root, runner, "status", "--porcelain", "--untracked-files=no").stdout.strip()
    if cambios:
        out("[ALTO] Hay archivos del proyecto modificados en esta PC; no se actualizó nada para no perderlos:")
        for line in cambios.splitlines():
            out(f"  {line.strip()}")
        out("Avisa a Tecnología.")
        return 1

    antes = _git(root, runner, "rev-parse", "HEAD").stdout.strip()
    out("Descargando la última versión...")
    pull = _git(root, runner, "pull", "--ff-only")
    if pull.returncode != 0:
        out(f"[ERROR] No se pudo actualizar: {_last_line(pull.stderr or pull.stdout)}")
        out("Revisa la conexión a internet o avisa a Tecnología.")
        return 1
    despues = _git(root, runner, "rev-parse", "HEAD").stdout.strip()
    if despues == antes:
        out("Ya tenías la última versión. No hace falta reiniciar Claude.")
        return 0

    cambiados = _git(root, runner, "diff", "--name-only", antes, despues).stdout.split()
    log = _git(root, runner, "log", "--oneline", f"{antes}..{despues}").stdout.strip()
    out(f"Actualizado: {len(log.splitlines()) if log else 0} cambio(s) nuevo(s).")
    for line in log.splitlines()[:10]:
        out(f"  {line}")

    python = python or venv_python(root)
    if "requirements.txt" in cambiados:
        out("Cambiaron las dependencias: instalando...")
        pip = runner([str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt")], capture_output=True, text=True)
        if pip.returncode != 0:
            out(f"[ERROR] Falló la instalación de dependencias: {_last_line(pip.stderr)}")
            return 1

    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    check = runner([str(python), "-c", "import cloudbeds_mcp.server"], capture_output=True, text=True, env=env, cwd=str(root))
    if check.returncode != 0:
        out(f"[ERROR] La versión nueva no arranca: {_last_line(check.stderr)}. Avisa a Tecnología.")
        return 1

    if probar:
        out("\nPrueba de conexión con Cloudbeds:")
        smoke = runner([str(python), str(root / "scripts" / "smoke_test.py")], env=env, cwd=str(root))
        if smoke.returncode != 0:
            out("[AVISO] La prueba de conexión falló; revisa los mensajes de arriba.")

    out(f"\nListo. {REINICIO}")
    return 0
