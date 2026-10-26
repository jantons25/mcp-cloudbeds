import keyring
import pytest
from keyring.backend import KeyringBackend

from cloudbeds_mcp.config import KEYRING_SERVICE, KEYRING_USER, load_settings
from cloudbeds_mcp.errors import ConfigError

VARS = (
    "CLOUDBEDS_API_KEY",
    "CLOUDBEDS_PROPERTY_ID",
    "CLOUDBEDS_SHOW_PII",
    "CLOUDBEDS_TZ",
    "CLOUDBEDS_MAX_RESULTS",
    "CLOUDBEDS_USE_KEYRING",
)


@pytest.fixture
def empty_env(monkeypatch, tmp_path):
    for var in VARS:
        monkeypatch.delenv(var, raising=False)
    return tmp_path / ".env"  # no existe: solo cuentan las variables del test


def test_falta_api_key(empty_env):
    with pytest.raises(ConfigError, match="CLOUDBEDS_API_KEY"):
        load_settings(empty_env)


def test_valores_por_defecto(empty_env, monkeypatch):
    monkeypatch.setenv("CLOUDBEDS_API_KEY", "cbat_x")
    s = load_settings(empty_env)
    assert s.property_id is None
    assert s.show_pii is False
    assert s.tz.key == "America/Lima"
    assert s.max_results == 500


def test_repr_no_expone_la_key(empty_env, monkeypatch):
    monkeypatch.setenv("CLOUDBEDS_API_KEY", "cbat_secreta")
    assert "cbat_secreta" not in repr(load_settings(empty_env))


def test_lee_archivo_env(empty_env):
    empty_env.write_text("CLOUDBEDS_API_KEY=cbat_desde_archivo\nCLOUDBEDS_SHOW_PII=true\n", encoding="utf-8")
    s = load_settings(empty_env)
    assert s.api_key == "cbat_desde_archivo"
    assert s.show_pii is True


@pytest.mark.parametrize(
    ("var", "value"),
    [("CLOUDBEDS_TZ", "Marte/Olympus"), ("CLOUDBEDS_MAX_RESULTS", "abc"), ("CLOUDBEDS_MAX_RESULTS", "0"), ("CLOUDBEDS_MAX_RESULTS", "5001"), ("CLOUDBEDS_SHOW_PII", "quizas")],
)
def test_valores_invalidos(empty_env, monkeypatch, var, value):
    monkeypatch.setenv("CLOUDBEDS_API_KEY", "cbat_x")
    monkeypatch.setenv(var, value)
    with pytest.raises(ConfigError):
        load_settings(empty_env)


# ---------- keyring ----------

def test_keyring_tiene_prioridad_sobre_env(empty_env, monkeypatch, memory_keyring):
    monkeypatch.setenv("CLOUDBEDS_API_KEY", "cbat_de_env")
    memory_keyring.set_password(KEYRING_SERVICE, KEYRING_USER, "cbat_de_keyring")
    s = load_settings(empty_env)
    assert s.api_key == "cbat_de_keyring" and s.key_source == "keyring"
    assert "cbat_de_keyring" not in repr(s) and "keyring" in repr(s)


def test_sin_keyring_usa_env(empty_env, monkeypatch):
    monkeypatch.setenv("CLOUDBEDS_API_KEY", "cbat_de_env")
    s = load_settings(empty_env)
    assert s.api_key == "cbat_de_env" and s.key_source == ".env"


def test_keyring_desactivado(empty_env, monkeypatch, memory_keyring):
    memory_keyring.set_password(KEYRING_SERVICE, KEYRING_USER, "cbat_de_keyring")
    monkeypatch.setenv("CLOUDBEDS_USE_KEYRING", "false")
    monkeypatch.setenv("CLOUDBEDS_API_KEY", "cbat_de_env")
    assert load_settings(empty_env).key_source == ".env"


def test_keyring_con_error_cae_a_env(empty_env, monkeypatch, caplog):
    class Roto(KeyringBackend):
        priority = 1

        def get_password(self, service, username):
            raise RuntimeError("backend bloqueado")

        def set_password(self, *a):
            raise RuntimeError

        def delete_password(self, *a):
            raise RuntimeError

    keyring.set_keyring(Roto())
    monkeypatch.setenv("CLOUDBEDS_API_KEY", "cbat_de_env")
    s = load_settings(empty_env)
    assert s.key_source == ".env"
    assert "No se pudo leer el keyring" in caplog.text


def test_keyring_vacio_y_sin_env_mensaje_claro(empty_env, memory_keyring):
    memory_keyring.set_password(KEYRING_SERVICE, KEYRING_USER, "   ")
    with pytest.raises(ConfigError, match="guardar_key.py"):
        load_settings(empty_env)


# ---------- logging ----------

def test_configure_logging_un_solo_handler_a_stderr():
    import logging
    import sys

    from cloudbeds_mcp import server  # importar server instala el RichHandler de FastMCP
    from cloudbeds_mcp.config import configure_logging

    assert server.mcp is not None
    root = logging.getLogger()
    saved = list(root.handlers)
    try:
        root.addHandler(logging.StreamHandler(sys.stdout))  # simula un handler ajeno
        configure_logging()
        configure_logging()  # idempotente
        assert len(root.handlers) == 1
        handler = root.handlers[0]
        assert handler.stream is sys.stderr
        assert handler.formatter._fmt == "%(asctime)s %(levelname)s %(name)s: %(message)s"
        assert logging.getLogger("httpx").level == logging.WARNING
    finally:
        root.handlers[:] = saved
