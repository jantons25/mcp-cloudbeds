import json

import pytest

from cloudbeds_mcp.config import (
    KEYRING_SERVICE,
    KEYRING_USER,
    LEGACY_ALIAS,
    keyring_user,
    load_catalog,
    load_hotels,
)
from cloudbeds_mcp.errors import ConfigError

VARS = (
    "CLOUDBEDS_API_KEY",
    "CLOUDBEDS_PROPERTY_ID",
    "CLOUDBEDS_SHOW_PII",
    "CLOUDBEDS_TZ",
    "CLOUDBEDS_MAX_RESULTS",
    "CLOUDBEDS_USE_KEYRING",
    "CLOUDBEDS_API_KEY_BALTA",
    "CLOUDBEDS_API_KEY_PLAZA",
    "CLOUDBEDS_API_KEY_SAN_JOSE",
)

ZENTRA = {
    "hoteles": [
        {"alias": "balta", "nombre": "Zentra Balta", "property_id": "111", "moneda": "pen"},
        {"alias": "plaza", "nombre": "Zentra Plaza", "property_id": 222, "tz": "America/Bogota"},
        {"alias": "san_jose", "nombre": "Zentra San José", "property_id": "333", "otros_nombres": ["SJ"]},
    ]
}


@pytest.fixture
def env(monkeypatch, tmp_path):
    for var in VARS:
        monkeypatch.delenv(var, raising=False)
    return tmp_path / ".env"  # no existe: solo cuentan las variables del test


def write(tmp_path, data, name="hoteles.json"):
    path = tmp_path / name
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def keys(memory_keyring, **por_alias):
    for alias, key in por_alias.items():
        memory_keyring.set_password(KEYRING_SERVICE, keyring_user(alias), key)


# ---------- modo legacy ----------

def test_sin_hoteles_json_es_modo_legacy(env, monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDBEDS_API_KEY", "cbat_x")
    monkeypatch.setenv("CLOUDBEDS_PROPERTY_ID", "318358")
    cfg = load_hotels(env, tmp_path / "no_existe.json")
    assert cfg.modo == "legacy"
    (h,) = cfg.hoteles
    assert h.alias == LEGACY_ALIAS and h.nombre is None and h.disponible
    assert h.settings.api_key == "cbat_x" and h.settings.property_id == "318358"


def test_legacy_sin_key_mantiene_el_error_de_siempre(env, tmp_path):
    with pytest.raises(ConfigError, match="guardar_key.py"):
        load_hotels(env, tmp_path / "no_existe.json")


# ---------- catálogo ----------

def test_catalogo_valido(tmp_path):
    cat = load_catalog(write(tmp_path, ZENTRA))
    assert [h.alias for h in cat.hoteles] == ["balta", "plaza", "san_jose"]
    balta, plaza, sj = cat.hoteles
    assert balta.moneda == "PEN" and balta.tz is None
    assert plaza.property_id == "222" and plaza.tz.key == "America/Bogota"
    assert sj.otros_nombres == ("SJ",)
    assert cat.predeterminado is None


def test_catalogo_inexistente_devuelve_none(tmp_path):
    assert load_catalog(tmp_path / "no.json") is None


def test_catalogo_admite_comentarios_y_bom(tmp_path):
    data = {"_comentario": "x", "hoteles": [{"_nota": "y", "alias": "a", "nombre": "A", "property_id": "1"}]}
    path = tmp_path / "hoteles.json"
    path.write_text(json.dumps(data), encoding="utf-8-sig")  # el Bloc de notas puede guardar con BOM
    assert load_catalog(path).hoteles[0].alias == "a"


def hotel(**over):
    base = {"alias": "a", "nombre": "A", "property_id": "1"}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


@pytest.mark.parametrize(
    ("data", "mensaje"),
    [
        ("{no es json", "no es un JSON válido"),
        ([], "debe ser un objeto"),
        ({"hoteles": []}, "al menos un hotel"),
        ({"hoteles": ["x"]}, "debe ser un objeto JSON"),
        ({"hoteles": [hotel(alias="San-Jose")]}, "alias"),
        ({"hoteles": [hotel(alias=None)]}, "alias"),
        ({"hoteles": [hotel(nombre=" ")]}, "nombre"),
        ({"hoteles": [hotel(property_id=None)]}, "property_id"),
        ({"hoteles": [hotel(property_id=True)]}, "property_id"),
        ({"hoteles": [hotel(tz="Marte/Olympus")]}, "zona horaria"),
        ({"hoteles": [hotel(tz=5)]}, "tz"),
        ({"hoteles": [hotel(moneda="soles")]}, "moneda"),
        ({"hoteles": [hotel(otros_nombres="sj")]}, "otros_nombres"),
        ({"hoteles": [hotel(), hotel(property_id="2")]}, "'alias' repetido: a"),
        ({"hoteles": [hotel(), hotel(alias="b")]}, "'property_id' repetido: 1"),
        ({"hoteles": [hotel()], "predeterminado": "zz"}, "predeterminado"),
        ({"hoteles": [hotel()], "extra": 1}, "campo desconocido 'extra'"),
        ({"hoteles": [hotel(ciudad="Lima")]}, "campo desconocido 'ciudad'"),
        ({"hoteles": [hotel(api_key="cbat_x")]}, "nunca van en hoteles.json"),
        ({"hoteles": [hotel()], "nombres_red": [""]}, "nombres_red"),
    ],
)
def test_catalogo_invalido(tmp_path, data, mensaje):
    with pytest.raises(ConfigError, match=mensaje):
        load_catalog(write(tmp_path, data))


def test_error_de_campo_secreto_no_muestra_el_valor(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_catalog(write(tmp_path, {"hoteles": [hotel(api_key="cbat_SECRETA")]}))
    assert "cbat_SECRETA" not in str(exc.value)


# ---------- keys por hotel ----------

def test_tres_hoteles_con_key_en_keyring(env, tmp_path, memory_keyring):
    keys(memory_keyring, balta="cbat_b", plaza="cbat_p", san_jose="cbat_s")
    cfg = load_hotels(env, write(tmp_path, ZENTRA))
    assert cfg.modo == "multi"
    b, p, s = cfg.hoteles
    assert (b.settings.api_key, p.settings.api_key, s.settings.api_key) == ("cbat_b", "cbat_p", "cbat_s")
    assert b.settings.key_source == "keyring"
    assert b.settings.hotel_alias == "balta" and b.settings.hotel_name == "Zentra Balta"
    assert b.settings.property_id == "111" and b.settings.currency == "PEN"
    assert b.settings.tz.key == "America/Lima" and p.settings.tz.key == "America/Bogota"


def test_globales_de_env_aplican_a_todos(env, monkeypatch, tmp_path, memory_keyring):
    keys(memory_keyring, balta="cbat_b", plaza="cbat_p", san_jose="cbat_s")
    monkeypatch.setenv("CLOUDBEDS_SHOW_PII", "true")
    monkeypatch.setenv("CLOUDBEDS_MAX_RESULTS", "50")
    monkeypatch.setenv("CLOUDBEDS_TZ", "America/Santiago")
    cfg = load_hotels(env, write(tmp_path, ZENTRA))
    assert all(h.settings.show_pii and h.settings.max_results == 50 for h in cfg.hoteles)
    assert cfg.hoteles[0].tz.key == "America/Santiago"  # sin tz propia
    assert cfg.hoteles[1].tz.key == "America/Bogota"  # la tz del hotel manda


def test_key_por_variable_de_entorno(env, monkeypatch, tmp_path, memory_keyring):
    keys(memory_keyring, balta="cbat_b", plaza="cbat_p")
    monkeypatch.setenv("CLOUDBEDS_API_KEY_SAN_JOSE", "cbat_env_s")
    s = load_hotels(env, write(tmp_path, ZENTRA)).hoteles[2]
    assert s.settings.api_key == "cbat_env_s" and s.settings.key_source == "env"


def test_keyring_tiene_prioridad_sobre_variable(env, monkeypatch, tmp_path, memory_keyring):
    keys(memory_keyring, balta="cbat_kr", plaza="cbat_p", san_jose="cbat_s")
    monkeypatch.setenv("CLOUDBEDS_API_KEY_BALTA", "cbat_env")
    assert load_hotels(env, write(tmp_path, ZENTRA)).hoteles[0].settings.api_key == "cbat_kr"


def test_key_legacy_solo_para_el_hotel_de_property_id(env, monkeypatch, tmp_path, memory_keyring):
    memory_keyring.set_password(KEYRING_SERVICE, KEYRING_USER, "cbat_legacy")
    monkeypatch.setenv("CLOUDBEDS_PROPERTY_ID", "111")
    b, p, s = load_hotels(env, write(tmp_path, ZENTRA)).hoteles
    assert b.settings.api_key == "cbat_legacy" and b.settings.key_source == "keyring"
    assert not p.disponible and not s.disponible


def test_key_legacy_con_un_solo_hotel(env, monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDBEDS_API_KEY", "cbat_legacy")
    (h,) = load_hotels(env, write(tmp_path, {"hoteles": [hotel()]})).hoteles
    assert h.settings.api_key == "cbat_legacy" and h.settings.key_source == ".env"


def test_key_propia_gana_a_la_legacy(env, monkeypatch, tmp_path, memory_keyring):
    keys(memory_keyring, balta="cbat_propia")
    monkeypatch.setenv("CLOUDBEDS_API_KEY", "cbat_legacy")
    monkeypatch.setenv("CLOUDBEDS_PROPERTY_ID", "111")
    assert load_hotels(env, write(tmp_path, ZENTRA)).hoteles[0].settings.api_key == "cbat_propia"


def test_hotel_sin_key_no_tumba_a_los_demas(env, tmp_path, memory_keyring, caplog):
    keys(memory_keyring, balta="cbat_b", plaza="cbat_p")
    b, p, s = load_hotels(env, write(tmp_path, ZENTRA)).hoteles
    assert b.disponible and p.disponible
    assert not s.disponible and s.settings is None
    assert "agregar_hotel.py --alias san_jose" in s.motivo
    assert s.property_id == "333" and s.nombre == "Zentra San José"
    assert "san_jose sin API key" in caplog.text


def test_ningun_hotel_con_key_es_error(env, tmp_path):
    with pytest.raises(ConfigError, match="Ningún hotel"):
        load_hotels(env, write(tmp_path, ZENTRA))


def test_keyring_desactivado_usa_variables(env, monkeypatch, tmp_path, memory_keyring):
    keys(memory_keyring, balta="cbat_kr")
    monkeypatch.setenv("CLOUDBEDS_USE_KEYRING", "false")
    monkeypatch.setenv("CLOUDBEDS_API_KEY_BALTA", "cbat_env")
    b = load_hotels(env, write(tmp_path, ZENTRA)).hoteles[0]
    assert b.settings.api_key == "cbat_env"


def test_aviso_si_la_key_no_parece_de_cloudbeds(env, tmp_path, memory_keyring, caplog):
    keys(memory_keyring, balta="otra_cosa")
    load_hotels(env, write(tmp_path, ZENTRA))
    assert "La API key de balta no empieza por 'cbat_'" in caplog.text
    assert "otra_cosa" not in caplog.text


def test_globales_invalidos_fallan_en_multi(env, monkeypatch, tmp_path, memory_keyring):
    keys(memory_keyring, balta="cbat_b")
    monkeypatch.setenv("CLOUDBEDS_MAX_RESULTS", "0")
    with pytest.raises(ConfigError, match="CLOUDBEDS_MAX_RESULTS"):
        load_hotels(env, write(tmp_path, ZENTRA))


def test_repr_no_expone_ninguna_key(env, tmp_path, memory_keyring):
    keys(memory_keyring, balta="cbat_SECRETA_b", plaza="cbat_SECRETA_p", san_jose="cbat_SECRETA_s")
    cfg = load_hotels(env, write(tmp_path, ZENTRA))
    texto = repr(cfg)
    assert "cbat_SECRETA" not in texto
    assert "hotel='balta'" in texto and "nombre='Zentra Balta'" in texto
