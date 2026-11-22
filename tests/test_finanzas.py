"""Cálculos de extras, pagos y resumen financiero (finanzas.py), con transacciones como las de la API contable."""

from datetime import date
from zoneinfo import ZoneInfo

import pytest

from cloudbeds_mcp import finanzas as fin

LIMA = ZoneInfo("America/Lima")

ITEMS = [
    {"itemID": "1196159", "name": "Agua San Luis 625ml", "categoryName": "A&B Exhibidoras"},
    {"itemID": "1199416", "name": "Lavandería", "categoryName": "Otros"},
    {"itemID": "1199417", "name": "Shampoo", "categoryName": "Productos de Aseo"},
    {"itemID": "1199418", "name": "Llavero", "categoryName": "uncategorized"},
]
METODOS = [
    {"name": "Tarjeta de Credito", "method": "credit"},
    {"name": "Tarjeta de Debito", "method": "debit"},
    {"name": "Transferencia Bancaria", "method": "bank_transfer"},
    {"name": "Efectivo", "method": "cash"},
    {"name": "Factura", "method": "bill"},
    {"name": "Yape", "method": "Yape"},
]


def tx(kind, amount, desc="", **extra):
    return {"externalRelationKind": kind, "amount": amount, "currencyScale": 2, "currency": "PEN",
            "description": desc, **extra}


# ---------- utilidades ----------

@pytest.mark.parametrize(("texto", "esperado"), [
    ("Lavandería  Express", "lavanderia express"), ("bank_transfer", "bank transfer"), (None, ""), ("A&B", "a b"),
])
def test_norm(texto, esperado):
    assert fin.norm(texto) == esperado


@pytest.mark.parametrize(("t", "esperado"), [
    ({"amount": 169.64, "currencyScale": 2}, 169.64),  # ya viene en soles: no se divide
    ({"amount": -2265.98, "currencyScale": 2}, -2265.98),
    ({"amount": "12.5", "currencyScale": 2}, 12.5),
    ({"amount": None}, 0.0),
    ({"amount": "x"}, 0.0),
])
def test_monto(t, esperado):
    assert fin.monto(t) == esperado


def test_catalogo_prefiere_exacto_y_el_nombre_mas_largo():
    medios = fin.catalogo_medios(METODOS)
    assert medios.buscar("Tarjeta de Debito") == "Tarjeta de débito"
    assert medios.buscar("Pago con tarjeta de débito Visa") == "Tarjeta de débito"  # gana al código "debit"
    assert medios.buscar("Payment - debit") == "Tarjeta de débito"
    assert medios.buscar("bank transfer BCP") == "Transferencia bancaria"
    assert medios.buscar("Yape") == "Yape"  # los medios propios conservan su nombre
    assert medios.buscar("Pago con billetera") is None  # "bill" solo como palabra completa
    assert medios.buscar("") is None


def test_catalogo_rubros_y_sin_categoria():
    rubros = fin.catalogo_rubros(ITEMS)
    assert rubros.buscar("agua san luis 625ml") == "A&B Exhibidoras"
    assert rubros.buscar("Llavero") == fin.SIN_CATEGORIA
    assert rubros.buscar("Servicio especial") is None


def test_medios_equivalentes_tienen_el_mismo_nombre_en_todos_los_hoteles():
    balta = fin.catalogo_medios([{"name": "Transferencia Bancaria", "method": "bank_transfer"}])
    plaza = fin.catalogo_medios([{"name": "Transferencia", "method": "Transferencia"},
                                 {"name": "Tarjeta de crédito", "method": "Tarjetadecrédito"},
                                 {"name": "Pago en llegada", "method": "1"}])
    assert balta.buscar("Transferencia Bancaria") == plaza.buscar("Transferencia") == "Transferencia bancaria"
    assert plaza.buscar("Tarjeta de crédito") == "Tarjeta de crédito"
    assert plaza.buscar("Pago") is None  # sin búsqueda parcial en medios: "Pago" no es "Pago en llegada"


def test_rubros_reconoce_items_renombrados():
    rubros = fin.catalogo_rubros([
        {"name": "Agua San Luis con Gas 625 ml - EX", "categoryName": "A&B Exhibidoras"},
        {"name": "Agua San Luis sin Gas 750 ml - EX", "categoryName": "uncategorized"},
        {"name": "Agua San Luis 500 cc - HAB", "categoryName": "A&B Habitaciones"},
        {"name": "Gatorade Azul - EX", "categoryName": "A&B Exhibidoras"},
    ])
    assert rubros.buscar("Agua San Luis - EX") == "A&B Exhibidoras"  # "sin categoría" no decide
    assert rubros.buscar("agua san luis hab") == "A&B Habitaciones"
    assert rubros.buscar("Gatorade") == "A&B Exhibidoras"
    assert rubros.buscar("Agua San Luis") is None  # EX y HAB: ambiguo, no se adivina
    assert rubros.buscar("500") is None  # solo números no alcanzan


# ---------- extras ----------

EXTRAS_TX = [
    tx("ITEM", 6.0, "Agua San Luis 625ml", serviceDate="2026-11-15", quantity=1),
    tx("ITEM", 25.0, "Lavandería", serviceDate="2026-11-15", quantity=1),
    tx("ITEM", -25.0, "Lavandería", serviceDate="2026-11-15", quantity=1),  # anulación
    tx("ITEM", 8.0, "Shampoo", serviceDate="2026-11-16", quantity=2),
    tx("ITEM", 12.5, "Rosa Quispe - cargo manual", serviceDate="2026-11-16"),  # no está en el catálogo
    tx("ADDON", 30.0, "Desayuno incluido", serviceDate="2026-11-16", quantity=2),
    tx("ROOM", 169.64, "Noche", serviceDate="2026-11-15"),
    tx("PAYMENT", -200.0, "Efectivo", serviceDate="2026-11-15"),
]


def test_extras_por_rubro():
    out = fin.extras(EXTRAS_TX, fin.catalogo_rubros(ITEMS))
    assert out["total"] == {"importe": 56.5, "movimientos": 6, "unidades": 6.0}
    assert list(out["por_rubro"]) == ["Complementos (add-ons)", "Sin clasificar", "Productos de Aseo", "A&B Exhibidoras", "Otros"]
    assert out["por_rubro"]["Otros"] == {"importe": 0.0, "movimientos": 2, "unidades": 0.0}  # cargo y anulación
    assert out["anulaciones"] == 1
    assert out["sin_clasificar"]["importe"] == 12.5
    assert "por_dia" not in out and "por_dia_y_rubro" not in out


def test_extras_por_dia_y_rubro():
    out = fin.extras(EXTRAS_TX, fin.catalogo_rubros(ITEMS), "dia_y_rubro")
    assert out["por_dia"]["2026-11-15"]["importe"] == 6.0
    assert out["por_dia"]["2026-11-16"]["importe"] == 50.5
    assert out["por_dia_y_rubro"]["2026-11-16"] == {"Complementos (add-ons)": 30.0, "Sin clasificar": 12.5, "Productos de Aseo": 8.0}


def test_extras_nunca_devuelve_descripciones():
    out = str(fin.extras(EXTRAS_TX, fin.catalogo_rubros(ITEMS), "dia_y_rubro"))
    assert "Rosa" not in out and "Quispe" not in out


def test_extras_sin_movimientos():
    out = fin.extras([], fin.catalogo_rubros(ITEMS), "dia")
    assert out == {"total": {"importe": 0.0, "movimientos": 0, "unidades": 0.0}, "por_rubro": {}, "por_dia": {}}


# ---------- pagos ----------

PAGOS_TX = [
    tx("PAYMENT", -129.0, "Pago Yape Rosa Quispe", transactionDatetimePropertyTime="2026-11-15T10:00:00",
       businessDate="2026-11-15"),
    tx("PAYMENT", -2265.98, "Transferencia Bancaria", transactionDatetimePropertyTime="2026-11-15T23:30:00",
       businessDate="2026-11-16"),  # el cierre de caja lo pasó al día siguiente
    tx("PAYMENT", -50.0, "Efectivo", transactionDatetime="2026-11-16T03:00:00Z", businessDate="2026-11-15"),  # 22:00 en Lima
    tx("PAYMENT", 20.0, "Reembolso Efectivo", transactionDatetimePropertyTime="2026-11-15T12:00:00",
       businessDate="2026-11-15"),  # devolución
    tx("PAYMENT", -10.0, "Pago", transactionDatetimePropertyTime="2026-11-15T13:00:00", businessDate="2026-11-15"),
    tx("PAYMENT", -300.0, "Yape", transactionDatetimePropertyTime="2026-11-15T14:00:00", businessDate="2026-11-15",
       internalTransactionCode="9000"),
    tx("PAYMENT", 300.0, "Yape", transactionDatetimePropertyTime="2026-11-15T14:05:00", businessDate="2026-11-15",
       internalTransactionCode="9000V"),  # el mismo pago, anulado
    tx("PAYMENT", -99.0, "Yape", transactionDatetimePropertyTime="2026-11-17T09:00:00", businessDate="2026-11-17"),
    tx("ITEM", 6.0, "Agua", transactionDatetimePropertyTime="2026-11-15T09:00:00", businessDate="2026-11-15"),
]
D15 = date(2026, 11, 15)


def test_pagos_por_dia_de_pago():
    out = fin.pagos(PAGOS_TX, fin.catalogo_medios(METODOS), D15, D15, "pago", LIMA)
    t = out["total"]
    assert t == {"neto": 2434.98, "registrado": 2754.98, "anulado": 300.0, "devuelto": 20.0,
                 "pagos": 5, "anulaciones": 1, "devoluciones": 1}
    assert list(out["por_medio"]) == ["Transferencia bancaria", "Yape", "Efectivo", "No identificado"]
    assert out["por_medio"]["Yape"] == {"neto": 129.0, "registrado": 429.0, "anulado": 300.0, "devuelto": 0.0,
                                        "pagos": 2, "anulaciones": 1, "devoluciones": 0}
    assert out["por_medio"]["Efectivo"]["devuelto"] == 20.0 and out["por_medio"]["Efectivo"]["neto"] == 30.0
    assert out["no_identificados"]["neto"] == 10.0


def test_pagos_por_dia_contable():
    out = fin.pagos(PAGOS_TX, fin.catalogo_medios(METODOS), D15, D15, "contable", LIMA)
    assert out["total"]["neto"] == 169.0  # 129 + 50 + 10 - 20: sin la transferencia que pasó al cierre siguiente
    assert "Transferencia bancaria" not in out["por_medio"]


def test_pagos_agrupados_por_dia_y_medio():
    out = fin.pagos(PAGOS_TX, fin.catalogo_medios(METODOS), D15, date(2026, 11, 17), "pago", LIMA, "dia_y_medio")
    assert list(out["por_dia"]) == ["2026-11-15", "2026-11-17"]
    assert out["por_dia_y_medio"]["2026-11-17"] == {"Yape": 99.0}
    assert "Rosa" not in str(out)


# ---------- resumen financiero ----------

def test_resumen_financiero():
    trans = [
        tx("ROOM", 169.64, internalTransactionCode="1000"),
        tx("ROOM", 20.36, internalTransactionCode="8000"),
        tx("ITEM", 931.5, internalTransactionCode="2000"),
        tx("ITEM", -43.5, internalTransactionCode="2000V"),
        tx("PAYMENT", -500.0, internalTransactionCode="9000"),
        tx("RARO", 1.0),
    ]
    out = fin.resumen_financiero(trans)
    assert out["cargos"]["total"] == 1079.0 and out["cargos"]["movimientos"] == 5
    assert list(out["cargos"]["por_tipo"]) == ["Productos y servicios", "Habitación", "RARO"]
    assert out["cargos"]["por_tipo"]["Habitación"] == {"importe": 190.0, "movimientos": 2, "por_codigo": {"1000": 169.64, "8000": 20.36}}
    assert out["cargos"]["por_tipo"]["Productos y servicios"]["por_codigo"] == {"2000": 931.5, "2000V": -43.5}
    assert out["pagos_aplicados"]["neto"] == 500.0 and out["pagos_aplicados"]["registrado"] == 500.0
    assert out["cargos_menos_pagos"] == 579.0


# ---------- total de la red ----------

def _hotel(moneda, importe, dia_importe):
    return {
        "periodo": {"desde": "2026-11-15", "hasta": "2026-11-16", "dias": 2},
        "moneda": moneda,
        "total": {"importe": importe, "movimientos": 2, "unidades": 2.0},
        "por_rubro": {"Otros": {"importe": importe, "movimientos": 2, "unidades": 2.0}},
        "por_dia": {"2026-11-15": {"importe": dia_importe, "movimientos": 1, "unidades": 1.0}},
        "notas": ["nota"],
    }


def test_merge_extras_suma_y_no_suma_el_periodo():
    a = _hotel("PEN", 100.0, 40.0)
    b = _hotel("PEN", 50.5, 10.0)
    b["por_rubro"]["Minibar"] = {"importe": 200.0, "movimientos": 1, "unidades": 1.0}
    out = fin.merge_extras({"balta": a, "plaza": b})
    assert out["periodo"]["dias"] == 2
    assert out["moneda"] == "PEN"
    assert out["total"]["importe"] == 150.5 and out["total"]["movimientos"] == 4
    assert list(out["por_rubro"]) == ["Minibar", "Otros"]
    assert out["por_rubro"]["Otros"]["importe"] == 150.5
    assert out["por_dia"]["2026-11-15"]["importe"] == 50.0
    assert "notas" not in out


def test_merge_nunca_suma_monedas_distintas():
    out = fin.merge_pagos({"balta": _hotel("PEN", 1.0, 1.0), "plaza": _hotel("USD", 1.0, 1.0)})
    assert out["moneda"] is None and "NO se suman" in out["advertencia_moneda"]
    assert "total" not in out


def test_merge_financiero_ordena_tipos():
    def r(hab, ext):
        return {"periodo": {"dias": 1}, "moneda": "PEN", "cargos": {"total": hab + ext, "movimientos": 2, "por_tipo": {
            "Habitación": {"importe": hab, "movimientos": 1, "por_codigo": {"1000": hab}},
            "Productos y servicios": {"importe": ext, "movimientos": 1, "por_codigo": {"2000": ext}}}},
            "pagos_aplicados": {"neto": 10.0}, "cargos_menos_pagos": hab + ext - 10}
    out = fin.merge_financiero({"a": r(100.0, 50.0), "b": r(10.0, 200.0)})
    assert list(out["cargos"]["por_tipo"]) == ["Productos y servicios", "Habitación"]
    assert out["cargos"]["total"] == 360.0 and out["pagos_aplicados"]["neto"] == 20.0
