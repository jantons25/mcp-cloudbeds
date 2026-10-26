"""Actualización por git pull (fase 3), con repositorios git reales en una carpeta temporal."""

import shutil
import subprocess
from pathlib import Path

import pytest

from cloudbeds_mcp.updater import run_update

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git no está instalado")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """origen (GitHub), dev (Tecnología) y gerente (clon de la PC del gerente)."""
    for var, val in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(var, val)
    origen, dev, gerente = tmp_path / "origen.git", tmp_path / "dev", tmp_path / "gerente"
    git(tmp_path, "init", "--bare", "-b", "main", str(origen))
    git(tmp_path, "clone", str(origen), str(dev))
    (dev / "requirements.txt").write_text("httpx\n", encoding="utf-8")
    (dev / "README.md").write_text("v1\n", encoding="utf-8")
    (dev / ".gitignore").write_text(".env\nhoteles.json\n", encoding="utf-8")
    git(dev, "add", ".")
    git(dev, "commit", "-m", "v1")
    git(dev, "push", "origin", "HEAD:main")
    git(tmp_path, "clone", str(origen), str(gerente))
    return dev, gerente


def publicar(dev, archivo, contenido, mensaje):
    (dev / archivo).write_text(contenido, encoding="utf-8")
    git(dev, "commit", "-am", mensaje)
    git(dev, "push", "origin", "HEAD:main")


class Runner:
    """git de verdad; Python (pip, import, smoke test) simulado y registrado."""

    def __init__(self, fallar=()):
        self.python_calls = []
        self.fallar = fallar

    def __call__(self, cmd, **kwargs):
        if cmd[0] == "git":
            return subprocess.run(cmd, **kwargs)
        self.python_calls.append(cmd[1:])
        code = 1 if any(f in " ".join(cmd) for f in self.fallar) else 0
        return subprocess.CompletedProcess(cmd, code, "", "Traceback\nImportError: algo")


def run(gerente, runner, **kw):
    lines = []
    code = run_update(gerente, python=Path("python"), runner=runner, out=lines.append, **kw)
    return code, "\n".join(lines)


def test_ya_actualizado(repos):
    _, gerente = repos
    runner = Runner()
    code, out = run(gerente, runner)
    assert code == 0 and "Ya tenías la última versión" in out
    assert runner.python_calls == []


def test_actualiza_y_verifica_que_arranque(repos):
    dev, gerente = repos
    publicar(dev, "README.md", "v2\n", "mejora del README")
    runner = Runner()
    code, out = run(gerente, runner)
    assert code == 0
    assert "1 cambio(s) nuevo(s)" in out and "mejora del README" in out and "bandeja" in out
    assert (gerente / "README.md").read_text(encoding="utf-8") == "v2\n"
    assert runner.python_calls == [["-c", "import cloudbeds_mcp.server"]]  # sin pip: no cambió requirements


def test_reinstala_dependencias_si_cambian(repos):
    dev, gerente = repos
    publicar(dev, "requirements.txt", "httpx\nkeyring\n", "nueva dependencia")
    runner = Runner()
    code, out = run(gerente, runner, probar=True)
    assert code == 0 and "instalando" in out
    assert runner.python_calls[0][:4] == ["-m", "pip", "install", "-r"]
    assert runner.python_calls[-1][0].endswith("smoke_test.py")


def test_conserva_la_configuracion_de_la_pc(repos):
    dev, gerente = repos
    (gerente / ".env").write_text("CLOUDBEDS_SHOW_PII=false\n", encoding="utf-8")
    (gerente / "hoteles.json").write_text("{}", encoding="utf-8")
    publicar(dev, "README.md", "v2\n", "v2")
    code, _ = run(gerente, Runner())
    assert code == 0
    assert (gerente / ".env").exists() and (gerente / "hoteles.json").read_text(encoding="utf-8") == "{}"


def test_no_toca_nada_si_hay_cambios_locales(repos):
    dev, gerente = repos
    publicar(dev, "README.md", "v2\n", "v2")
    (gerente / "README.md").write_text("editado a mano\n", encoding="utf-8")
    code, out = run(gerente, Runner())
    assert code == 1 and "[ALTO]" in out and "README.md" in out
    assert (gerente / "README.md").read_text(encoding="utf-8") == "editado a mano\n"


def test_historia_divergente_no_se_fusiona(repos):
    dev, gerente = repos
    publicar(dev, "README.md", "v2\n", "v2")
    (gerente / "otro.txt").write_text("x\n", encoding="utf-8")
    git(gerente, "add", "otro.txt")
    git(gerente, "commit", "-m", "commit local")
    code, out = run(gerente, Runner())
    assert code == 1 and "No se pudo actualizar" in out


def test_version_nueva_que_no_arranca(repos):
    dev, gerente = repos
    publicar(dev, "README.md", "v2\n", "v2")
    code, out = run(gerente, Runner(fallar=("import cloudbeds_mcp.server",)))
    assert code == 1 and "no arranca" in out and "ImportError" in out


def test_falla_pip(repos):
    dev, gerente = repos
    publicar(dev, "requirements.txt", "otra\n", "deps")
    code, out = run(gerente, Runner(fallar=("pip",)))
    assert code == 1 and "dependencias" in out


def test_carpeta_que_no_es_clon(tmp_path):
    code, out = run(tmp_path, Runner())
    assert code == 1 and "no es un clon de git" in out


def test_git_no_instalado(tmp_path):
    def sin_git(cmd, **kw):
        raise FileNotFoundError("git")

    code, out = run(tmp_path, sin_git)
    assert code == 1 and "Git no está instalado" in out
