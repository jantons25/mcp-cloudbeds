"""Extras, pagos y resumen financiero a partir de las transacciones de la API contable de Cloudbeds.

Reglas verificadas contra la API real (Zentra Balta, 15/11/2026, ver PLAN_MULTI_API.md):
- `amount` ya viene en la moneda del hotel (169.64 = S/ 169,64); `currencyScale` es la
  cantidad de decimales, no un divisor.
- Los cargos son positivos y los pagos negativos (créditos). Una anulación de un cargo es
  otro movimiento con importe negativo (código 2000V para ítems).
- `externalRelationKind` dice qué es cada movimiento: ITEM, ITEM_POS y ADDON son extras;
  PAYMENT son pagos; ROOM es habitación.
- El rubro de un extra NO se puede cruzar por id con getItems (`externalRelationId` es el id
  del movimiento): se toma del nombre del ítem que trae `description` (32 de 37 en la prueba).
- El medio de pago no viene en ningún campo propio: se deduce de `description` comparándolo
  con los medios configurados en getPaymentMethods (23 de 23 en la prueba). El código
  interno no alcanza (9000 mezcla débito y Yape).

Nunca se devuelven las descripciones: pueden traer nombres de huéspedes. El detalle por
producto usa el nombre del catálogo (getItems); solo cuando un cargo es de un ítem renombrado
y no se sabe cuál de varios es, se muestra su texto, y únicamente si todas sus palabras están
en el nombre de un mismo ítem del catálogo (así nunca aparece un nombre de huésped).
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

EXTRAS = {"ITEM", "ITEM_POS", "ADDON"}
PAGO = "PAYMENT"
SIN_RUBRO = "Sin clasificar"
SIN_MEDIO = "No identificado"
SIN_CATEGORIA = "Sin categoría en Cloudbeds"
SIN_PRODUCTO = "Sin identificar (nombre distinto al catálogo)"
RUBRO_POR_TIPO = {"ADDON": "Complementos (add-ons)", "ITEM_POS": "Punto de venta (POS)"}
TIPOS = {
    "ROOM": "Habitación",
    "ITEM": "Productos y servicios",
    "ITEM_POS": "Punto de venta (POS)",
    "ADDON": "Complementos (add-ons)",
    "TAX": "Impuestos",
    "FEE": "Cargos adicionales",
    "GRATUITY": "Propinas",
    "PAYMENT_FEE": "Comisiones de pago",
}


def norm(texto: Any) -> str:
    """Minúsculas, sin tildes y con cualquier signo convertido en espacio."""
    plano = unicodedata.normalize("NFKD", str(texto or ""))
    plano = "".join(c for c in plano if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", plano))


def monto(t: dict[str, Any]) -> float:
    try:
        return round(float(t.get("amount") or 0), int(t.get("currencyScale") or 2))
    except (TypeError, ValueError):
        return 0.0


def _r(x: float) -> float:
    return round(x + 0.0, 2)  # +0.0 evita "-0.0"


class Catalogo:
    """Reconoce un nombre de catálogo dentro de un texto libre (descripción de la transacción).

    1. Coincidencia exacta.
    2. El nombre más largo que aparezca como palabras completas, así "Tarjeta de Debito" gana
       a "debit" y "bill" no coincide con "billetera".
    3. Solo con `parcial=True` (rubros): todas las palabras del texto están en el nombre de
       uno o más ítems y todos ellos son del mismo rubro. Cubre ítems renombrados: en Balta,
       los cargos "Agua San Luis - EX" son del ítem que hoy se llama "Agua San Luis con Gas
       625 ml - EX" (87 de 464 extras de noviembre de 2026). `ignorar` es una etiqueta que no
       decide (p. ej. "sin categoría") si hay otra candidata.
    """

    def __init__(
        self, pares: Iterable[tuple[Any, str]], min_len: int = 3, parcial: bool = False, ignorar: str | None = None
    ) -> None:
        self._exactos: dict[str, str] = {}
        self._palabras: list[tuple[frozenset[str], str]] = []
        for clave, etiqueta in pares:
            n = norm(clave)
            if len(n) >= min_len:
                self._exactos.setdefault(n, etiqueta)
                self._palabras.append((frozenset(n.split()), etiqueta))
        self._por_largo = sorted(self._exactos.items(), key=lambda kv: -len(kv[0]))
        self._parcial = parcial
        self._ignorar = ignorar

    def buscar(self, texto: Any) -> str | None:
        n = norm(texto)
        if not n:
            return None
        if n in self._exactos:
            return self._exactos[n]
        rodeado = f" {n} "
        encontrado = next((etiqueta for clave, etiqueta in self._por_largo if f" {clave} " in rodeado), None)
        if encontrado or not self._parcial:
            return encontrado
        palabras = set(n.split())
        if not any(len(p) >= 3 and not p.isdigit() for p in palabras):
            return None
        candidatas = {etiqueta for nombre, etiqueta in self._palabras if palabras <= nombre}
        if len(candidatas) > 1 and self._ignorar in candidatas:
            candidatas.discard(self._ignorar)
        return candidatas.pop() if len(candidatas) == 1 else None

    def solo_palabras_del_catalogo(self, texto: Any) -> bool:
        """Todas las palabras del texto están en el nombre de un mismo ítem (no hay nada ajeno al catálogo)."""
        palabras = set(norm(texto).split())
        if not any(len(p) >= 3 and not p.isdigit() for p in palabras):
            return False
        return any(palabras <= nombre for nombre, _ in self._palabras)


def catalogo_rubros(items: list[dict[str, Any]]) -> Catalogo:
    """Nombre del ítem (getItems) -> su categoría."""
    def categoria(i: dict[str, Any]) -> str:
        c = str(i.get("categoryName") or "").strip()
        return c if c and c.lower() != "uncategorized" else SIN_CATEGORIA
    return Catalogo(((i.get("name"), categoria(i)) for i in items if i.get("name")), parcial=True, ignorar=SIN_CATEGORIA)


def catalogo_productos(items: list[dict[str, Any]]) -> Catalogo:
    """Nombre del ítem (getItems) -> el mismo nombre, tal como está en el catálogo."""
    return Catalogo(((i.get("name"), " ".join(str(i.get("name")).split())) for i in items if i.get("name")), parcial=True)


def producto(t: dict[str, Any], productos: Catalogo) -> str:
    """Nombre del producto de un extra, sin exponer texto libre de la descripción."""
    desc = t.get("description")
    nombre = productos.buscar(desc)
    if nombre:
        return nombre
    if productos.solo_palabras_del_catalogo(desc):  # ítem renombrado: se sabe el rubro pero no cuál ítem
        return " ".join(str(desc).split())[:80]
    return SIN_PRODUCTO


# Medios equivalentes con nombres distintos según el hotel (verificado en los 3 hoteles, nov-2026):
# Balta usa "Transferencia Bancaria" (bank_transfer) y Plaza y San José, "Transferencia"; San José
# además tiene "Tarjeta de crédito" (Tarjetadecrédito) junto a "Tarjeta de Credito" (credit).
MEDIOS_CANONICOS = {
    "Efectivo": ("cash", "efectivo"),
    "Tarjeta de crédito": ("credit", "tarjeta de credito", "tarjetadecredito"),
    "Tarjeta de débito": ("debit", "tarjeta de debito", "tarjetadedebito"),
    "Transferencia bancaria": ("bank transfer", "transferencia", "transferencia bancaria"),
}
_CANONICO = {alias: nombre for nombre, aliases in MEDIOS_CANONICOS.items() for alias in aliases}


def catalogo_medios(metodos: list[dict[str, Any]]) -> Catalogo:
    """Nombre, método o código del medio de pago (getPaymentMethods) -> nombre a mostrar.

    Los medios equivalentes se muestran con el mismo nombre en todos los hoteles, para que el
    total de la red no los separe.
    """
    pares = []
    for m in metodos:
        etiqueta = str(m.get("name") or m.get("method") or "").strip()
        claves = [m.get(k) for k in ("name", "method", "code") if m.get(k)]
        canonico = next((_CANONICO[norm(c)] for c in claves if norm(c) in _CANONICO), None)
        if etiqueta:
            pares += [(c, canonico or etiqueta) for c in claves]
    return Catalogo(pares)


def _acum() -> dict[str, float]:
    return {"importe": 0.0, "movimientos": 0, "unidades": 0.0}


def _sumar(a: dict[str, float], importe: float, unidades: float) -> None:
    a["importe"] += importe
    a["movimientos"] += 1
    a["unidades"] += unidades


def _redondear(d: dict[str, Any]) -> dict[str, Any]:
    return {k: _r(v) if isinstance(v, float) else v for k, v in d.items()}


def _por_importe(d: dict[str, dict[str, Any]], campo: str = "importe") -> dict[str, dict[str, Any]]:
    return dict(sorted(((k, _redondear(v)) for k, v in d.items()), key=lambda kv: -abs(kv[1].get(campo) or 0)))


def _unidades(t: dict[str, Any], importe: float) -> float:
    try:
        q = abs(float(t.get("quantity")))
    except (TypeError, ValueError):
        q = 1.0
    return -q if importe < 0 else q  # una anulación descuenta unidades


# ---------- extras ----------

def extras(
    transacciones: list[dict[str, Any]],
    rubros: Catalogo,
    agrupar: str = "rubro",
    productos: Catalogo | None = None,
    rubro: str | None = None,
) -> dict[str, Any]:
    """Extras (ITEM, ITEM_POS, ADDON) por rubro y, si se pide, por día de servicio o por producto.

    `rubro` limita el resultado a los rubros cuyo nombre contiene ese texto (sin tildes ni mayúsculas).
    """
    filtro = norm(rubro) if rubro else ""
    productos = productos or Catalogo([])
    total, sin = _acum(), _acum()
    por_rubro: dict[str, dict[str, float]] = defaultdict(_acum)
    por_producto: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(_acum))
    vistos: set[str] = set()
    por_dia: dict[str, dict[str, float]] = defaultdict(_acum)
    por_dia_rubro: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    anulaciones = 0
    for t in transacciones:
        tipo = t.get("externalRelationKind")
        if tipo not in EXTRAS:
            continue
        importe = monto(t)
        unidades = _unidades(t, importe)
        r = rubros.buscar(t.get("description")) or RUBRO_POR_TIPO.get(str(tipo)) or SIN_RUBRO
        vistos.add(r)
        if filtro and filtro not in norm(r):
            continue
        dia = str(t.get("serviceDate") or "")[:10] or "sin fecha"
        _sumar(total, importe, unidades)
        _sumar(por_rubro[r], importe, unidades)
        _sumar(por_dia[dia], importe, unidades)
        por_dia_rubro[dia][r] += importe
        if agrupar == "producto":
            _sumar(por_producto[r][producto(t, productos)], importe, unidades)
        if r == SIN_RUBRO:
            _sumar(sin, importe, unidades)
        if importe < 0:
            anulaciones += 1

    out: dict[str, Any] = {"total": _redondear(total), "por_rubro": _por_importe(por_rubro)}
    if rubro:
        out["filtro_rubro"] = rubro
        if not por_rubro:
            out["aviso"] = (f"Ningún rubro contiene '{rubro}'. Rubros con extras en el periodo: "
                            + (", ".join(sorted(vistos)) or "ninguno") + ".")
    if agrupar == "producto":
        for r, v in out["por_rubro"].items():
            v["productos"] = _por_importe(por_producto[r])
    if agrupar in ("dia", "dia_y_rubro"):
        out["por_dia"] = {d: _redondear(v) for d, v in sorted(por_dia.items())}
    if agrupar == "dia_y_rubro":
        out["por_dia_y_rubro"] = {
            d: {r: _r(v) for r, v in sorted(rs.items(), key=lambda kv: -abs(kv[1]))} for d, rs in sorted(por_dia_rubro.items())
        }
    if anulaciones:
        out["anulaciones"] = anulaciones
    if sin["movimientos"]:
        out["sin_clasificar"] = {
            **_redondear(sin),
            "nota": "Extras cuyo nombre no coincide con ningún ítem del catálogo de Cloudbeds (ítems "
                    "personalizados, renombrados o anulaciones). Están incluidos en el total.",
        }
    return out


# ---------- pagos ----------

def _dia_pago(t: dict[str, Any], criterio: str, tz: ZoneInfo) -> date | None:
    if criterio == "contable":
        valor = t.get("businessDate")
    else:
        local = t.get("transactionDatetimePropertyTime")
        if local:
            valor = local
        else:
            try:
                utc = datetime.fromisoformat(str(t.get("transactionDatetime")).replace("Z", "+00:00"))
                return utc.astimezone(tz).date()
            except ValueError:
                return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def _acum_pago() -> dict[str, float]:
    return {"neto": 0.0, "registrado": 0.0, "anulado": 0.0, "devuelto": 0.0, "pagos": 0, "anulaciones": 0, "devoluciones": 0}


def es_anulacion(t: dict[str, Any]) -> bool:
    """Los códigos internos que terminan en V anulan un movimiento (2000V ítem, 9000V/9100V/9200V pago).

    Verificado en los 3 hoteles (1-21/11/2026): los 52 pagos positivos eran todos V y cada uno
    tenía un pago del mismo importe en la misma reserva.
    """
    return str(t.get("internalTransactionCode") or "").upper().endswith("V")


def _sumar_pago(a: dict[str, float], importe: float, anulacion: bool) -> None:
    """`importe` en sentido de cobro: positivo = entra dinero."""
    a["neto"] += importe
    if importe >= 0:
        a["registrado"] += importe
        a["pagos"] += 1
    elif anulacion:
        a["anulado"] += -importe
        a["anulaciones"] += 1
    else:
        a["devuelto"] += -importe
        a["devoluciones"] += 1


def pagos(
    transacciones: list[dict[str, Any]],
    medios: Catalogo,
    desde: date,
    hasta: date,
    criterio: str,
    tz: ZoneInfo,
    agrupar: str = "medio",
) -> dict[str, Any]:
    """Pagos recibidos por medio de pago y, si se pide, por día.

    criterio='pago' cuenta cada pago el día (hora del hotel) en que se registró;
    criterio='contable', el día contable (businessDate) al que lo asignó el cierre.
    """
    total, sin = _acum_pago(), _acum_pago()
    por_medio: dict[str, dict[str, float]] = defaultdict(_acum_pago)
    por_dia: dict[str, dict[str, float]] = defaultdict(_acum_pago)
    por_dia_medio: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in transacciones:
        if t.get("externalRelationKind") != PAGO:
            continue
        dia = _dia_pago(t, criterio, tz)
        if dia is None or not desde <= dia <= hasta:
            continue
        importe = -monto(t)  # en Cloudbeds el pago es un crédito (negativo)
        anulacion = es_anulacion(t)
        medio = medios.buscar(t.get("description")) or SIN_MEDIO
        for a in (total, por_medio[medio], por_dia[dia.isoformat()]) + ((sin,) if medio == SIN_MEDIO else ()):
            _sumar_pago(a, importe, anulacion)
        por_dia_medio[dia.isoformat()][medio] += importe

    out: dict[str, Any] = {"total": _redondear(total), "por_medio": _por_importe(por_medio, "neto")}
    if agrupar in ("dia", "dia_y_medio"):
        out["por_dia"] = {d: _redondear(v) for d, v in sorted(por_dia.items())}
    if agrupar == "dia_y_medio":
        out["por_dia_y_medio"] = {
            d: {m: _r(v) for m, v in sorted(ms.items(), key=lambda kv: -abs(kv[1]))} for d, ms in sorted(por_dia_medio.items())
        }
    if sin["pagos"] or sin["anulaciones"] or sin["devoluciones"]:
        out["no_identificados"] = {
            **_redondear(sin),
            "nota": "Pagos cuya descripción no menciona ningún medio de pago configurado en Cloudbeds. "
                    "Están incluidos en el total.",
        }
    return out


# ---------- resumen financiero ----------

def resumen_financiero(transacciones: list[dict[str, Any]]) -> dict[str, Any]:
    """Cargos por tipo y pagos aplicados, según la fecha de servicio de cada movimiento."""
    cargos = _acum()
    por_tipo: dict[str, dict[str, Any]] = {}
    pagos_aplicados = _acum_pago()
    for t in transacciones:
        tipo = str(t.get("externalRelationKind") or "OTRO")
        importe = monto(t)
        if tipo == PAGO:
            _sumar_pago(pagos_aplicados, -importe, es_anulacion(t))
            continue
        etiqueta = TIPOS.get(tipo, tipo)
        item = por_tipo.setdefault(etiqueta, {**_acum(), "por_codigo": defaultdict(float)})
        _sumar(item, importe, 0)
        _sumar(cargos, importe, 0)
        item["por_codigo"][str(t.get("internalTransactionCode") or "-")] += importe

    tipos = {}
    for etiqueta, v in sorted(por_tipo.items(), key=lambda kv: -abs(kv[1]["importe"])):
        tipos[etiqueta] = {
            "importe": _r(v["importe"]),
            "movimientos": v["movimientos"],
            "por_codigo": {c: _r(x) for c, x in sorted(v["por_codigo"].items())},
        }
    return {
        "cargos": {"total": _r(cargos["importe"]), "movimientos": cargos["movimientos"], "por_tipo": tipos},
        "pagos_aplicados": _redondear(pagos_aplicados),
        "cargos_menos_pagos": _r(cargos["importe"] - pagos_aplicados["neto"]),
    }


# ---------- total de la red ----------

def _suma_profunda(dicts: list[Any]) -> Any:
    """Suma hoja a hoja los números de varios dicts con la misma forma; los textos se toman del primero."""
    presentes = [d for d in dicts if d is not None]
    if not presentes:
        return None
    if all(isinstance(d, dict) for d in presentes):
        claves: list[str] = []
        for d in presentes:
            claves += [k for k in d if k not in claves]
        return {k: _suma_profunda([d.get(k) for d in presentes]) for k in claves}
    if all(isinstance(d, (int, float)) and not isinstance(d, bool) for d in presentes):
        total = sum(presentes)
        return _r(total) if isinstance(total, float) else total
    return presentes[0]


def _ordenar(d: dict[str, Any] | None, campo: str) -> dict[str, Any] | None:
    if not isinstance(d, dict):
        return d
    return dict(sorted(d.items(), key=lambda kv: -abs((kv[1] or {}).get(campo) or 0) if isinstance(kv[1], dict) else 0))


def _merge(results: dict[str, dict[str, Any]], ordenar: dict[str, str]) -> dict[str, Any]:
    rs = list(results.values())
    monedas = {r.get("moneda") for r in rs}
    if len(monedas) != 1 or None in monedas:
        conocidas = ", ".join(sorted(m for m in monedas if m)) or "desconocida"
        return {
            "periodo": rs[0].get("periodo"),
            "moneda": None,
            "advertencia_moneda": f"Los hoteles no tienen la misma moneda conocida ({conocidas}): los importes "
                                  "NO se suman; consulta cada hotel por separado.",
        }
    fuera = ("periodo", "notas", "advertencia")  # el periodo es el mismo en todos; no se suma
    total = {"periodo": rs[0].get("periodo"), **_suma_profunda([{k: v for k, v in r.items() if k not in fuera} for r in rs])}
    for clave, campo in ordenar.items():
        if clave in total:
            total[clave] = _ordenar(total[clave], campo)
    return total


def merge_extras(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    total = _merge(results, {"por_rubro": "importe"})
    for v in (total.get("por_rubro") or {}).values():
        if isinstance(v, dict) and isinstance(v.get("productos"), dict):
            v["productos"] = _ordenar(v["productos"], "importe")
    return total


def merge_pagos(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return _merge(results, {"por_medio": "neto"})


def merge_financiero(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    total = _merge(results, {})
    if isinstance(total.get("cargos"), dict):
        total["cargos"]["por_tipo"] = _ordenar(total["cargos"].get("por_tipo"), "importe")
    return total
