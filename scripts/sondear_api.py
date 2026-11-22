"""Fase 0 de PLAN_MULTI_API.md: sondea con la key real lo que Cloudbeds entrega para extras, pagos y reportes.

Uso (desde la raíz del proyecto, con la key ya guardada con agregar_hotel.py):
    Windows: .\\.venv\\Scripts\\python.exe scripts\\sondear_api.py --alias balta
             .\\.venv\\Scripts\\python.exe scripts\\sondear_api.py --alias balta --fecha 2026-11-15
    macOS:   ./.venv/bin/python scripts/sondear_api.py --alias balta

Solo lee: GET a la API v1.3 y a Insights, y dos POST que solo consultan (búsqueda de
transacciones contables y consulta agregada de Insights). Nunca imprime la key ni datos de
huéspedes: muestra códigos HTTP, nombres de campos, conteos, totales, montos sueltos y valores
de catálogo (categorías, medios de pago, códigos). El resultado se guarda en logs/ (fuera de git).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402

from cloudbeds_mcp.config import (  # noqa: E402
    ENV_PATH,
    PROJECT_ROOT,
    env_key_var,
    key_from_keyring,
    keyring_user,
    load_catalog,
)

V13 = "https://api.cloudbeds.com/api/v1.3/"
ACCOUNTING = "https://api.cloudbeds.com/accounting/v1.0/transactions"
INSIGHTS = "https://api.cloudbeds.com/datainsights/v1.1/"
PAUSA = 0.3  # ~3 req/s, por debajo del límite de Cloudbeds
MAX_PAGINAS = 30
EXTRAS = {"ITEM", "ITEM_POS", "ADDON"}
SIN_MEDIO = "(no reconocido en la descripción)"
# Campos cuyos valores son catálogo o códigos (sin datos de huéspedes): se pueden mostrar.
CAMPOS_SEGUROS = {
    "transactionType", "transactionCategory", "category", "categoryName", "itemCategoryName",
    "paymentMethod", "paymentType", "cardType", "transactionCode", "sourceKind",
    "externalRelationKind", "chartOfAccountType", "currency", "currencyScale", "internalTransactionCode",
    "customTransactionCode", "generalLedgerCustomCode", "isDeleted", "transactionStatus",
}
# Consultas de Insights con columnas reales del dataset 1 (Financiero), vistas en la ronda 2.
# Solo se agrupa por columnas de catálogo: nunca por nombres de huéspedes ni datos de tarjetas.
CONSULTAS_INSIGHTS = [
    {"titulo": "Extras por rubro (fecha de servicio)", "dataset": 1,
     "metricas": [("debit_amount", "sum"), ("quantity_amount", "sum")],
     "agrupar": ["transaction_type", "item_service_category"], "fecha": "service_date"},
    {"titulo": "Pagos por medio de pago (fecha contable)", "dataset": 1,
     "metricas": [("credit_amount", "sum"), ("credit_amount", "count")],
     "agrupar": ["transaction_type", "payment_method"], "fecha": "business_date"},
    {"titulo": "Pagos por medio de pago (fecha y hora de la transacción, hora del hotel)", "dataset": 1,
     "metricas": [("credit_amount", "sum")],
     "agrupar": ["payment_method"], "fecha": "transaction_datetime_property_timezone"},
]
LISTAS_INSIGHTS = ["transaction_type", "item_service_category", "payment_method"]


class Salida:
    def __init__(self) -> None:
        self.lineas: list[str] = []

    def __call__(self, texto: str = "") -> None:
        print(texto)
        self.lineas.append(texto)


out = Salida()


def _norm(texto: Any) -> str:
    plano = unicodedata.normalize("NFKD", str(texto or ""))
    plano = "".join(c for c in plano if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", plano).strip()


def _corto(valor: Any, n: int = 300) -> str:
    texto = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)
    return re.sub(r"\s+", " ", texto)[:n]


def _mensaje(resp: httpx.Response) -> str:
    """Texto del error de Cloudbeds (validaciones; no trae datos de huéspedes)."""
    try:
        body = resp.json()
    except ValueError:
        return "(respuesta no JSON)" if resp.text.strip() else ""
    if isinstance(body, dict):
        for k in ("message", "error", "detail", "errors", "title"):
            if body.get(k):
                return _corto(body[k])
    return _corto(body)


def _campos(registros: list[dict[str, Any]]) -> list[str]:
    nombres: set[str] = set()
    for r in registros:
        for k, v in r.items():
            nombres.add(k)
            if isinstance(v, dict):
                nombres.update(f"{k}.{sub}" for sub in v)
    return sorted(nombres)


def _valores_seguros(registros: list[dict[str, Any]], sangria: str = "    ") -> None:
    conteos: dict[str, Counter] = defaultdict(Counter)
    for r in registros:
        for k, v in r.items():
            if k in CAMPOS_SEGUROS and not isinstance(v, (dict, list)):
                conteos[k][str(v)] += 1
            elif isinstance(v, dict):
                for sub, sv in v.items():
                    if sub in CAMPOS_SEGUROS and not isinstance(sv, (dict, list)):
                        conteos[f"{k}.{sub}"][str(sv)] += 1
    for campo, c in sorted(conteos.items()):
        out(f"{sangria}{campo}: " + ", ".join(f"{val} ({n})" for val, n in c.most_common(15)))


def _monto(t: dict[str, Any]) -> float:
    # Verificado en la ronda 2: amount ya viene en soles (p. ej. 169.64); currencyScale es la
    # cantidad de decimales, no un divisor.
    try:
        return round(float(t.get("amount") or 0), int(t.get("currencyScale") or 2))
    except (TypeError, ValueError):
        return 0.0


def _tabla(grupos: dict[str, list[float]], ancho: int = 34, sangria: str = "       ") -> None:
    for nombre, montos in sorted(grupos.items(), key=lambda x: -abs(sum(x[1]))):
        out(f"{sangria}{nombre:<{ancho}} {len(montos):>5} · {sum(montos):>12,.2f}")


# ---------- 1. API v1.3 ----------

def get_v13(http: httpx.Client, endpoint: str, params: dict[str, Any]) -> dict[str, Any] | None:
    time.sleep(PAUSA)
    try:
        resp = http.get(V13 + endpoint, params=params)
    except httpx.HTTPError as exc:
        out(f"  {endpoint}: error de red ({type(exc).__name__})")
        return None
    try:
        body = resp.json()
    except ValueError:
        body = None
    ok = resp.status_code == 200 and isinstance(body, dict) and body.get("success") is not False
    out(f"  {endpoint}: HTTP {resp.status_code} {'OK' if ok else 'FALLÓ ' + _mensaje(resp)}".rstrip())
    return body if ok else None


def _lista(body: Any, *ruta: str) -> list[dict[str, Any]]:
    data: Any = body
    for paso in ruta:
        data = data.get(paso) if isinstance(data, dict) else None
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def sondear_v13(http: httpx.Client, pid: str) -> dict[str, Any]:
    out("\n== 1. API v1.3: catálogos (encabezado x-api-key, el mismo del MCP)")
    items = _lista(get_v13(http, "getItems", {"propertyID": pid}), "data")
    cats = _lista(get_v13(http, "getItemCategories", {"propertyID": pid}), "data")
    metodos = _lista(get_v13(http, "getPaymentMethods", {"propertyID": pid, "lang": "es"}), "data", "methods")
    out(f"  Ítems en catálogo: {len(items)} · categorías: {len(cats)} · medios de pago activos: {len(metodos)}")
    por_cat = Counter(str(i.get("categoryName")) for i in items)
    out("  Ítems por categoría: " + ", ".join(f"{c} ({n})" for c, n in por_cat.most_common()))
    out("  Medios de pago: " + ", ".join(f"{m.get('name')} [{m.get('method')}]" for m in metodos))
    out("  Ejemplos de itemID: " + ", ".join(str(i.get("itemID")) for i in items[:3]))
    return {"items": items, "metodos": metodos}


# ---------- 2. API contable ----------

def _buscar(http: httpx.Client, headers: dict[str, str], filtros: dict[str, Any]) -> tuple[int, list[dict[str, Any]], str]:
    transacciones: list[dict[str, Any]] = []
    token: str | None = None
    for _ in range(MAX_PAGINAS):
        body: dict[str, Any] = {"filters": filtros, "limit": 1100}
        if token:
            body["pageToken"] = token
        time.sleep(PAUSA)
        try:
            resp = http.post(ACCOUNTING, json=body, headers=headers)
        except httpx.HTTPError as exc:
            return 0, transacciones, f"error de red ({type(exc).__name__})"
        if resp.status_code != 200:
            return resp.status_code, transacciones, _mensaje(resp)
        data = resp.json()
        transacciones += [t for t in data.get("transactions") or [] if isinstance(t, dict)]
        token = data.get("nextPageToken")
        if not token:
            return 200, transacciones, ""
    return 200, transacciones, f"(cortado en {MAX_PAGINAS} páginas)"


def _montos_crudos(transacciones: list[dict[str, Any]]) -> None:
    """Montos tal como llegan (sin escalar), para confirmar cómo se convierten a soles."""
    por_tipo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in transacciones:
        por_tipo[str(t.get("externalRelationKind"))].append(t)
    out("     Montos crudos por tipo (amount sin escalar · currencyScale):")
    for tipo, ts in sorted(por_tipo.items()):
        crudos = [t.get("amount") for t in ts]
        numeros = [float(a) for a in crudos if isinstance(a, (int, float)) or re.fullmatch(r"-?\d+(\.\d+)?", str(a))]
        escalas = Counter(str(t.get("currencyScale")) for t in ts)
        tipos = Counter(type(a).__name__ for a in crudos)
        resumen = f"mín {min(numeros)} · mediana {statistics.median(numeros)} · máx {max(numeros)}" if numeros else "sin números"
        out(f"       {tipo:<10} ejemplos {crudos[:5]} · {resumen} · escala {dict(escalas)} · tipo {dict(tipos)}")


def _medio_de_pago(metodos: list[dict[str, Any]]):
    nombres = {_norm(m.get(k)): str(m.get("name")) for m in metodos for k in ("name", "method", "code") if m.get(k)}
    nombres = {k: v for k, v in nombres.items() if len(k) >= 3}
    return lambda p: next((v for k, v in nombres.items() if k in _norm(p.get("description"))), SIN_MEDIO)


def _analizar_pagos(pagos: list[dict[str, Any]], metodos: list[dict[str, Any]], dia: date) -> None:
    medio = _medio_de_pago(metodos)
    por_medio: dict[str, list[float]] = defaultdict(list)
    cruce: Counter = Counter()
    for p in pagos:
        m = medio(p)
        por_medio[m].append(_monto(p))
        cruce[(str(p.get("internalTransactionCode")), m)] += 1
    out(f"     Pagos: {len(pagos)} · suma: {sum(_monto(p) for p in pagos):,.2f}")
    out("     Medio de pago deducido de la descripción: cantidad · suma")
    _tabla(por_medio)
    out("     Código interno × medio deducido (para mapear 9000 / 9100 / 9200…):")
    for (codigo, m), n in sorted(cruce.items()):
        out(f"       {codigo:<8} {m:<34} {n:>4}")
    fechas = Counter(
        ("businessDate=día" if p.get("businessDate") == dia.isoformat() else "businessDate≠día")
        + " · " + ("serviceDate=día" if p.get("serviceDate") == dia.isoformat() else "serviceDate≠día")
        for p in pagos
    )
    out("     Fechas de los pagos: " + ", ".join(f"{k} ({n})" for k, n in fechas.items()))


def sondear_contable(http: httpx.Client, key: str, pid: str, dia: date, tz: ZoneInfo, catalogo: dict[str, Any]) -> None:
    out("\n== 2. API contable: POST /accounting/v1.0/transactions (solo consulta)")
    headers = {"Authorization": f"Bearer {key}", "X-Property-ID": pid, "Accept": "application/json"}
    status, transacciones, msg = _buscar(http, headers, {"field": "service_date", "operator": "equals", "value": dia.isoformat()})
    out(f"  a) Por fecha de servicio (service_date = {dia}): HTTP {status} {msg}".rstrip())
    if status != 200:
        out("     [RESULTADO] La API contable no aceptó la consulta. Revisa que la key tenga read:payment.")
        return
    out(f"     {len(transacciones)} transacciones")
    if not transacciones:
        out("     No hay movimientos ese día. Prueba con otra fecha (--fecha).")
        return
    _valores_seguros(transacciones, "     ")
    _montos_crudos(transacciones)
    por_tipo: dict[str, list[float]] = defaultdict(list)
    por_codigo: Counter = Counter()
    for t in transacciones:
        por_tipo[str(t.get("externalRelationKind"))].append(_monto(t))
        por_codigo[(str(t.get("externalRelationKind")), str(t.get("internalTransactionCode")))] += 1
    out("     Totales por tipo (monto / 10^currencyScale): cantidad · suma")
    _tabla(por_tipo, 14)
    out("     Tipo × código interno: " + ", ".join(f"{k}/{c} ({n})" for (k, c), n in sorted(por_codigo.items())))

    # Extras: ¿cómo se llega al rubro? Por id del catálogo o por el nombre del ítem en la descripción.
    extras = [t for t in transacciones if t.get("externalRelationKind") in EXTRAS]
    por_id = {str(i.get("itemID")): i for i in catalogo["items"]}
    por_nombre = {_norm(i.get("name")): i for i in catalogo["items"] if i.get("name")}
    rubros: dict[str, list[float]] = defaultdict(list)
    via: Counter = Counter()
    for t in extras:
        item = por_id.get(str(t.get("externalRelationId")))
        if item:
            via["id"] += 1
        else:
            desc = _norm(t.get("description"))
            item = por_nombre.get(desc) or next((i for n, i in sorted(por_nombre.items(), key=lambda x: -len(x[0])) if n and n in desc), None)
            via["nombre" if item else "ninguno"] += 1
        rubros[str(item.get("categoryName")) if item else "(sin cruce con el catálogo)"].append(_monto(t))
    out(f"\n  b) Extras (ITEM, ITEM_POS, ADDON): {len(extras)} · cruce por id: {via['id']} · por nombre en la descripción: {via['nombre']} · sin cruce: {via['ninguno']}")
    out("     Ejemplos de externalRelationId: " + ", ".join(str(t.get("externalRelationId")) for t in extras[:3]))
    _tabla(rubros, 30)

    # Pagos: se prueban varias formas de filtrar por día para ver cuál acepta Cloudbeds.
    inicio = datetime.combine(dia, dtime.min, tz).astimezone(timezone.utc)
    fin = inicio + timedelta(days=1)
    z = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    ge = {"field": "transaction_datetime", "operator": "greater_than_or_equal", "value": z(inicio)}
    lt = {"field": "transaction_datetime", "operator": "less_than", "value": z(fin)}
    # Ronda 2: external_relation_kind solo se acepta junto con external_relation_id, y business_date
    # no sirve como filtro único. Lo que funciona es el rango de transaction_datetime y filtrar aquí.
    variantes = [("transaction_datetime (rango UTC del día de Lima)", {"and": [ge, lt]})]
    out(f"\n  c) Pagos del día {dia} (hora de Lima)")
    pagos: list[dict[str, Any]] | None = None
    for nombre, filtro in variantes:
        status, encontrados, msg = _buscar(http, headers, filtro)
        solo_pagos = [t for t in encontrados if t.get("externalRelationKind") == "PAYMENT"]
        detalle = f"{len(solo_pagos)} pagos de {len(encontrados)} transacciones" if status == 200 else msg
        out(f"     {nombre}: HTTP {status} · {detalle}")
        if status == 200 and pagos is None:
            pagos = solo_pagos
    if pagos is None:
        out("     Ningún filtro de pagos funcionó; se analizan los pagos de la consulta por fecha de servicio.")
        pagos = [t for t in transacciones if t.get("externalRelationKind") == "PAYMENT"]
    if pagos:
        _analizar_pagos(pagos, catalogo["metodos"], dia)


# ---------- 3. Insights ----------

def _insights_get(http: httpx.Client, headers: dict[str, str], ruta: str) -> Any:
    time.sleep(PAUSA)
    try:
        resp = http.get(INSIGHTS + ruta, headers=headers)
    except httpx.HTTPError as exc:
        out(f"  GET {ruta}: error de red ({type(exc).__name__})")
        return None
    out(f"  GET {ruta}: HTTP {resp.status_code} {'' if resp.status_code == 200 else _mensaje(resp)}".rstrip())
    return resp.json() if resp.status_code == 200 else None


def _consulta(pid: str, c: dict[str, Any], dia: date) -> dict[str, Any]:
    cdf = lambda col: {"type": "default", "column": col}  # noqa: E731
    metricas: dict[str, list[str]] = defaultdict(list)
    for col, metrica in c["metricas"]:
        metricas[col].append(metrica)
    return {
        "property_ids": [int(pid)],
        "dataset_id": c["dataset"],
        "columns": [{"cdf": cdf(col), "metrics": ms} for col, ms in metricas.items()],
        "group_rows": [{"cdf": cdf(col)} for col in c["agrupar"]],
        "filters": {"and": [
            {"cdf": cdf(c["fecha"]), "operator": "greater_than_or_equal", "value": f"{dia.isoformat()}T00:00:00"},
            {"cdf": cdf(c["fecha"]), "operator": "less_than", "value": f"{(dia + timedelta(days=1)).isoformat()}T00:00:00"},
        ]},
        "settings": {"details": False, "totals": True},
    }


def sondear_insights(http: httpx.Client, key: str, pid: str, dia: date) -> None:
    out("\n== 3. Insights API (reportes, encabezado X-API-KEY)")
    headers = {"X-API-KEY": key, "X-PROPERTY-ID": pid, "Accept-Language": "es", "Accept": "application/json"}
    if _insights_get(http, headers, "datasets") is None:
        out("  Sin acceso: la propiedad no tiene Cloudbeds Insights o la key no sirve para esta API.")
        return

    out("\n  Valores posibles de las columnas de agrupación (dataset 1, Financiero):")
    for col in LISTAS_INSIGHTS:
        lista = _insights_get(http, headers, f"datasets/1/{col}")
        if isinstance(lista, dict) and lista.get("options") is not None:
            out(f"    {col}: {_corto(lista.get('options'), 1500)}")

    permiso_denegado = False
    for c in CONSULTAS_INSIGHTS:
        time.sleep(PAUSA)
        try:
            resp = http.post(INSIGHTS + "reports/query/data", params={"mode": "Preview"},
                             json=_consulta(pid, c, dia), headers=headers)
        except httpx.HTTPError as exc:
            out(f"\n  {c['titulo']}: error de red ({type(exc).__name__})")
            continue
        out(f"\n  {c['titulo']}: HTTP {resp.status_code} {'' if resp.status_code == 200 else _mensaje(resp)}".rstrip())
        if resp.status_code == 403:
            permiso_denegado = True
        elif resp.status_code == 200:
            data = resp.json()
            for k in ("headers", "index", "records", "totals"):
                out(f"    {k}: {_corto(data.get(k), 3000)}")
    if permiso_denegado:
        out("\n  [RESULTADO] La key puede ver los datasets pero no ejecutar consultas: el usuario que autorizó")
        out("  la key no tiene permiso para ver reportes de Insights en Cloudbeds.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fase 0: sondeo de extras, pagos y reportes en Cloudbeds.")
    parser.add_argument("--alias", required=True, help="alias del hotel en hoteles.json (ej. balta)")
    parser.add_argument("--fecha", help="día a revisar, YYYY-MM-DD (por defecto, ayer)")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(ENV_PATH, override=False)
    catalogo = load_catalog()
    hotel = next((h for h in (catalogo.hoteles if catalogo else ()) if h.alias == args.alias), None)
    if hotel is None:
        print(f"[ERROR] No hay un hotel '{args.alias}' en hoteles.json. Agrégalo con scripts\\agregar_hotel.py.")
        return 2
    key = key_from_keyring(keyring_user(args.alias)) or os.getenv(env_key_var(args.alias), "").strip()
    if not key:
        print(f"[ERROR] No hay key para '{args.alias}'. Guárdala con scripts\\agregar_hotel.py --alias {args.alias}.")
        return 2
    tz = hotel.tz or ZoneInfo(os.getenv("CLOUDBEDS_TZ", "America/Lima"))
    try:
        dia = date.fromisoformat(args.fecha) if args.fecha else datetime.now(tz).date() - timedelta(days=1)
    except ValueError:
        print("[ERROR] --fecha debe tener el formato YYYY-MM-DD.")
        return 2

    out(f"Sondeo fase 0 (ronda 3) · {hotel.nombre} ({hotel.alias}) · propertyID {hotel.property_id} · día {dia}")
    out("La key no se muestra. Solo se muestran conteos, totales, montos y valores de catálogo.")
    base = {"Accept": "application/json", "User-Agent": "cloudbeds-mcp-sondeo"}
    with httpx.Client(headers={**base, "x-api-key": key}, timeout=60) as v13, httpx.Client(headers=base, timeout=60) as plano:
        cat = sondear_v13(v13, hotel.property_id)
        sondear_contable(plano, key, hotel.property_id, dia, tz, cat)
        sondear_insights(plano, key, hotel.property_id, dia)

    destino = PROJECT_ROOT / "logs" / f"sondeo_{hotel.alias}_{dia}.txt"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text("\n".join(out.lineas) + "\n", encoding="utf-8")
    print(f"\nResultado guardado en {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
