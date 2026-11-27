"""Desglose de precio de las reservas de Booking: formato del reporte, cálculo y textos.

Funciones puras (sin red), usadas por scripts/desglose_booking.py y por el servidor MCP.

Cálculo por noche (el mismo del reporte en Excel):
    promoción combinada  p = 1 − (1−p1)(1−p2)(1−p3)
    precio original      O = subtotal / ((1 − p)(1 − g))
    monto promoción        = O × p
    monto Genius           = (O − monto promoción) × g
    comisión               = subtotal × % comisión
    neto hotel             = subtotal − comisión
"""

from __future__ import annotations

import csv
import math
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Campos personalizados de reserva en Cloudbeds: clave -> (shortcode, nombre visible).
CAMPOS_BOOKING: dict[str, tuple[str, str]] = {
    "base_cb": ("bk_base_cb", "Booking: tarifa base Cloudbeds"),
    "original": ("bk_original", "Booking: precio original"),
    "promo": ("bk_promo", "Booking: promoción"),
    "genius": ("bk_genius", "Booking: Genius"),
    "subtotal": ("bk_subtotal", "Booking: subtotal sin IGV"),
    "comision": ("bk_comision", "Booking: comisión"),
    "neto": ("bk_neto", "Booking: neto hotel"),
}
MAX_CARACTERES_CAMPO = 60

HOJA_NOCHES = "Reporte por noche"
HOJA_RESERVAS = "Resumen por reserva"
HOJA_PARAMETROS = "Parámetros y notas"

# Columnas de entrada (datos leídos de Booking/Cloudbeds). clave -> encabezado exacto en el Excel.
# En el CSV de entrada se usa la clave como encabezado.
COLUMNAS: dict[str, str] = {
    "hotel": "Hotel",
    "reserva_booking": "N° reserva Booking",
    "habitacion_booking": "Habitación (Booking)",
    "tipo_cloudbeds": "Tipo de habitación en Cloudbeds",
    "noche": "Noche",
    "plan": "Plan de tarifa",
    "tarifa_base_cb": "1. Tarifa base Cloudbeds hoy (S/)",
    "promocion": "3. Promoción: nombre",
    "promo1": "Promo 1 %",
    "promo2": "Promo 2 %",
    "promo3": "Promo 3 %",
    "genius_pct": "4. Genius %",
    "genius_tipo": "4. Genius: tipo",
    "subtotal_usd": "5. Subtotal sin IGV (US$)",
    "comision_pct": "6. Comisión Booking %",
}
OBLIGATORIAS = ("hotel", "reserva_booking", "noche", "subtotal_usd", "comision_pct")
COMISION_INFORMADA = "Comisión informada por Booking (US$)"
GENIUS_TIPOS = {"fijo": "fijo", "dinamico": "dinámico", "dinámico": "dinámico", "—": "", "-": "", "": ""}
SIN_PROMO = {"", "sin promocion", "sin promoción", "—", "-"}


class FormatoError(ValueError):
    """El archivo no cumple el formato del reporte."""


@dataclass
class Noche:
    fila: int
    hotel: str
    reserva_booking: str
    noche: date
    subtotal: float
    comision_pct: float
    promos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    genius_pct: float = 0.0
    genius_tipo: str = ""
    promocion: str = ""
    plan: str = ""
    habitacion: str = ""
    tipo_cloudbeds: str = ""
    tarifa_base_cb: float | None = None

    @property
    def promo_pct(self) -> float:
        p1, p2, p3 = self.promos
        return 1 - (1 - p1) * (1 - p2) * (1 - p3)

    @property
    def original(self) -> float:
        return self.subtotal / ((1 - self.promo_pct) * (1 - self.genius_pct))

    @property
    def promo_monto(self) -> float:
        return self.original * self.promo_pct

    @property
    def genius_monto(self) -> float:
        return (self.original - self.promo_monto) * self.genius_pct

    @property
    def comision(self) -> float:
        return self.subtotal * self.comision_pct


@dataclass
class Reserva:
    hotel: str
    reserva_booking: str
    noches: list[Noche] = field(default_factory=list)
    comision_informada: float | None = None

    def total(self, attr: str) -> float:
        return sum(getattr(n, attr) for n in self.noches)

    @property
    def desde(self) -> date:
        return min(n.noche for n in self.noches)

    @property
    def hasta(self) -> date:
        return max(n.noche for n in self.noches)


# --- lectura -----------------------------------------------------------------------------------


def _norm(texto: Any) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())


def _num(valor: Any, donde: str, *, pct: bool = False, opcional: bool = False) -> float | None:
    if valor is None or (isinstance(valor, str) and valor.strip() in {"", "—", "-"}):
        if opcional:
            return None
        raise FormatoError(f"{donde}: falta el valor.")
    if isinstance(valor, str) and valor.strip().startswith("="):
        raise FormatoError(f"{donde}: es una fórmula; esta columna debe traer el dato, no una fórmula.")
    try:
        texto = str(valor).strip().replace("US$", "").replace("S/", "").replace(",", ".")
        es_pct = texto.endswith("%")
        n = float(texto.rstrip("%").strip())
    except ValueError:
        raise FormatoError(f"{donde}: '{valor}' no es un número.") from None
    if pct:
        if es_pct or n > 1:
            n /= 100  # acepta 23, "23%" o 0.23
        if not 0 <= n < 1:
            raise FormatoError(f"{donde}: porcentaje fuera de rango ({valor}).")
    elif n < 0 or math.isnan(n):
        raise FormatoError(f"{donde}: valor negativo o inválido ({valor}).")
    return n


def _fecha(valor: Any, donde: str) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            pass
    raise FormatoError(f"{donde}: fecha '{valor}' inválida (usa AAAA-MM-DD).")


def _reserva_id(valor: Any, donde: str) -> str:
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor or "").strip()
    if not texto.isdigit():
        raise FormatoError(f"{donde}: el N° de reserva de Booking debe ser solo dígitos ('{valor}').")
    return texto


def noche_desde_fila(datos: dict[str, Any], fila: int) -> Noche:
    """Convierte una fila (clave de COLUMNAS -> valor) en una Noche validada."""
    donde = f"Fila {fila}"
    for clave in OBLIGATORIAS:
        if datos.get(clave) in (None, ""):
            raise FormatoError(f"{donde}: falta '{COLUMNAS[clave]}'.")
    tipo = _norm(datos.get("genius_tipo"))
    if tipo not in {_norm(k) for k in GENIUS_TIPOS}:
        raise FormatoError(f"{donde}: Genius tipo '{datos.get('genius_tipo')}' (usa Fijo, Dinámico o —).")
    n = Noche(
        fila=fila,
        hotel=str(datos["hotel"]).strip(),
        reserva_booking=_reserva_id(datos["reserva_booking"], donde),
        noche=_fecha(datos["noche"], donde),
        subtotal=_num(datos["subtotal_usd"], f"{donde}, subtotal"),
        comision_pct=_num(datos["comision_pct"], f"{donde}, comisión %", pct=True),
        promos=tuple(  # type: ignore[arg-type]
            _num(datos.get(k), f"{donde}, {k}", pct=True, opcional=True) or 0.0 for k in ("promo1", "promo2", "promo3")
        ),
        genius_pct=_num(datos.get("genius_pct"), f"{donde}, Genius %", pct=True, opcional=True) or 0.0,
        genius_tipo=GENIUS_TIPOS.get(tipo, GENIUS_TIPOS.get(str(datos.get("genius_tipo") or "").strip().lower(), "")),
        promocion=str(datos.get("promocion") or "").strip(),
        plan=str(datos.get("plan") or "").strip(),
        habitacion=str(datos.get("habitacion_booking") or "").strip(),
        tipo_cloudbeds=str(datos.get("tipo_cloudbeds") or "").strip(),
        tarifa_base_cb=_num(datos.get("tarifa_base_cb"), f"{donde}, tarifa base", opcional=True),
    )
    if n.subtotal <= 0:
        raise FormatoError(f"{donde}: subtotal debe ser mayor que 0.")
    if n.genius_pct and not n.genius_tipo:
        raise FormatoError(f"{donde}: hay Genius % pero el tipo es '—'.")
    return n


def agrupar(noches: Iterable[Noche], comisiones: dict[str, float] | None = None) -> list[Reserva]:
    """Agrupa las filas (habitación-noche) por (hotel, reserva)."""
    reservas: dict[tuple[str, str], Reserva] = {}
    for n in noches:  # una fila por habitación y noche: una reserva de 2 habitaciones repite la noche
        r = reservas.setdefault((n.hotel, n.reserva_booking), Reserva(n.hotel, n.reserva_booking))
        r.noches.append(n)
    ids = [r.reserva_booking for r in reservas.values()]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise FormatoError(f"Reservas asignadas a más de un hotel: {', '.join(sorted(dup))}.")
    for r in reservas.values():
        r.noches.sort(key=lambda x: x.noche)
        if comisiones and r.reserva_booking in comisiones:
            r.comision_informada = comisiones[r.reserva_booking]
    return list(reservas.values())


def leer_excel(path: Path) -> tuple[list[Reserva], dict[str, Any]]:
    """Lee el reporte (.xlsx). Solo usa las columnas de datos; las fórmulas se recalculan aquí."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(path, read_only=True)
    except Exception as exc:  # archivo dañado, no es xlsx, abierto con bloqueo...
        raise FormatoError(f"No se pudo abrir {path.name}: {type(exc).__name__}.") from None
    if HOJA_NOCHES not in wb.sheetnames:
        raise FormatoError(f"Falta la hoja '{HOJA_NOCHES}'. Hojas: {', '.join(wb.sheetnames)}.")
    filas = list(wb[HOJA_NOCHES].iter_rows(values_only=True))
    cab_idx = next((i for i, f in enumerate(filas[:15]) if f and COLUMNAS["reserva_booking"] in f), None)
    if cab_idx is None:
        raise FormatoError(f"No se encontró la fila de encabezados (con '{COLUMNAS['reserva_booking']}').")
    cab = [str(c).strip() if c is not None else "" for c in filas[cab_idx]]
    faltan = [enc for enc in COLUMNAS.values() if enc not in cab]
    if faltan:
        raise FormatoError("Faltan columnas en '" + HOJA_NOCHES + "': " + "; ".join(faltan))
    pos = {clave: cab.index(enc) for clave, enc in COLUMNAS.items()}
    noches: list[Noche] = []
    for i, fila in enumerate(filas[cab_idx + 1 :], start=cab_idx + 2):
        valor_id = fila[pos["reserva_booking"]] if len(fila) > pos["reserva_booking"] else None
        if valor_id in (None, "") or _norm(fila[0]) == "total":
            continue
        noches.append(noche_desde_fila({k: fila[p] if p < len(fila) else None for k, p in pos.items()}, i))
    if not noches:
        raise FormatoError(f"La hoja '{HOJA_NOCHES}' no tiene noches.")

    comisiones: dict[str, float] = {}
    if HOJA_RESERVAS in wb.sheetnames:
        rf = list(wb[HOJA_RESERVAS].iter_rows(values_only=True))
        ci = next((i for i, f in enumerate(rf[:10]) if f and COMISION_INFORMADA in f), None)
        if ci is not None:
            ic, ir = rf[ci].index(COMISION_INFORMADA), rf[ci].index(COLUMNAS["reserva_booking"])
            for f in rf[ci + 1 :]:
                if f and f[ir] not in (None, "") and isinstance(f[ic], (int, float)):
                    comisiones[_reserva_id(f[ir], "Resumen por reserva")] = float(f[ic])
    params: dict[str, Any] = {}
    if HOJA_PARAMETROS in wb.sheetnames:
        for f in wb[HOJA_PARAMETROS].iter_rows(values_only=True):
            if f and f[0] and str(f[0]).startswith("K") and isinstance(f[1], (int, float)):
                params["k"] = float(f[1])
    wb.close()
    return agrupar(noches, comisiones), params


def leer_csv(path: Path) -> list[Noche]:
    """CSV de entrada (UTF-8, separador coma o punto y coma) con las claves de COLUMNAS como encabezado."""
    lineas = path.read_text(encoding="utf-8-sig").splitlines()
    if not lineas or not lineas[0].strip():
        raise FormatoError(f"{path.name} está vacío: falta la fila de encabezados.")
    try:
        dialecto = csv.Sniffer().sniff(lineas[0], delimiters=",;")
    except csv.Error:
        raise FormatoError(f"{path.name}: no se reconoce el separador (usa coma o punto y coma).") from None
    lector = csv.DictReader(lineas, dialect=dialecto)
    faltan = [c for c in COLUMNAS if c not in (lector.fieldnames or [])]
    if faltan:
        raise FormatoError(f"Faltan columnas en {path.name}: {', '.join(faltan)}.")
    return [noche_desde_fila(fila, i) for i, fila in enumerate(lector, start=2)]


# --- textos para Cloudbeds -------------------------------------------------------------------


def _usd(x: float) -> str:
    return f"US$ {x:,.2f}"


def _pct(x: float) -> str:
    texto = f"{x * 100:.1f}".rstrip("0").rstrip(".")
    return f"{texto} %"


def _corta(texto: str, limite: int = MAX_CARACTERES_CAMPO) -> str:
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def valores_campos(r: Reserva) -> dict[str, str]:
    """Los 7 textos (≤ 60 caracteres) que van a los campos personalizados de la reserva."""
    n = len(r.noches)
    noches = len({x.noche for x in r.noches})
    if n == noches:
        en = f" en {n} noches" if n > 1 else ""
    else:
        en = f" en {n} noches-hab."
    original, promo, genius = r.total("original"), r.total("promo_monto"), r.total("genius_monto")
    subtotal, comision = r.total("subtotal"), r.total("comision")
    if r.comision_informada is not None:
        comision = r.comision_informada
    neto = subtotal - comision

    bases = [x.tarifa_base_cb for x in r.noches]
    if all(b is None for b in bases):
        base = "sin tarifa en Cloudbeds"
    else:
        base = f"S/ {sum(b or 0 for b in bases):,.2f}{en} (tarifa hoy)"
        if any(b is None for b in bases):
            base = f"S/ {sum(b or 0 for b in bases):,.2f} ({sum(b is not None for b in bases)} de {n} noches)"

    nombres = sorted({p.strip() for x in r.noches for p in x.promocion.split(";") if _norm(p) not in SIN_PROMO})
    if promo > 0.005:
        promo_txt = _corta(f"{' + '.join(nombres) or 'Promoción'} {_pct(promo / original)}", 46) + f": -{_usd(promo)}"
    else:
        promo_txt = "Sin promoción"
    if genius > 0.005:
        tipos = {x.genius_tipo for x in r.noches if x.genius_pct}
        tipo = tipos.pop() if len(tipos) == 1 else "mixto"
        genius_txt = f"Genius {_pct(genius / (original - promo))} {tipo}: -{_usd(genius)}".replace("  ", " ")
    else:
        genius_txt = "Sin Genius"
    return {
        "base_cb": _corta(base),
        "original": _corta(f"{_usd(original)} sin IGV{en}"),
        "promo": _corta(promo_txt),
        "genius": _corta(genius_txt),
        "subtotal": _corta(f"{_usd(subtotal)}{en}"),
        "comision": _corta(f"{_pct(comision / subtotal)}: {_usd(comision)}"),
        "neto": _corta(f"{_usd(neto)} ({_pct(neto / original)} del original)"),
    }


def encabezado_nota(reserva_booking: str) -> str:
    """Inicio de la nota del desglose; sirve para saber si la reserva ya la tiene."""
    return f"Desglose Booking {reserva_booking}"


def encabezado_anulacion(reserva_booking: str) -> str:
    return f"ANULADO · Desglose Booking {reserva_booking}"


def nota_anulacion(reserva_booking: str, campos: dict[str, str], hoy: date) -> str:
    """Nota para una reserva cancelada que ya tenía el desglose: sus montos no son ingreso.
    `campos` es shortcode -> valor actual en Cloudbeds."""
    def v(clave: str) -> str:
        return campos.get(CAMPOS_BOOKING[clave][0]) or "—"

    return "\n".join([
        encabezado_anulacion(reserva_booking),
        "Reserva CANCELADA: NO considerar como ingreso los montos de los campos «Booking: …» de esta reserva.",
        f"Montos anulados: subtotal {v('subtotal')} | comisión {v('comision')} | neto {v('neto')}.",
        f"Registrado por cloudbeds-mcp el {hoy:%Y-%m-%d}.",
    ])


def nota(r: Reserva, archivo: str, hoy: date) -> str:
    """Nota de la reserva con el cálculo noche por noche."""
    v = valores_campos(r)
    lineas = [f"{encabezado_nota(r.reserva_booking)} ({r.hotel}, {len(r.noches)} noche(s)-habitación)"]
    for x in r.noches:
        base = f"base CB S/ {x.tarifa_base_cb:,.2f} | " if x.tarifa_base_cb is not None else ""
        promo = f"{x.promocion or 'promo'} -{_pct(x.promo_pct)} " if x.promo_pct else ""
        genius = f"Genius {x.genius_tipo} -{_pct(x.genius_pct)} " if x.genius_pct else ""
        lineas.append(
            f"{x.noche:%d/%m} {x.tipo_cloudbeds or x.habitacion}: {base}original {_usd(x.original)} "
            f"{promo}{genius}-> subtotal {_usd(x.subtotal)}; comisión {_pct(x.comision_pct)} {_usd(x.comision)}"
        )
    lineas.append(f"Total: original {v['original']} | {v['promo']} | {v['genius']}")
    lineas.append(f"Subtotal {v['subtotal']} | comisión {v['comision']} | neto {v['neto']}")
    lineas.append(f"Fuente: {archivo}. Cargado por cloudbeds-mcp el {hoy:%Y-%m-%d}.")
    return "\n".join(lineas)
