"""Desglose de Booking: cálculo, textos de los campos y validación del formato."""

import importlib.util
from datetime import date
from pathlib import Path

import openpyxl
import pytest

from cloudbeds_mcp import desglose as dg

RAIZ = Path(__file__).resolve().parents[1]


def _noche(**kw):
    base = {
        "hotel": "Zentra Balta", "reserva_booking": "6280864979", "habitacion_booking": "Standard Doble",
        "tipo_cloudbeds": "Doble Standard", "noche": "2026-11-26", "plan": "No reembolsable",
        "tarifa_base_cb": 150, "promocion": "Mobile Rate", "promo1": 0.1, "promo2": None, "promo3": None,
        "genius_pct": 0.25, "genius_tipo": "Dinámico", "subtotal_usd": 33.53, "comision_pct": 0.23,
    }
    base.update(kw)
    return base


def test_calculo_katerina():
    n = dg.noche_desde_fila(_noche(), 5)
    assert n.original == pytest.approx(49.674, abs=0.001)
    assert n.promo_monto == pytest.approx(4.967, abs=0.001)
    assert n.genius_monto == pytest.approx(11.177, abs=0.001)
    assert n.comision == pytest.approx(7.712, abs=0.001)
    v = dg.valores_campos(dg.agrupar([n])[0])
    assert v == {
        "base_cb": "S/ 150.00 (tarifa hoy)",
        "original": "US$ 49.67 sin IGV",
        "promo": "Mobile Rate 10 %: -US$ 4.97",
        "genius": "Genius 25 % dinámico: -US$ 11.18",
        "subtotal": "US$ 33.53",
        "comision": "23 %: US$ 7.71",
        "neto": "US$ 25.82 (52 % del original)",
    }
    assert all(len(x) <= dg.MAX_CARACTERES_CAMPO for x in v.values())


def test_varias_habitaciones_y_comision_informada():
    filas = [dg.noche_desde_fila(_noche(noche=d), i) for i, d in enumerate(["2026-11-21", "2026-11-21", "2026-11-22"])]
    r = dg.agrupar(filas, {"6280864979": 23.0})[0]
    v = dg.valores_campos(r)
    assert "en 3 noches-hab." in v["subtotal"]
    assert v["comision"].endswith("US$ 23.00")  # manda la comisión informada por Booking


def test_sin_promocion_sin_genius_y_sin_tarifa():
    n = dg.noche_desde_fila(_noche(promocion="Sin promoción", promo1=None, genius_pct=0, genius_tipo="—",
                                   tarifa_base_cb=None), 5)
    v = dg.valores_campos(dg.agrupar([n])[0])
    assert v["promo"] == "Sin promoción" and v["genius"] == "Sin Genius"
    assert v["base_cb"] == "sin tarifa en Cloudbeds"
    assert v["original"] == "US$ 33.53 sin IGV"


@pytest.mark.parametrize("pct", [0.23, 23, "23%", "23 %", "0,23"])
def test_porcentajes_en_varios_formatos(pct):
    assert dg.noche_desde_fila(_noche(comision_pct=pct), 5).comision_pct == pytest.approx(0.23)


@pytest.mark.parametrize(
    ("cambio", "mensaje"),
    [
        ({"subtotal_usd": "=R5*2"}, "fórmula"),
        ({"subtotal_usd": None}, "falta"),
        ({"reserva_booking": "62808-64979"}, "solo dígitos"),
        ({"noche": "26 nov"}, "fecha"),
        ({"comision_pct": 150}, "fuera de rango"),
        ({"genius_tipo": "Otro"}, "Genius tipo"),
        ({"genius_tipo": "—"}, "tipo es"),
    ],
)
def test_errores_de_formato(cambio, mensaje):
    with pytest.raises(dg.FormatoError, match=mensaje):
        dg.noche_desde_fila(_noche(**cambio), 7)


def test_misma_reserva_en_dos_hoteles():
    a = dg.noche_desde_fila(_noche(), 5)
    b = dg.noche_desde_fila(_noche(hotel="Zentra Plaza"), 6)
    with pytest.raises(dg.FormatoError, match="más de un hotel"):
        dg.agrupar([a, b])


def test_textos_largos_se_recortan():
    n = dg.noche_desde_fila(_noche(promocion="Country Rate; Last Minute Deal; Mobile Rate; Black Friday Deal",
                                   promo2=0.1, promo3=0.05), 5)
    v = dg.valores_campos(dg.agrupar([n])[0])
    assert len(v["promo"]) <= dg.MAX_CARACTERES_CAMPO
    assert v["promo"].endswith("-US$ 10.70") or "-US$" in v["promo"]


def _script():
    spec = importlib.util.spec_from_file_location("desglose_booking", RAIZ / "scripts" / "desglose_booking.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generar_y_leer_el_excel(tmp_path):
    csv_path = tmp_path / "noches.csv"
    cab = list(dg.COLUMNAS) + ["comision_informada_usd"]
    filas = [
        ["Zentra Balta", "6280864979", "Standard Doble", "Doble Standard", "2026-11-26", "No reembolsable", "150",
         "Mobile Rate", "0.1", "", "", "0.25", "Dinámico", "33.53", "0.23", "7.71"],
        ["Zentra Plaza", "5339059508", "Standard Twin", "Twin Standard", "2026-11-21", "No reembolsable", "150",
         "Late Escape Deal", "15%", "", "", "20%", "Dinámico", "27.98", "15%", ""],
    ]
    csv_path.write_text("\n".join(";".join(f) for f in [cab, *filas]), encoding="utf-8")
    salida = tmp_path / "reporte.xlsx"
    assert _script().main(["generar", "--noches", str(csv_path), "--k", "3.43", "--salida", str(salida)]) == 0
    reservas, params = dg.leer_excel(salida)
    assert params == {"k": 3.43}
    por_id = {r.reserva_booking: r for r in reservas}
    assert por_id["6280864979"].comision_informada == 7.71
    assert dg.valores_campos(por_id["6280864979"])["neto"] == "US$ 25.82 (52 % del original)"
    ws = openpyxl.load_workbook(salida)[dg.HOJA_NOCHES]
    assert ws["H5"].value.startswith("=R5/")  # el Excel conserva las fórmulas


def test_excel_sin_columnas_obligatorias(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = dg.HOJA_NOCHES
    wb.active.append(["Hotel", "N° reserva Booking", "Noche"])
    path = tmp_path / "malo.xlsx"
    wb.save(path)
    with pytest.raises(dg.FormatoError, match="Faltan columnas"):
        dg.leer_excel(path)
    assert _script().main(["validar", "--excel", str(path)]) == 2


def test_nota_incluye_cada_noche():
    n = dg.noche_desde_fila(_noche(), 5)
    texto = dg.nota(dg.agrupar([n])[0], "reporte.xlsx", date(2026, 11, 27))
    assert "26/11 Doble Standard" in texto and "reporte.xlsx" in texto and "2026-11-27" in texto
