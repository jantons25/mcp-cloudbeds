"""Flujo diario del desglose de Booking (pendientes -> agregar -> cargar) con un Cloudbeds simulado."""

import csv
import importlib.util
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from cloudbeds_mcp import desglose as dg
from cloudbeds_mcp.errors import HotelError

RAIZ = Path(__file__).resolve().parents[1]
BK = "6280864979"
CB = "2608443502551"
HOY = date(2026, 11, 28)  # la tarea corre el 28 a la 1:00 a. m.: la noche a revisar es la del 27


def _script():
    spec = importlib.util.spec_from_file_location("desglose_booking_diario", RAIZ / "scripts" / "desglose_booking.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeClient:
    def __init__(self):
        self.settings = SimpleNamespace(property_id="1")
        self.reservas = []
        self.detalles = {}
        self.notas = {}
        self.escrituras = []

    def agregar(self, cb_id, bk, inicio, fin, status="confirmed", fuente="Booking.com"):
        self.reservas.append({"reservationID": cb_id, "thirdPartyIdentifier": bk, "status": status,
                              "sourceName": fuente, "startDate": inicio, "endDate": fin})
        self.detalles[cb_id] = {"startDate": inicio, "endDate": fin, "customFields": [],
                                "assigned": [{"roomTypeName": "Doble Standard", "startDate": inicio, "endDate": fin}]}

    def cambiar(self, cb_id, **kw):
        for r in self.reservas:
            if r["reservationID"] == cb_id:
                r.update(kw)
        d = self.detalles[cb_id]
        d.update({k: v for k, v in kw.items() if k in ("startDate", "endDate")})
        d["assigned"][0].update({k: v for k, v in kw.items() if k in ("startDate", "endDate")})

    async def get_all(self, endpoint, params, max_results=None):
        assert endpoint == "getReservations"
        return {"data": [dict(r) for r in self.reservas if r["endDate"] >= params["checkOutFrom"]], "truncado": False}

    async def get(self, endpoint, params):
        rid = params.get("reservationID")
        if endpoint == "getReservation":
            return {"data": self.detalles[rid]}
        if endpoint == "getReservationNotes":
            return {"data": [{"reservationNote": n} for n in self.notas.get(rid, [])]}
        if endpoint == "getCustomFields":
            return {"data": [{"shortcode": s} for s, _ in dg.CAMPOS_BOOKING.values()]}
        raise AssertionError(endpoint)

    async def write(self, endpoint, data):
        self.escrituras.append(endpoint)
        rid = data["reservationID"]
        if endpoint == "putReservation":
            self.detalles[rid]["customFields"] = [
                {"shortcode": f["customFieldName"], "customFieldValue": f["customFieldValue"]} for f in data["customFields"]]
        elif endpoint == "postReservationNote":
            self.notas.setdefault(rid, []).append(data["reservationNote"])
        return {"success": True}


class FakeReg:
    hoteles = [SimpleNamespace(alias="balta", nombre="Zentra Balta")]

    def __init__(self, client):
        self._client = client

    def hotel(self, texto):
        if "balta" in dg._norm(texto):
            return self.hoteles[0]
        raise HotelError(f"No conozco {texto}")

    def client(self, alias):
        return self._client

    async def aclose(self):
        pass


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    mod = _script()
    client = FakeClient()
    monkeypatch.setattr(mod, "HotelRegistry", lambda cfg: FakeReg(client))
    monkeypatch.setattr(mod, "load_hotels", lambda: None)
    monkeypatch.setattr(mod, "_hoy", lambda: HOY)
    carpeta = tmp_path / "booking"
    carpeta.mkdir()

    def correr(*args):
        extra = ["--carpeta", str(carpeta)]
        if args[0] == "cargar":
            extra += ["--logs", str(tmp_path / "logs")]
        return mod.main([*args, *extra])

    return SimpleNamespace(mod=mod, client=client, carpeta=carpeta, correr=correr, tmp=tmp_path)


def _lectura(e, noches=("2026-11-27",), bk=BK, nombre="lectura.csv"):
    path = e.tmp / nombre
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[*dg.COLUMNAS, "comision_informada_usd"])
        w.writeheader()
        for i, n in enumerate(noches):
            w.writerow({"hotel": "Zentra Balta", "reserva_booking": bk, "habitacion_booking": "Standard Doble",
                        "tipo_cloudbeds": "Doble Standard", "noche": n, "plan": "No reembolsable", "tarifa_base_cb": "150",
                        "promocion": "Mobile Rate", "promo1": "0.1", "genius_pct": "0.25", "genius_tipo": "Dinámico",
                        "subtotal_usd": "33.53", "comision_pct": "0.23",
                        "comision_informada_usd": "7.71" if i == 0 else ""})
    return path


def _pendientes(e):
    path = e.carpeta / f"pendientes_{HOY}.csv"
    return list(csv.DictReader(path.open(encoding="utf-8")))


def test_flujo_completo(entorno):
    e = entorno
    e.client.agregar(CB, BK, "2026-11-27", "2026-11-28")
    e.client.agregar("999", "1111111111", "2026-11-27", "2026-11-28", fuente="Website/Booking Engine")
    e.client.agregar("998", "2222222222", "2026-11-20", "2026-11-25")  # ya salió: fuera de la ventana
    e.client.agregar("997", "3333333333", "2027-03-10", "2027-03-12")  # futura

    assert e.correr("pendientes") == 0
    assert {(f["reserva_booking"], f["motivo"]) for f in _pendientes(e)} == {(BK, "nueva"), ("3333333333", "nueva")}

    assert e.correr("agregar", "--lectura", str(_lectura(e)), "--k", "3.43") == 0
    assert (e.carpeta / "noches_2026-11.csv").exists() and (e.carpeta / "reporte_booking_2026-11.xlsx").exists()
    assert e.correr("pendientes") == 0
    assert [f["reserva_booking"] for f in _pendientes(e)] == ["3333333333"]

    assert e.correr("cargar") == 0  # vista previa
    assert e.client.escrituras == []
    assert e.correr("cargar", "--confirmar") == 0
    assert e.client.escrituras == ["putReservation", "postReservationNote"]
    campos = {f["shortcode"]: f["customFieldValue"] for f in e.client.detalles[CB]["customFields"]}
    assert campos["bk_neto"] == "US$ 25.82 (52 % del original)"
    assert json.loads((e.carpeta / "estado.json").read_text(encoding="utf-8"))["ultima_noche_ok"] == "2026-11-27"

    e.client.escrituras.clear()
    assert e.correr("cargar", "--confirmar") == 0  # misma corrida: no duplica nada
    assert e.client.escrituras == []

    e.client.notas[CB] = []  # la nota no llegó a escribirse: se reintenta sola
    assert e.correr("cargar", "--confirmar") == 0
    assert e.client.escrituras == ["postReservationNote"]


def test_modificada_en_cloudbeds_se_vuelve_a_leer(entorno):
    e = entorno
    e.client.agregar(CB, BK, "2026-11-27", "2026-11-28")
    e.correr("pendientes")
    e.correr("agregar", "--lectura", str(_lectura(e)), "--k", "3.43")
    e.client.cambiar(CB, endDate="2026-11-29")  # el huésped agregó una noche en Booking

    assert e.correr("cargar", "--confirmar") == 0
    assert e.client.escrituras == []  # no escribe datos viejos
    assert e.correr("pendientes") == 0
    assert [(f["reserva_booking"], f["motivo"]) for f in _pendientes(e)] == [(BK, "modificada")]

    e.correr("agregar", "--lectura", str(_lectura(e, noches=("2026-11-27", "2026-11-28"))))  # K del Excel del mes
    assert e.correr("cargar", "--confirmar") == 0
    assert e.client.escrituras == ["putReservation", "postReservationNote"]
    campos = {f["shortcode"]: f["customFieldValue"] for f in e.client.detalles[CB]["customFields"]}
    assert "en 2 noches" in campos["bk_subtotal"]


def test_diferencia_solo_en_cloudbeds_se_acepta_tras_releer(entorno):
    e = entorno
    e.client.agregar(CB, BK, "2026-11-27", "2026-11-28")
    e.client.cambiar(CB, endDate="2026-11-29")  # recepción extendió en Cloudbeds; Booking sigue con 1 noche
    e.correr("pendientes")
    e.correr("agregar", "--lectura", str(_lectura(e)), "--k", "3.43")
    assert e.correr("pendientes") == 0
    assert _pendientes(e) == []  # no se vuelve a leer cada día
    assert e.correr("cargar", "--confirmar") == 0
    assert e.client.escrituras == ["putReservation", "postReservationNote"]


def test_cancelada_deja_nota_y_sale_del_reporte(entorno):
    e = entorno
    e.client.agregar(CB, BK, "2026-11-29", "2026-11-30")
    e.correr("pendientes")
    e.correr("agregar", "--lectura", str(_lectura(e, noches=("2026-11-29",))), "--k", "3.43")
    e.correr("cargar", "--confirmar")
    e.client.escrituras.clear()
    e.client.cambiar(CB, status="canceled")

    assert e.correr("cargar") == 0  # vista previa: no escribe ni mueve archivos
    assert e.client.escrituras == [] and (e.carpeta / "reporte_booking_2026-11.xlsx").exists()
    assert e.correr("cargar", "--confirmar") == 0
    assert e.client.escrituras == ["postReservationNote"]
    nota = e.client.notas[CB][-1]
    assert nota.startswith(dg.encabezado_anulacion(BK)) and "NO considerar como ingreso" in nota
    assert "US$ 25.82" in nota
    assert not (e.carpeta / "reporte_booking_2026-11.xlsx").exists()
    assert BK in (e.carpeta / "canceladas.csv").read_text(encoding="utf-8")
    e.client.escrituras.clear()
    assert e.correr("cargar", "--confirmar") == 0
    assert e.client.escrituras == []


def test_no_encontrada_no_es_error_y_ambigua_se_informa(entorno):
    e = entorno
    e.correr("agregar", "--lectura", str(_lectura(e)), "--k", "3.43")
    assert e.correr("cargar", "--confirmar") == 0  # aún no llega a Cloudbeds: se reintenta mañana
    estado = json.loads((e.carpeta / "estado.json").read_text(encoding="utf-8"))
    assert estado["ultima_noche_ok"] == "2026-11-27"
    e.client.agregar("A1", BK, "2026-11-27", "2026-11-28")
    e.client.agregar("A2", BK, "2026-11-27", "2026-11-28")
    assert e.correr("cargar", "--confirmar") == 0
    assert e.client.escrituras == []


def test_dias_sin_correr_se_recuperan(entorno):
    e = entorno
    assert e.mod._noche_inicio(e.carpeta, None) == date(2026, 11, 27)
    (e.carpeta / "estado.json").write_text(json.dumps({"ultima_noche_ok": "2026-11-24"}), encoding="utf-8")
    assert e.mod._noche_inicio(e.carpeta, None) == date(2026, 11, 25)
    e.client.agregar("998", "2222222222", "2026-11-24", "2026-11-26")  # salió el 26: entra por la recuperación
    assert e.correr("pendientes") == 0
    assert [f["reserva_booking"] for f in _pendientes(e)] == ["2222222222"]


def test_agregar_mueve_de_mes_si_cambia_la_llegada(entorno):
    e = entorno
    e.correr("agregar", "--lectura", str(_lectura(e, noches=("2026-11-30",))), "--k", "3.43")
    assert e.correr("agregar", "--lectura", str(_lectura(e, noches=("2026-12-01",), nombre="l2.csv"))) == 0
    assert BK not in (e.carpeta / "noches_2026-11.csv").read_text(encoding="utf-8")
    assert not (e.carpeta / "reporte_booking_2026-11.xlsx").exists()
    _, params = dg.leer_excel(e.carpeta / "reporte_booking_2026-12.xlsx")
    assert params["k"] == 3.43  # tomado del mes anterior


def test_agregar_sin_k_ni_reporte_previo_falla_sin_tocar_nada(entorno):
    e = entorno
    assert e.correr("agregar", "--lectura", str(_lectura(e))) == 2
    assert not list(e.carpeta.glob("noches_*.csv"))


def test_csv_vacio_es_formato_invalido(entorno, tmp_path):
    vacio = tmp_path / "vacio.csv"
    vacio.write_text("", encoding="utf-8")
    assert entorno.mod.main(["generar", "--noches", str(vacio), "--k", "3.4", "--salida", str(tmp_path / "x.xlsx")]) == 2
    assert not (tmp_path / "x.xlsx").exists()
