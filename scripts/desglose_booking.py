"""Desglose de las reservas de Booking: lista de pendientes, reporte en Excel y carga a Cloudbeds.

Tarea diaria (ver skills/zentra-desglose-booking/SKILL.md), desde la raíz del proyecto, en Windows:
    .\\.venv\\Scripts\\python.exe scripts\\desglose_booking.py pendientes
        -> reportes\\booking\\pendientes_AAAA-MM-DD.csv: reservas de Booking en Cloudbeds que pernoctan
           desde anoche o llegan después y que hay que leer en el extranet (nuevas o modificadas).
    (Claude lee esas reservas en Booking y escribe reportes\\booking\\lectura_AAAA-MM-DD.csv)
    .\\.venv\\Scripts\\python.exe scripts\\desglose_booking.py agregar --lectura reportes\\booking\\lectura_AAAA-MM-DD.csv
        -> fusiona la lectura en noches_AAAA-MM.csv (mes de llegada) y rehace reporte_booking_AAAA-MM.xlsx.
    .\\.venv\\Scripts\\python.exe scripts\\desglose_booking.py cargar               (vista previa)
    .\\.venv\\Scripts\\python.exe scripts\\desglose_booking.py cargar --confirmar

Otros comandos: validar --excel X.xlsx · generar --noches X.csv --k 3.43 --salida X.xlsx · exportar.

`cargar` escribe en cada reserva de Cloudbeds (buscada por su N° de Booking) 7 campos personalizados
y una nota con el cálculo: 8 datos. Sin --confirmar no escribe nada. Solo escribe lo que cambió, así
que se puede correr todos los días. Si la reserva fue cancelada y tenía el desglose, deja una nota
de anulación (sus montos no son ingreso) y la saca del reporte (pasa a canceladas.csv). Si las
fechas o las habitaciones de Cloudbeds ya no coinciden con lo leído en Booking, no escribe y la
reserva vuelve a salir en `pendientes`. Nunca cambia estado, fechas, habitaciones, tarifas, pagos ni
ajustes. Deja un registro CSV en logs/.

Días perdidos: `cargar --confirmar` sin errores guarda la noche procesada en reportes\\booking\\estado.json;
la siguiente corrida empieza en la noche siguiente a esa, así que un día sin correr se recupera solo.

Códigos de salida: 0 bien (las «no encontrada», «a releer» y «a revisar» se informan y se reintentan
al día siguiente) · 1 alguna reserva con error · 2 archivo inválido, sin acceso o sin conexión.
El formato está en skills/zentra-desglose-booking/FORMATO.md.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from cloudbeds_mcp import desglose as dg  # noqa: E402
from cloudbeds_mcp.config import configure_logging, load_hotels  # noqa: E402
from cloudbeds_mcp.errors import CloudbedsError, ConfigError, HotelError  # noqa: E402
from cloudbeds_mcp.hotels import HotelRegistry  # noqa: E402

ERRORES = (CloudbedsError, ConfigError, HotelError)
CARPETA = RAIZ / "reportes" / "booking"
LIMA = ZoneInfo("America/Lima")
ACTIVAS = frozenset({"confirmed", "not_confirmed", "checked_in", "checked_out"})
CANCELADA = "canceled"
DIAS_FUTURO = 731  # reservas futuras: hasta 2 años
MAX_RESERVAS = 5000
CAMPOS_CSV = [*dg.COLUMNAS, "comision_informada_usd"]
COLS_PENDIENTES = ["hotel", "reserva_booking", "reserva_cloudbeds", "llegada", "salida", "noches_hab",
                   "tipos_cloudbeds", "estado_cloudbeds", "motivo", "huella_cloudbeds"]


def _p(*args: Any) -> None:
    print(*args, flush=True)


def _hoy() -> date:
    return datetime.now(LIMA).date()


# --- archivos locales ---------------------------------------------------------------------------


def _filas_csv(path: Path) -> list[dict[str, str]]:
    lineas = path.read_text(encoding="utf-8-sig").splitlines()
    if not lineas or not lineas[0].strip():
        return []
    try:
        dialecto = csv.Sniffer().sniff(lineas[0], delimiters=",;")
    except csv.Error:
        raise dg.FormatoError(f"{path.name}: no se reconoce el separador (usa coma o punto y coma).") from None
    return [{k: (v or "").strip() for k, v in f.items() if k} for f in csv.DictReader(lineas, dialect=dialecto)]


def _id(fila: dict[str, str]) -> str:
    return fila.get("reserva_booking", "").strip().removesuffix(".0")


def _reemplazar(tmp: Path, destino: Path) -> None:
    try:
        os.replace(tmp, destino)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        raise OSError(f"No se pudo reemplazar {destino.name}: ciérralo en Excel y repite.") from None


def _escribir_csv(path: Path, filas: list[dict[str, str]], *, directo: bool = False) -> Path:
    """Escribe en path.tmp y devuelve esa ruta (o reemplaza path si directo=True)."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS_CSV, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
    if directo:
        _reemplazar(tmp, path)
        return path
    return tmp


def _archivos_noches(carpeta: Path) -> list[Path]:
    return sorted(carpeta.glob("noches_[0-9][0-9][0-9][0-9]-[0-9][0-9].csv"))


def _comisiones_csv(path: Path) -> dict[str, float]:
    """Columna opcional comision_informada_usd del CSV (basta en una noche de cada reserva)."""
    out: dict[str, float] = {}
    for fila in _filas_csv(path):
        v = fila.get("comision_informada_usd", "").replace(",", ".")
        if v:
            try:
                out[_id(fila)] = float(v)
            except ValueError:
                raise dg.FormatoError(f"{path.name}: comision_informada_usd '{v}' no es un número.") from None
    return out


def _almacen(carpeta: Path) -> dict[str, dg.Reserva]:
    """Todas las reservas leídas en Booking (noches_AAAA-MM.csv), por N° de Booking."""
    out: dict[str, dg.Reserva] = {}
    for p in _archivos_noches(carpeta):
        for r in dg.agrupar(dg.leer_csv(p), _comisiones_csv(p)):
            out[r.reserva_booking] = r
    return out


def _estado(carpeta: Path) -> dict[str, Any]:
    p = carpeta / "estado.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        _p(f"AVISO: {p.name} está dañado; se ignora.")
        return {}


def _guardar_estado(carpeta: Path, estado: dict[str, Any]) -> None:
    p = carpeta / "estado.json"
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def _noche_inicio(carpeta: Path, desde: date | None) -> date:
    """Primera noche a revisar: ayer, o la siguiente a la última corrida buena si hubo días sin correr."""
    ayer = _hoy() - timedelta(days=1)
    if desde:
        return desde
    ultima = _estado(carpeta).get("ultima_noche_ok")
    if ultima:
        try:
            return min(ayer, date.fromisoformat(ultima) + timedelta(days=1))
        except ValueError:
            pass
    return ayer


def _leer_k(path: Path) -> float | None:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(path, read_only=True)
    except Exception:  # noqa: BLE001 - archivo dañado o bloqueado: se prueba el siguiente
        return None
    try:
        if dg.HOJA_PARAMETROS not in wb.sheetnames:
            return None
        for f in wb[dg.HOJA_PARAMETROS].iter_rows(values_only=True):
            if f and f[0] and str(f[0]).startswith("K") and len(f) > 1 and isinstance(f[1], (int, float)):
                return float(f[1])
        return None
    finally:
        wb.close()


def _k_para(carpeta: Path, mes: str, k: float | None) -> float:
    """K del mes: --k, o el del Excel de ese mes, o el del mes anterior más cercano, o el de cualquier otro."""
    if k:
        return k
    otros = sorted(carpeta.glob("reporte_booking_[0-9][0-9][0-9][0-9]-[0-9][0-9].xlsx"))
    meses = {p.stem.removeprefix("reporte_booking_"): p for p in otros}
    orden = [mes] + sorted((m for m in meses if m < mes), reverse=True) + sorted(m for m in meses if m > mes)
    for m in orden:
        if m in meses and (valor := _leer_k(meses[m])):
            return valor
    raise dg.FormatoError(f"No hay K para {mes}: no existe un reporte previo. Indica --k (S/ por US$).")


# --- Excel --------------------------------------------------------------------------------------


def _generar_excel(noches_csv: Path, k: float, salida: Path, titulo: str | None = None) -> tuple[int, int]:
    """Arma el Excel del reporte desde el CSV de noches. Lo valida antes de reemplazar el anterior."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    noches = dg.leer_csv(noches_csv)
    if not noches:
        raise dg.FormatoError(f"{noches_csv.name} no tiene noches.")
    reservas = dg.agrupar(noches, _comisiones_csv(noches_csv))
    noches = sorted(noches, key=lambda n: (n.hotel, n.noche, n.reserva_booking))
    azul, negrita = Font(color="1F4E9E"), Font(bold=True)
    cab_fill = PatternFill("solid", fgColor="D9E1F2")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = dg.HOJA_NOCHES
    ws.append([titulo or f"Reporte de reservas Booking (una fila por noche) · {salida.stem}"])
    ws.append([f'Azul = dato leído de Booking/Cloudbeds · Negro = fórmula · K y supuestos en la hoja "{dg.HOJA_PARAMETROS}"'])
    ws.append([])
    c = dg.COLUMNAS
    cab = [c["hotel"], c["reserva_booking"], c["habitacion_booking"], c["tipo_cloudbeds"], c["noche"], c["plan"],
           c["tarifa_base_cb"], "2. Precio original Booking (US$ sin IGV)", c["promocion"], c["promo1"], c["promo2"],
           c["promo3"], "3. Promoción: % combinado", "3. Promoción: monto (US$)", c["genius_pct"],
           "4. Genius: monto (US$)", c["genius_tipo"], c["subtotal_usd"], c["comision_pct"],
           "6. Comisión Booking: monto (US$)", "7. Neto para el hotel (US$)", "Base implícita (S/) = original × K",
           "Dif. base implícita vs Cloudbeds hoy"]
    ws.append(cab)
    primera = 5
    for i, n in enumerate(noches, start=primera):
        ws.append([
            n.hotel, int(n.reserva_booking), n.habitacion, n.tipo_cloudbeds, n.noche, n.plan, n.tarifa_base_cb,
            f"=R{i}/((1-M{i})*(1-O{i}))", n.promocion or "Sin promoción",
            n.promos[0] or None, n.promos[1] or None, n.promos[2] or None,
            f"=1-(1-N(J{i}))*(1-N(K{i}))*(1-N(L{i}))", f"=H{i}*M{i}", n.genius_pct, f"=(H{i}-N{i})*O{i}",
            n.genius_tipo.capitalize() if n.genius_tipo else "—", n.subtotal, n.comision_pct,
            f"=R{i}*S{i}", f"=R{i}-T{i}", f"=H{i}*'{dg.HOJA_PARAMETROS}'!$B$4", f'=IF(G{i}="","",V{i}/G{i}-1)',
        ])
        for col in (1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 15, 17, 18, 19):
            ws.cell(i, col).font = azul
        ws.cell(i, 5).number_format = "yyyy-mm-dd"
        for col in (10, 11, 12, 13, 15, 19, 23):
            ws.cell(i, col).number_format = "0.0%"
        for col in (8, 14, 16, 18, 20, 21, 22):
            ws.cell(i, col).number_format = "#,##0.00"
    ultima = primera + len(noches) - 1
    t = ultima + 1
    ws.append(["TOTAL"] + [None] * 6 + [f"=SUM(H{primera}:H{ultima})"] + [None] * 5 + [f"=SUM(N{primera}:N{ultima})", None,
              f"=SUM(P{primera}:P{ultima})", None, f"=SUM(R{primera}:R{ultima})", None, f"=SUM(T{primera}:T{ultima})",
              f"=SUM(U{primera}:U{ultima})"])
    for col in range(1, 24):
        ws.cell(4, col).font, ws.cell(4, col).fill = negrita, cab_fill
        ws.cell(t, col).font = negrita
        ws.column_dimensions[get_column_letter(col)].width = 14
    ws.freeze_panes = "C5"
    rn = f"'{dg.HOJA_NOCHES}'!$B${primera}:$B${ultima}"
    ra = f"'{dg.HOJA_NOCHES}'!$A${primera}:$A${ultima}"

    def col_n(letra: str) -> str:
        return f"'{dg.HOJA_NOCHES}'!${letra}${primera}:${letra}${ultima}"

    wr = wb.create_sheet(dg.HOJA_RESERVAS)
    wr.append(["Resumen por reserva (suma de las noches)"])
    wr.append([])
    wr.append(["Hotel", c["reserva_booking"], "Noches", "Tipo de comisión", "2. Precio original (US$)", "3. Promoción (US$)",
               "4. Genius (US$)", "5. Subtotal sin IGV (US$)", "6. Comisión (US$)", "6. Comisión %", "7. Neto hotel (US$)",
               dg.COMISION_INFORMADA, "Diferencia (US$)"])
    for i, r in enumerate(sorted(reservas, key=lambda x: (x.hotel, x.desde)), start=4):
        wr.append([r.hotel, int(r.reserva_booking), f"=COUNTIF({rn},B{i})",
                   f'=IF(ROUND(J{i},2)=0.15,"Estándar (15%)",IF(ROUND(J{i},2)=0.23,"Mayor (23%)","Revisar"))',
                   f"=SUMIFS({col_n('H')},{rn},B{i})", f"=SUMIFS({col_n('N')},{rn},B{i})",
                   f"=SUMIFS({col_n('P')},{rn},B{i})", f"=SUMIFS({col_n('R')},{rn},B{i})",
                   f"=SUMIFS({col_n('T')},{rn},B{i})", f"=IF(H{i}=0,0,I{i}/H{i})", f"=SUMIFS({col_n('U')},{rn},B{i})",
                   r.comision_informada, f'=IF(L{i}="","",I{i}-L{i})'])
        wr.cell(i, 12).font = azul
        wr.cell(i, 10).number_format = "0.0%"
    ultima_r = 3 + len(reservas)
    for col in range(1, 14):
        wr.cell(3, col).font, wr.cell(3, col).fill = negrita, cab_fill
        wr.column_dimensions[get_column_letter(col)].width = 16

    wh = wb.create_sheet("Resumen por hotel")
    wh.append(["Resumen por hotel (reservas leídas en Booking)"])
    wh.append([])
    wh.append(["Hotel", "Reservas", "Noches", "2. Precio original (US$)", "3. Promoción (US$)", "4. Genius (US$)",
               "5. Subtotal sin IGV (US$)", "6. Comisión (US$)", "Comisión efectiva %", "7. Neto hotel (US$)"])
    hoteles = sorted({r.hotel for r in reservas})
    for i, h in enumerate(hoteles, start=4):
        wh.append([h, f"=COUNTIF('{dg.HOJA_RESERVAS}'!$A$4:$A${ultima_r},A{i})", f"=COUNTIF({ra},A{i})"]
                  + [f"=SUMIFS({col_n(x)},{ra},A{i})" for x in ("H", "N", "P", "R", "T")]
                  + [f"=IF(G{i}=0,0,H{i}/G{i})", f"=SUMIFS({col_n('U')},{ra},A{i})"])
        wh.cell(i, 9).number_format = "0.0%"
    f = 4 + len(hoteles)
    wh.append(["TOTAL"] + [f"=SUM({get_column_letter(x)}4:{get_column_letter(x)}{f - 1})" for x in range(2, 9)]
              + [f"=IF(G{f}=0,0,H{f}/G{f})", f"=SUM(J4:J{f - 1})"])
    for col in range(1, 11):
        wh.cell(3, col).font, wh.cell(3, col).fill = negrita, cab_fill
        wh.cell(f, col).font = negrita
        wh.column_dimensions[get_column_letter(col)].width = 18

    wp = wb.create_sheet(dg.HOJA_PARAMETROS)
    wp.append(["Parámetros y notas"])
    wp.append([])
    wp.append(["Parámetro", "Valor"])
    wp.append(["K — tipo de cambio de referencia (S/ por US$)", k])
    wp.append([])
    wp.append(["Cómo se calcula cada columna"])
    for fila in (
        ("2. Precio original (US$)", "Subtotal ÷ [(1 − % promoción combinado) × (1 − % Genius)]."),
        ("3. Promoción", "Combinadas: 1 − (1−p1)(1−p2)(1−p3), aplicadas primero. Monto = original × % combinado."),
        ("4. Genius", "Monto = (original − promoción) × %. Fijo = «Genius discount x%»; Dinámico = «Genius Dynamic Pricing discount x%»."),
        ("5. Subtotal sin IGV (US$)", "Precio por noche del detalle de la reserva en el extranet (dato leído)."),
        ("6. Comisión Booking", "Comisión que Booking informa por reserva ÷ subtotal de sus noches (15 % o 23 %)."),
        ("7. Neto para el hotel", "Subtotal − comisión (US$)."),
        ("Base implícita (S/)", "Precio original × K, para comparar con la tarifa base de Cloudbeds de hoy."),
        ("Canceladas", "Las reservas canceladas salen de este reporte y pasan a canceladas.csv."),
        ("Generado", f"{datetime.now(LIMA):%Y-%m-%d %H:%M} con scripts/desglose_booking.py, desde {noches_csv.name}."),
    ):
        wp.append(list(fila))
    wp.cell(4, 2).font = azul
    wp.column_dimensions["A"].width, wp.column_dimensions["B"].width = 46, 110

    salida.parent.mkdir(parents=True, exist_ok=True)
    tmp = salida.with_name(salida.stem + ".tmp.xlsx")
    wb.save(tmp)
    try:
        dg.leer_excel(tmp)  # el archivo generado debe pasar la validación
    except dg.FormatoError:
        tmp.unlink(missing_ok=True)
        raise
    _reemplazar(tmp, salida)
    return len(reservas), len(noches)


def _rehacer_mes(carpeta: Path, mes: str, k: float | None) -> str:
    """Rehace el Excel de un mes desde su CSV; si el CSV quedó sin filas, borra el Excel."""
    noches_csv, excel = carpeta / f"noches_{mes}.csv", carpeta / f"reporte_booking_{mes}.xlsx"
    if not _filas_csv(noches_csv):
        excel.unlink(missing_ok=True)
        return f"{mes}: sin reservas (se quitó el Excel)"
    nr, nn = _generar_excel(noches_csv, k, excel)
    return f"{excel.name}: {nr} reservas, {nn} noches-hab."


# --- validar / generar / exportar --------------------------------------------------------------


def cmd_validar(args: argparse.Namespace) -> int:
    reservas, params = dg.leer_excel(Path(args.excel))
    noches = sum(len(r.noches) for r in reservas)
    _p(f"OK: {len(reservas)} reservas, {noches} noches. K = {params.get('k', 'no indicado')}.")
    por_hotel: dict[str, int] = defaultdict(int)
    for r in reservas:
        por_hotel[r.hotel] += 1
    for h, n in sorted(por_hotel.items()):
        _p(f"  {h}: {n} reservas")
    for r in reservas:
        if r.comision_informada is not None and abs(r.comision_informada - r.total("comision")) > 0.05:
            _p(f"  AVISO {r.reserva_booking}: comisión informada {r.comision_informada:.2f} y calculada "
               f"{r.total('comision'):.2f}. Se cargará la informada.")
    if args.mostrar:
        for r in reservas:
            if r.reserva_booking in args.mostrar:
                _p(f"\n{r.reserva_booking}:")
                for k, v in dg.valores_campos(r).items():
                    _p(f"  {dg.CAMPOS_BOOKING[k][1]}: {v}")
                _p("  Nota:\n    " + dg.nota(r, Path(args.excel).name, _hoy()).replace("\n", "\n    "))
    return 0


def cmd_generar(args: argparse.Namespace) -> int:
    salida = Path(args.salida)
    nr, nn = _generar_excel(Path(args.noches), args.k, salida, args.titulo)
    _p(f"Generado {salida}: {nr} reservas, {nn} noches.")
    return 0


def cmd_exportar(args: argparse.Namespace) -> int:
    reservas, params = dg.leer_excel(Path(args.excel))
    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    filas: list[dict[str, str]] = []
    for r in reservas:
        for i, n in enumerate(r.noches):
            filas.append({
                "hotel": n.hotel, "reserva_booking": n.reserva_booking, "habitacion_booking": n.habitacion,
                "tipo_cloudbeds": n.tipo_cloudbeds, "noche": n.noche.isoformat(), "plan": n.plan,
                "tarifa_base_cb": "" if n.tarifa_base_cb is None else f"{n.tarifa_base_cb:g}",
                "promocion": n.promocion or "Sin promoción",
                **{f"promo{j}": f"{n.promos[j - 1]:g}" if n.promos[j - 1] else "" for j in (1, 2, 3)},
                "genius_pct": f"{n.genius_pct:g}", "genius_tipo": n.genius_tipo.capitalize() if n.genius_tipo else "—",
                "subtotal_usd": f"{n.subtotal:g}", "comision_pct": f"{n.comision_pct:g}",
                "comision_informada_usd": f"{r.comision_informada:g}" if i == 0 and r.comision_informada is not None else "",
            })
    _escribir_csv(salida, filas, directo=True)
    _p(f"Exportado {salida}: {len(reservas)} reservas, {len(filas)} filas. K del archivo: {params.get('k', 'no indicado')}.")
    return 0


# --- agregar ------------------------------------------------------------------------------------


def _huellas_pendientes(carpeta: Path) -> dict[str, str]:
    """N° de Booking -> huella de Cloudbeds del último pendientes_*.csv."""
    archivos = sorted(carpeta.glob("pendientes_*.csv"))
    if not archivos:
        return {}
    return {_id(f): f.get("huella_cloudbeds", "") for f in _filas_csv(archivos[-1]) if _id(f)}


def cmd_agregar(args: argparse.Namespace) -> int:
    carpeta, lectura = Path(args.carpeta), Path(args.lectura)
    carpeta.mkdir(parents=True, exist_ok=True)
    noches = dg.leer_csv(lectura)  # valida la lectura completa antes de tocar nada
    if not noches:
        _p("La lectura no tiene filas: no hay nada que agregar.")
        return 0
    reservas = dg.agrupar(noches, _comisiones_csv(lectura))
    nuevas: dict[str, list[dict[str, str]]] = defaultdict(list)
    for f in _filas_csv(lectura):
        f["reserva_booking"] = _id(f)
        nuevas[f["reserva_booking"]].append(f)
    ids = set(nuevas)

    contenido = {p.stem.removeprefix("noches_"): _filas_csv(p) for p in _archivos_noches(carpeta)}
    afectados: set[str] = set()
    reemplazadas = 0
    for mes, filas in contenido.items():
        quedan = [f for f in filas if _id(f) not in ids]
        if len(quedan) != len(filas):
            reemplazadas += len({_id(f) for f in filas} & ids)
            contenido[mes] = quedan
            afectados.add(mes)
    for r in reservas:
        mes = f"{r.desde:%Y-%m}"  # el mes del archivo es el de la llegada
        contenido.setdefault(mes, []).extend(nuevas[r.reserva_booking])
        afectados.add(mes)

    ks = {mes: _k_para(carpeta, mes, args.k) for mes in afectados if contenido[mes]}
    tmps: dict[str, Path] = {}
    try:
        for mes in sorted(afectados):
            tmps[mes] = _escribir_csv(carpeta / f"noches_{mes}.csv", contenido[mes])
            dg.leer_csv(tmps[mes])
    except Exception:
        for t in tmps.values():
            t.unlink(missing_ok=True)
        raise
    for mes, tmp in tmps.items():
        _reemplazar(tmp, carpeta / f"noches_{mes}.csv")
    for mes in sorted(afectados):
        _p("  " + _rehacer_mes(carpeta, mes, ks.get(mes)))

    # Si Cloudbeds tiene otras fechas/habitaciones que Booking (cambio hecho solo en Cloudbeds), se acepta
    # la diferencia para no volver a leer la reserva cada día.
    huellas, estado = _huellas_pendientes(carpeta), _estado(carpeta)
    aceptadas: dict[str, str] = estado.setdefault("aceptadas", {})
    for r in reservas:
        h = huellas.get(r.reserva_booking)
        if h and h != _huella_local(r):
            aceptadas[r.reserva_booking] = h
            _p(f"  AVISO {r.reserva_booking}: Cloudbeds tiene {h} y Booking {_huella_local(r)} (llegada|salida|noches-hab.). "
               "Se carga lo leído en Booking; revisa la reserva en Cloudbeds.")
        else:
            aceptadas.pop(r.reserva_booking, None)
    _guardar_estado(carpeta, estado)
    _p(f"Agregadas {len(reservas)} reservas ({len(noches)} noches-hab.); {reemplazadas} ya estaban y se reemplazaron.")
    return 0


# --- Cloudbeds ----------------------------------------------------------------------------------


def _es_booking(r: dict[str, Any]) -> bool:
    return "booking.com" in str(r.get("sourceName") or "").lower() and str(r.get("thirdPartyIdentifier") or "").strip().isdigit()


async def _reservas_booking(client: Any, co_desde: date, co_hasta: date) -> dict[str, list[dict[str, Any]]]:
    """Reservas de Booking.com en Cloudbeds con salida en [co_desde, co_hasta], por N° de Booking."""
    res = await client.get_all(
        "getReservations",
        {"propertyID": client.settings.property_id, "checkOutFrom": co_desde.isoformat(), "checkOutTo": co_hasta.isoformat()},
        max_results=MAX_RESERVAS,
    )
    if res.get("truncado"):
        raise CloudbedsError(f"Cloudbeds devolvió más de {MAX_RESERVAS} reservas; la lista quedó incompleta. Acota con --desde.")
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in res["data"]:
        if _es_booking(r):
            out[str(r["thirdPartyIdentifier"]).strip()].append(r)
    return out


def _clasificar(lista: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    activas = [x for x in lista if x.get("status") in ACTIVAS]
    if len(activas) > 1:
        return "ambigua", activas
    if activas:
        return "activa", activas
    canceladas = [x for x in lista if x.get("status") == CANCELADA]
    if canceladas:
        return "cancelada", canceladas
    return "otra", lista


async def _detalle(client: Any, cb_id: str) -> dict[str, Any]:
    body = await client.get("getReservation", {"propertyID": client.settings.property_id, "reservationID": cb_id})
    return body.get("data") or {}


def _campos(det: dict[str, Any]) -> dict[str, str]:
    return {str(f.get("shortcode")): str(f.get("customFieldValue") or "") for f in det.get("customFields") or []}


def _fecha(valor: Any) -> date | None:
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def _huella(det: dict[str, Any]) -> str:
    """llegada|salida|noches-habitación de la reserva en Cloudbeds."""
    ini, fin = _fecha(det.get("startDate")), _fecha(det.get("endDate"))
    total = 0
    for x in (det.get("assigned") or []) + (det.get("unassigned") or []):
        a, b = _fecha(x.get("startDate")) or ini, _fecha(x.get("endDate")) or fin
        total += (b - a).days if a and b else 0
    return f"{ini}|{fin}|{total}"


def _huella_local(r: dg.Reserva) -> str:
    return f"{r.desde}|{r.hasta + timedelta(days=1)}|{len(r.noches)}"


def _coincide(r: dg.Reserva, huella_cb: str, estado: dict[str, Any]) -> bool:
    return _huella_local(r) == huella_cb or (estado.get("aceptadas") or {}).get(r.reserva_booking) == huella_cb


def _tipos(det: dict[str, Any]) -> str:
    return "; ".join(sorted({str(x.get("roomTypeName") or "").strip()
                             for x in (det.get("assigned") or []) + (det.get("unassigned") or [])} - {""}))


async def _notas(client: Any, cb_id: str) -> list[str]:
    body = await client.get("getReservationNotes", {"propertyID": client.settings.property_id, "reservationID": cb_id})
    data = body.get("data") or []
    return [str(x.get("reservationNote") or "").strip() for x in data if isinstance(x, dict)]


def _misma_sede(reg: HotelRegistry, nombre: str, alias: str) -> bool:
    try:
        return reg.hotel(nombre).alias == alias
    except HotelError:
        return False


# --- pendientes ---------------------------------------------------------------------------------


async def _pendientes(args: argparse.Namespace) -> int:
    carpeta = Path(args.carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    hoy, inicio = _hoy(), _noche_inicio(carpeta, args.desde)
    almacen, estado = _almacen(carpeta), _estado(carpeta)
    _p(f"Reservas de Booking que pernoctan desde la noche del {inicio:%d-%m-%Y} o llegan después.")
    filas: list[dict[str, str]] = []
    cuenta: dict[str, int] = defaultdict(int)
    errores = 0
    reg = HotelRegistry(load_hotels())
    try:
        hoteles = [reg.hotel(args.hotel)] if args.hotel else reg.hoteles
        for hotel in hoteles:
            nombre = hotel.nombre or hotel.alias
            try:
                client = reg.client(hotel.alias)
                mapa = await _reservas_booking(client, inicio + timedelta(days=1), hoy + timedelta(days=DIAS_FUTURO))
                n_hotel = 0
                for bk, lista in sorted(mapa.items()):
                    tipo, sel = _clasificar(lista)
                    local = almacen.get(bk)
                    if tipo == "ambigua":
                        cuenta["a revisar (varias reservas activas)"] += 1
                        _p(f"  [{nombre}] {bk}: A REVISAR, {len(sel)} reservas activas en Cloudbeds "
                           f"({', '.join(str(x.get('reservationID')) for x in sel)})")
                        continue
                    if tipo == "cancelada":
                        if local:
                            cuenta["cancelada (se anota al cargar)"] += 1
                        continue
                    if tipo == "otra":
                        cuenta[f"{sel[0].get('status')} (no se toca)"] += 1
                        continue
                    cb_id = str(sel[0].get("reservationID"))
                    det = await _detalle(client, cb_id)
                    h = _huella(det)
                    if local is None:
                        motivo = "nueva"
                    elif not _misma_sede(reg, local.hotel, hotel.alias):
                        motivo = "otra sede"
                    elif not _coincide(local, h, estado):
                        motivo = "modificada"
                    else:
                        cuenta["ya leída"] += 1
                        continue
                    cuenta[motivo] += 1
                    n_hotel += 1
                    llegada, salida, nh = h.split("|")
                    filas.append({"hotel": nombre, "reserva_booking": bk, "reserva_cloudbeds": cb_id, "llegada": llegada,
                                  "salida": salida, "noches_hab": nh, "tipos_cloudbeds": _tipos(det),
                                  "estado_cloudbeds": str(sel[0].get("status")), "motivo": motivo, "huella_cloudbeds": h})
                _p(f"  [{nombre}] {len(mapa)} reservas de Booking; {n_hotel} por leer.")
            except ERRORES as exc:
                errores += 1
                _p(f"  [{nombre}] ERROR: {exc}")
    finally:
        await reg.aclose()

    salida = carpeta / f"pendientes_{hoy}.csv"
    tmp = salida.with_name(salida.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS_PENDIENTES)
        w.writeheader()
        w.writerows(filas)
    _reemplazar(tmp, salida)
    _p("Resumen: " + (", ".join(f"{k}: {v}" for k, v in sorted(cuenta.items())) or "sin reservas"))
    _p(f"Por leer en Booking: {len(filas)} -> {salida}")
    return 1 if errores else 0


def cmd_pendientes(args: argparse.Namespace) -> int:
    return asyncio.run(_pendientes(args))


# --- cargar -------------------------------------------------------------------------------------


async def _anular(client: Any, r: dg.Reserva, cb_id: str, actual: dict[str, str], confirmar: bool,
                  hoy: date) -> tuple[str, str]:
    if not any(actual.get(sc) for sc, _ in dg.CAMPOS_BOOKING.values()):
        return "cancelada", "No tenía el desglose cargado; sale del reporte"
    if any(n.startswith(dg.encabezado_anulacion(r.reserva_booking)) for n in await _notas(client, cb_id)):
        return "cancelada", "Ya tenía la nota de anulación; sale del reporte"
    if not confirmar:
        return "vista previa", "Cancelada: se agregaría la nota de anulación y saldría del reporte"
    await client.write("postReservationNote", {
        "reservationID": cb_id, "reservationNote": dg.nota_anulacion(r.reserva_booking, actual, hoy)})
    return "anulada", "Nota de anulación agregada; sale del reporte"


def _archivar_canceladas(carpeta: Path, ids: set[str]) -> None:
    """Pasa las filas de esas reservas de noches_AAAA-MM.csv a canceladas.csv y rehace los Excel."""
    salen: list[dict[str, str]] = []
    for p in _archivos_noches(carpeta):
        filas = _filas_csv(p)
        quedan = [f for f in filas if _id(f) not in ids]
        if len(quedan) == len(filas):
            continue
        mes = p.stem.removeprefix("noches_")
        k = _k_para(carpeta, mes, None) if quedan else None
        salen += [f for f in filas if _id(f) in ids]
        _escribir_csv(p, quedan, directo=True)
        _p("  " + _rehacer_mes(carpeta, mes, k))
    if salen:
        destino = carpeta / "canceladas.csv"
        previas = _filas_csv(destino) if destino.exists() else []
        _escribir_csv(destino, previas + salen, directo=True)
        _p(f"  {len({_id(f) for f in salen})} reservas canceladas pasaron a {destino.name}")


async def _cargar(args: argparse.Namespace) -> int:
    hoy, carpeta = _hoy(), Path(args.carpeta)
    modo_carpeta = not args.excel
    fuente: dict[str, str] = {}
    estado: dict[str, Any] = {}
    if modo_carpeta:
        inicio = _noche_inicio(carpeta, args.desde)
        estado = _estado(carpeta)
        reservas = [r for r in _almacen(carpeta).values() if r.hasta >= inicio]
        for r in reservas:
            fuente[r.reserva_booking] = f"reporte_booking_{r.desde:%Y-%m}.xlsx"
        _p(f"Reservas leídas en Booking con noches desde el {inicio:%d-%m-%Y}: {len(reservas)}")
    else:
        reservas = []
        for e in args.excel:
            rs, _ = dg.leer_excel(Path(e))
            reservas += rs
            fuente.update({r.reserva_booking: Path(e).name for r in rs})
    if args.hotel:
        reservas = [r for r in reservas if dg._norm(args.hotel) in dg._norm(r.hotel)]
    if args.reserva:
        pedidas = set(args.reserva)
        reservas = [r for r in reservas if r.reserva_booking in pedidas]
    if args.limite:
        reservas = reservas[: args.limite]
    parcial = bool(args.hotel or args.reserva or args.limite or args.desde)

    registro: list[dict[str, str]] = []
    canceladas: set[str] = set()
    log: Path | None = None
    reg = HotelRegistry(load_hotels())
    try:
        por_hotel: dict[str, list[dg.Reserva]] = defaultdict(list)
        for r in reservas:
            por_hotel[r.hotel].append(r)
        for nombre, lista in por_hotel.items():
            try:
                hotel = reg.hotel(nombre)
                client = reg.client(hotel.alias)
                co_desde = min(r.desde for r in lista) - timedelta(days=args.dias_atras)
                co_hasta = max(max(r.hasta for r in lista) + timedelta(days=1), hoy) + timedelta(days=DIAS_FUTURO)
                mapa = await _reservas_booking(client, co_desde, co_hasta)
            except ERRORES as exc:
                for r in lista:
                    registro.append(_fila(r, "", "error", f"Hotel: {exc}"))
                _p(f"[{nombre}] ERROR: {exc}")
                continue
            _p(f"\n[{hotel.nombre}] {len(lista)} reservas")
            campos_ok = False
            for r in lista:
                bk = r.reserva_booking
                tipo, sel = _clasificar(mapa.get(bk, []))
                if not mapa.get(bk):
                    registro.append(_fila(r, "", "no encontrada", "No hay reserva de Booking.com en Cloudbeds con ese N°; se reintenta mañana"))
                    _p(f"  {bk}: NO ENCONTRADA en Cloudbeds (se reintenta mañana)")
                    continue
                if tipo == "ambigua":
                    ids = ", ".join(str(x.get("reservationID")) for x in sel)
                    registro.append(_fila(r, ids, "a revisar", "Varias reservas activas en Cloudbeds con ese N° de Booking"))
                    _p(f"  {bk}: A REVISAR, varias reservas activas en Cloudbeds ({ids})")
                    continue
                cb_id = str(sel[0].get("reservationID"))
                if tipo == "otra":
                    registro.append(_fila(r, cb_id, "omitida", f"Estado en Cloudbeds: {sel[0].get('status')}"))
                    _p(f"  {bk} -> {cb_id}: omitida ({sel[0].get('status')})")
                    continue
                try:
                    det = await _detalle(client, cb_id)
                    actual = _campos(det)
                    if tipo == "cancelada":
                        accion, detalle = await _anular(client, r, cb_id, actual, args.confirmar, hoy)
                        registro.append(_fila(r, cb_id, accion, detalle))
                        _p(f"  {bk} -> {cb_id}: CANCELADA. {detalle}")
                        if args.confirmar and modo_carpeta:
                            canceladas.add(bk)
                        continue
                    h = _huella(det)
                    if not _coincide(r, h, estado):
                        registro.append(_fila(r, cb_id, "a releer",
                                              f"Cloudbeds {h} y archivo {_huella_local(r)} (llegada|salida|noches-hab.)"))
                        _p(f"  {bk} -> {cb_id}: A RELEER en Booking (cambió en Cloudbeds: {h})")
                        continue
                    valores = dg.valores_campos(r)
                    cambios = {k: v for k, v in valores.items() if actual.get(dg.CAMPOS_BOOKING[k][0]) != v}
                    falta_nota = False
                    if not args.sin_nota:
                        falta_nota = bool(cambios) or not any(
                            n.startswith(dg.encabezado_nota(bk)) for n in await _notas(client, cb_id))
                    if not cambios and not falta_nota:
                        registro.append(_fila(r, cb_id, "sin cambios", ""))
                        _p(f"  {bk} -> {cb_id}: sin cambios")
                        continue
                    que = " y ".join(x for x in (f"{len(cambios)} campos" if cambios else "", "la nota" if falta_nota else "") if x)
                    if not args.confirmar:
                        registro.append(_fila(r, cb_id, "vista previa",
                                              "; ".join(f"{k}={v}" for k, v in cambios.items()) or "solo falta la nota"))
                        _p(f"  {bk} -> {cb_id}: se escribirían {que}")
                        continue
                    if cambios:
                        if not campos_ok:
                            await _asegurar_campos(client)
                            campos_ok = True
                        await client.write("putReservation", {
                            "reservationID": cb_id,
                            "customFields": [
                                {"customFieldName": dg.CAMPOS_BOOKING[k][0], "customFieldValue": v} for k, v in valores.items()
                            ],
                        })
                        despues = _campos(await _detalle(client, cb_id))
                        malos = [k for k, v in valores.items() if despues.get(dg.CAMPOS_BOOKING[k][0]) != v]
                        if malos:
                            registro.append(_fila(r, cb_id, "error", f"Verificación: no quedaron {', '.join(malos)}"))
                            _p(f"  {bk} -> {cb_id}: ERROR al verificar ({', '.join(malos)})")
                            continue
                    if falta_nota:
                        await client.write("postReservationNote", {
                            "reservationID": cb_id, "reservationNote": dg.nota(r, fuente.get(bk, ""), hoy)})
                    registro.append(_fila(r, cb_id, "cargada", que))
                    _p(f"  {bk} -> {cb_id}: cargada ({que})")
                except ERRORES as exc:
                    registro.append(_fila(r, cb_id, "error", str(exc)))
                    _p(f"  {bk} -> {cb_id}: ERROR {exc}")
                    if "scope" in str(exc).lower() or "denegó" in str(exc):
                        _p("  La key de este hotel no tiene permiso de escritura; se omite el resto del hotel.")
                        for resto in lista[lista.index(r) + 1 :]:
                            registro.append(_fila(resto, "", "error", "Sin permiso de escritura"))
                        break
    finally:
        await reg.aclose()
        log = _guardar_log(registro, args)

    if canceladas:
        _archivar_canceladas(carpeta, canceladas)
    cuenta: dict[str, int] = defaultdict(int)
    for f in registro:
        cuenta[f["accion"]] += 1
    _p("\nResumen: " + (", ".join(f"{k}: {v}" for k, v in sorted(cuenta.items())) or "sin reservas que procesar"))
    _p(f"Registro: {log}")
    if not args.confirmar:
        _p("Vista previa: no se escribió nada. Repite con --confirmar para cargar.")
    elif modo_carpeta and not parcial and not cuenta["error"]:
        estado = _estado(carpeta)
        estado["ultima_noche_ok"] = (hoy - timedelta(days=1)).isoformat()
        _guardar_estado(carpeta, estado)
        _p(f"Estado: noche {estado['ultima_noche_ok']} procesada.")
    return 1 if cuenta["error"] else 0


async def _asegurar_campos(client: Any) -> None:
    body = await client.get("getCustomFields", {"propertyID": client.settings.property_id})
    existentes = {f.get("shortcode") for f in body.get("data") or []}
    for shortcode, nombre in dg.CAMPOS_BOOKING.values():
        if shortcode not in existentes:
            await client.write("postCustomField", {
                "name": nombre, "shortcode": shortcode, "applyTo": "reservation", "required": False,
                "maxCharacters": dg.MAX_CARACTERES_CAMPO, "type": "input", "displayed": ["reservation"],
                "isPersonal": False,
            })
            _p(f"  campo creado: {nombre}")


def _fila(r: dg.Reserva, cb_id: str, accion: str, detalle: str) -> dict[str, str]:
    return {"hotel": r.hotel, "reserva_booking": r.reserva_booking, "reserva_cloudbeds": cb_id,
            "noches": str(len(r.noches)), "accion": accion, "detalle": detalle}


def _guardar_log(registro: list[dict[str, str]], args: argparse.Namespace) -> Path:
    carpeta = Path(args.logs)
    carpeta.mkdir(parents=True, exist_ok=True)
    modo = "carga" if args.confirmar else "vista_previa"
    path = carpeta / f"desglose_booking_{datetime.now(LIMA):%Y%m%d_%H%M%S}_{modo}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["hotel", "reserva_booking", "reserva_cloudbeds", "noches", "accion", "detalle"])
        w.writeheader()
        w.writerows(registro)
    return path


def cmd_cargar(args: argparse.Namespace) -> int:
    return asyncio.run(_cargar(args))


# --- main ---------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser(description="Desglose de Booking: pendientes, Excel y carga a Cloudbeds.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    carpeta = {"default": str(CARPETA), "help": "Carpeta de los CSV, Excel y estado (por defecto reportes\\booking)."}
    desde = {"type": date.fromisoformat, "metavar": "AAAA-MM-DD",
             "help": "Primera noche a revisar (por defecto ayer, o desde la última corrida buena)."}

    p = sub.add_parser("pendientes", help="Lista las reservas de Booking en Cloudbeds que hay que leer en el extranet.")
    p.add_argument("--carpeta", **carpeta)
    p.add_argument("--desde", **desde)
    p.add_argument("--hotel", help="Solo este hotel (p. ej. Balta).")
    p.set_defaults(func=cmd_pendientes)

    a = sub.add_parser("agregar", help="Fusiona una lectura de Booking en los CSV del mes y rehace los Excel.")
    a.add_argument("--lectura", required=True, help="CSV con las reservas leídas (formato de FORMATO.md).")
    a.add_argument("--carpeta", **carpeta)
    a.add_argument("--k", type=float, help="K (S/ por US$) si no hay un reporte previo del que tomarlo.")
    a.set_defaults(func=cmd_agregar)

    c = sub.add_parser("cargar", help="Escribe los 8 datos en cada reserva de Cloudbeds.")
    c.add_argument("--excel", action="append", help="Cargar este Excel (se puede repetir). Sin esto usa la carpeta.")
    c.add_argument("--carpeta", **carpeta)
    c.add_argument("--desde", **desde)
    c.add_argument("--confirmar", action="store_true", help="Sin esto solo muestra lo que haría.")
    c.add_argument("--hotel", help="Solo este hotel (parte del nombre, p. ej. Balta).")
    c.add_argument("--reserva", action="append", help="Solo este N° de Booking (se puede repetir).")
    c.add_argument("--limite", type=int, help="Procesa como máximo N reservas.")
    c.add_argument("--sin-nota", action="store_true", help="Solo campos, sin nota.")
    c.add_argument("--dias-atras", type=int, default=31, help="Margen para buscar la reserva en Cloudbeds.")
    c.add_argument("--logs", default=str(RAIZ / "logs"))
    c.set_defaults(func=cmd_cargar)

    v = sub.add_parser("validar", help="Revisa el formato del Excel sin conectarse a Cloudbeds.")
    v.add_argument("--excel", required=True)
    v.add_argument("--mostrar", nargs="*", default=[], metavar="N_BOOKING", help="Muestra los 8 datos de esas reservas.")
    v.set_defaults(func=cmd_validar)

    g = sub.add_parser("generar", help="Arma el Excel del reporte desde un CSV de noches.")
    g.add_argument("--noches", required=True, help="CSV con una fila por noche (ver FORMATO.md).")
    g.add_argument("--k", type=float, required=True, help="Tipo de cambio de referencia S/ por US$.")
    g.add_argument("--salida", required=True)
    g.add_argument("--titulo")
    g.set_defaults(func=cmd_generar)

    e = sub.add_parser("exportar", help="Saca el CSV de noches desde un Excel del reporte.")
    e.add_argument("--excel", required=True)
    e.add_argument("--salida", required=True)
    e.set_defaults(func=cmd_exportar)

    args = ap.parse_args(argv)
    configure_logging()
    try:
        return args.func(args)
    except dg.FormatoError as exc:
        _p(f"ARCHIVO INVÁLIDO: {exc}")
        return 2
    except ERRORES as exc:
        _p(f"ERROR: {exc}")
        return 2
    except OSError as exc:
        _p(f"ERROR de archivo: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
