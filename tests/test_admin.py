"""Alta de hoteles (fase 3): lógica de admin.py y el script agregar_hotel.py."""

import importlib.util
import json
from pathlib import Path

import pytest

from cloudbeds_mcp import admin
from cloudbeds_mcp.config import KEYRING_SERVICE, KEYRING_USER, keyring_user, load_catalog
from cloudbeds_mcp.errors import ConfigError

ROOT = Path(__file__).resolve().parents[1]

PLAZA = {
    "propertyID": 222,
    "propertyName": "Zentra Plaza",
    "propertyTimezone": "America/Lima",
    "propertyCurrency": [{"currencyCode": "pen", "currencySymbol": "S/"}],
}


# ---------- datos de Cloudbeds ----------

@pytest.mark.parametrize(
    ("value", "esperado"),
    [({"currencyCode": "PEN"}, "PEN"), ([{"currencyCode": "usd"}], "USD"), ("eur", "EUR"), ([], None), ("  ", None), (5, None)],
)
def test_currency_code(value, esperado):
    assert admin.currency_code(value) == esperado


def test_valid_tz():
    assert admin.valid_tz(" America/Lima ") == "America/Lima"
    assert admin.valid_tz("Marte/Olympus") is None
    assert admin.valid_tz(None) is None


@pytest.mark.parametrize(
    ("nombre", "otros", "alias"),
    [
        ("Zentra Balta", [], "balta"),
        ("Zentra San José", ["Zentra Balta"], "san_jose"),
        ("Zentra Plaza", ["Zentra Balta", "Zentra San José"], "plaza"),
        ("Balta", [], "balta"),
        ("Hotel Sol", [], "sol"),
        ("¡!", [], "hotel"),
    ],
)
def test_suggest_alias(nombre, otros, alias):
    assert admin.suggest_alias(nombre, otros) == alias


def test_entry_from_cloudbeds():
    assert admin.entry_from_cloudbeds("plaza", PLAZA) == {
        "alias": "plaza", "nombre": "Zentra Plaza", "property_id": "222", "tz": "America/Lima", "moneda": "PEN",
    }
    sin_datos = admin.entry_from_cloudbeds("x", {"propertyID": "9", "propertyName": "X", "propertyTimezone": "Nada/Nada"})
    assert "tz" not in sin_datos and "moneda" not in sin_datos
    with pytest.raises(ConfigError, match="alias"):
        admin.entry_from_cloudbeds("San José", PLAZA)


# ---------- escritura de hoteles.json ----------

def test_upsert_crea_y_actualiza_conservando_campos(tmp_path):
    path = tmp_path / "hoteles.json"
    assert admin.upsert_hotel(path, {"alias": "balta", "nombre": "Zentra Balta", "property_id": "111"}) == "agregado"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_comentario"] = "no borrar"
    data["hoteles"][0]["otros_nombres"] = ["el de Balta"]
    path.write_text(json.dumps(data), encoding="utf-8")

    assert admin.upsert_hotel(path, admin.entry_from_cloudbeds("plaza", PLAZA)) == "agregado"
    assert admin.upsert_hotel(path, {"alias": "balta", "nombre": "Zentra Balta", "property_id": "111", "moneda": "PEN"}) == "actualizado"

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["_comentario"] == "no borrar"
    assert data["hoteles"][0] == {"alias": "balta", "nombre": "Zentra Balta", "property_id": "111",
                                  "otros_nombres": ["el de Balta"], "moneda": "PEN"}
    assert [h.alias for h in load_catalog(path).hoteles] == ["balta", "plaza"]
    assert "Zentra Plaza" in path.read_text(encoding="utf-8")  # sin escapar tildes ni nada


def test_upsert_rechaza_propiedad_ya_registrada(tmp_path):
    path = tmp_path / "hoteles.json"
    admin.upsert_hotel(path, {"alias": "balta", "nombre": "Zentra Balta", "property_id": "111"})
    with pytest.raises(ConfigError, match="ya está registrada con el alias 'balta'"):
        admin.upsert_hotel(path, {"alias": "otro", "nombre": "Otro", "property_id": "111"})


def test_upsert_no_toca_un_archivo_invalido(tmp_path):
    path = tmp_path / "hoteles.json"
    path.write_text("{roto", encoding="utf-8")
    with pytest.raises(ConfigError, match="no es un JSON válido"):
        admin.upsert_hotel(path, {"alias": "balta", "nombre": "Zentra Balta", "property_id": "111"})
    assert path.read_text(encoding="utf-8") == "{roto"


def test_upsert_no_escribe_si_el_resultado_es_invalido(tmp_path):
    path = tmp_path / "hoteles.json"
    admin.upsert_hotel(path, {"alias": "balta", "nombre": "Zentra Balta", "property_id": "111"})
    antes = path.read_text(encoding="utf-8")
    with pytest.raises(ConfigError):
        admin.upsert_hotel(path, {"alias": "plaza", "nombre": "", "property_id": "222"})
    assert path.read_text(encoding="utf-8") == antes
    assert [p.name for p in tmp_path.iterdir()] == ["hoteles.json"]  # sin temporales sueltos


def test_remove_hotel(tmp_path):
    path = tmp_path / "hoteles.json"
    path.write_text(json.dumps({"predeterminado": "plaza", "hoteles": [
        {"alias": "balta", "nombre": "Zentra Balta", "property_id": "111"},
        {"alias": "plaza", "nombre": "Zentra Plaza", "property_id": "222"},
    ]}), encoding="utf-8")
    assert admin.remove_hotel(path, "nada") is False
    assert admin.remove_hotel(path, "plaza") is True
    cat = load_catalog(path)
    assert [h.alias for h in cat.hoteles] == ["balta"] and cat.predeterminado is None
    assert admin.remove_hotel(path, "balta") is True
    assert not path.exists()  # sin hoteles se vuelve al modo de un solo hotel (.env)


def test_read_raw_sin_archivo(tmp_path):
    assert admin.read_raw(tmp_path / "no.json") == {"hoteles": []}


# ---------- origen de las keys ----------

@pytest.fixture
def catalog(tmp_path, monkeypatch):
    for var in ("CLOUDBEDS_API_KEY", "CLOUDBEDS_API_KEY_PLAZA", "CLOUDBEDS_USE_KEYRING"):
        monkeypatch.delenv(var, raising=False)
    path = tmp_path / "hoteles.json"
    path.write_text(json.dumps({"hoteles": [
        {"alias": "balta", "nombre": "Zentra Balta", "property_id": "111"},
        {"alias": "plaza", "nombre": "Zentra Plaza", "property_id": "222"},
        {"alias": "san_jose", "nombre": "Zentra San José", "property_id": "333"},
    ]}), encoding="utf-8")
    return load_catalog(path)


def test_key_status(catalog, monkeypatch, memory_keyring):
    memory_keyring.set_password(KEYRING_SERVICE, keyring_user("balta"), "cbat_SECRETA_b")
    monkeypatch.setenv("CLOUDBEDS_API_KEY_PLAZA", "cbat_SECRETA_p")
    rows = admin.key_status(catalog, legacy_property_id=None)
    assert [r["fuente"] for r in rows] == ["keyring (CLOUDBEDS_API_KEY:balta)", "variable CLOUDBEDS_API_KEY_PLAZA", None]
    assert "cbat_SECRETA" not in repr(rows)


def test_key_status_legacy(catalog, memory_keyring):
    memory_keyring.set_password(KEYRING_SERVICE, KEYRING_USER, "cbat_legacy")
    rows = admin.key_status(catalog, legacy_property_id="333")
    assert [r["fuente"] for r in rows] == [None, None, "key legacy (guardar_key.py / .env)"]


# ---------- script agregar_hotel.py ----------

@pytest.fixture
def script(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("agregar_hotel", ROOT / "scripts" / "agregar_hotel.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "HOTELES_PATH", tmp_path / "hoteles.json")
    monkeypatch.setattr(mod, "ENV_PATH", tmp_path / ".env")
    return mod


def fake_cloudbeds(monkeypatch, mod, hotels):
    async def props(api_key):
        assert api_key == "cbat_NUEVA"
        return "Cuenta Institucional", hotels
    monkeypatch.setattr(mod, "_properties", props)
    monkeypatch.setattr(mod.getpass, "getpass", lambda prompt: "cbat_NUEVA")


def answers(monkeypatch, *values):
    it = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


def test_agregar_hotel_completo(script, monkeypatch, memory_keyring, capsys):
    fake_cloudbeds(monkeypatch, script, [PLAZA])
    answers(monkeypatch, "")  # Enter = alias sugerido
    assert script.agregar(None, None) == 0
    assert memory_keyring.get_password(KEYRING_SERVICE, keyring_user("plaza")) == "cbat_NUEVA"
    (h,) = load_catalog(script.HOTELES_PATH).hoteles
    assert (h.alias, h.nombre, h.property_id, h.moneda) == ("plaza", "Zentra Plaza", "222", "PEN")
    salida = capsys.readouterr().out
    assert "cbat_NUEVA" not in salida and "Hotel agregado" in salida and "bandeja" in salida


def test_agregar_elige_entre_varias_propiedades(script, monkeypatch, memory_keyring):
    balta = {"propertyID": "111", "propertyName": "Zentra Balta"}
    fake_cloudbeds(monkeypatch, script, [balta, PLAZA])
    answers(monkeypatch, "2")
    assert script.agregar("plaza", None) == 0
    assert load_catalog(script.HOTELES_PATH).hoteles[0].property_id == "222"


def test_agregar_property_id_no_visible(script, monkeypatch, memory_keyring):
    fake_cloudbeds(monkeypatch, script, [PLAZA])
    assert script.agregar("plaza", "999") == 1
    assert not script.HOTELES_PATH.exists()
    assert memory_keyring.get_password(KEYRING_SERVICE, keyring_user("plaza")) is None


def test_agregar_key_invalida_no_guarda(script, monkeypatch, memory_keyring, capsys):
    from cloudbeds_mcp.errors import AuthError

    async def props(api_key):
        raise AuthError("La API key de Cloudbeds es inválida.")
    monkeypatch.setattr(script, "_properties", props)
    monkeypatch.setattr(script.getpass, "getpass", lambda prompt: "cbat_MALA")
    assert script.agregar("plaza", None) == 1
    assert not script.HOTELES_PATH.exists()
    assert "no se guardó" in capsys.readouterr().out


def test_agregar_alias_existente_pide_confirmar(script, monkeypatch, memory_keyring):
    script.HOTELES_PATH.write_text(json.dumps({"hoteles": [{"alias": "plaza", "nombre": "Zentra Plaza", "property_id": "222"}]}), encoding="utf-8")
    fake_cloudbeds(monkeypatch, script, [PLAZA])
    answers(monkeypatch, "n")
    assert script.agregar("plaza", None) == 1
    assert memory_keyring.get_password(KEYRING_SERVICE, keyring_user("plaza")) is None


def test_estado_y_borrar(script, monkeypatch, memory_keyring, capsys):
    monkeypatch.delenv("CLOUDBEDS_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDBEDS_PROPERTY_ID", raising=False)
    script.HOTELES_PATH.write_text(json.dumps({"hoteles": [
        {"alias": "balta", "nombre": "Zentra Balta", "property_id": "111"},
        {"alias": "plaza", "nombre": "Zentra Plaza", "property_id": "222", "moneda": "PEN"},
    ]}), encoding="utf-8")
    memory_keyring.set_password(KEYRING_SERVICE, keyring_user("plaza"), "cbat_SECRETA")
    assert script.estado() == 1  # falta la key de balta
    salida = capsys.readouterr().out
    assert "SIN KEY" in salida and "Falta la key de: balta" in salida and "cbat_SECRETA" not in salida

    answers(monkeypatch, "s")
    assert script.borrar("plaza") == 0
    assert memory_keyring.get_password(KEYRING_SERVICE, keyring_user("plaza")) is None
    assert [h.alias for h in load_catalog(script.HOTELES_PATH).hoteles] == ["balta"]


def test_estado_sin_hoteles_json(script, capsys):
    assert script.estado() == 0
    assert "modo de un solo hotel" in capsys.readouterr().out
