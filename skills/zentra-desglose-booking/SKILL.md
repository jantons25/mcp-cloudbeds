---
name: zentra-desglose-booking
description: Arma el reporte de desglose de precios de las reservas de Booking de Zentra (Balta, Plaza y San José): precio original, promoción, Genius, subtotal, comisión y neto por noche, leído del extranet de Booking y de Cloudbeds. Lo guarda en Excel y carga esos 8 datos (7 campos personalizados y una nota) en cada reserva de Cloudbeds con scripts/desglose_booking.py. Úsala en la tarea programada de la 1:00 a. m. o cuando pidan «desglose de Booking», «cargar comisiones de Booking a Cloudbeds» o «reporte de Booking del día».
---

# Zentra · desglose de Booking a Cloudbeds (v2.0)

Trabaja en español. Esta skill **lee** Booking y Cloudbeds, y **carga** el desglose en Cloudbeds solo con el script. Nunca cambia precios, estados, fechas, pagos ni ajustes, y nunca escribe en Cloudbeds por otro medio.

**Objetivo:** que toda reserva de Booking registrada en Cloudbeds, en casa o futura, tenga los 8 datos.

**Configura una vez en cada PC:**
- `PROYECTO` = `D:\Juanjo\PROYECTOS\mcp-cloudbeds`. Es la carpeta que contiene `scripts\desglose_booking.py`; cámbiala aquí si en esta PC está en otro lado.
- `PY` = `PROYECTO\.venv\Scripts\python.exe`
- `SALIDA` = `PROYECTO\reportes\booking\`.

Corre todos los comandos desde `PROYECTO`. El formato de los archivos está en `FORMATO.md`, junto a este archivo.

## 1. Qué reservas leer: lo decide el script
```
<PY> scripts\desglose_booking.py pendientes
```
- Revisa en Cloudbeds las reservas de Booking.com que pernoctan desde anoche (hora de Lima) o llegan después, en las tres sedes.
- Escribe `SALIDA\pendientes_AAAA-MM-DD.csv` con las que hay que leer en Booking:
  - **nueva:** todavía no se ha leído;
  - **modificada:** cambiaron sus fechas o habitaciones;
  - **otra sede:** antes se leyó en otro hotel.
- Si un día no se corrió, el script incluye solo las noches que faltan. No calcules fechas tú.
- Para una fecha manual: `pendientes --desde AAAA-MM-DD`.
- Si el archivo no tiene filas, salta al paso 4.

## 2. Leer Booking (extranet)
Usa el navegador que tenga la sesión de Booking abierta: Claude in Chrome o el navegador del Code tab.

- **Si aparece login o verificación de identidad, detente.** No escribas contraseñas ni códigos. Termina con «Booking pidió iniciar sesión; no se cargó nada» y no corras `cargar`. Al día siguiente el script recupera lo pendiente.
- **Propiedades en Booking:**
  - 5042812 = **Zentra Hotel** (Balta).
  - 16258576 y 16209904 = Plaza y San José. Confirma cuál es cuál por el nombre que muestra el extranet.
- **Detalle de cada reserva del archivo de pendientes:** `https://admin.booking.com/hotel/hoteladmin/extranet_ng/manage/booking.html?res_id=<reserva_booking>&hotel_id=<ID>&lang=xu&ses=<ses>`
  - Toma `ses` de la URL actual del extranet. Nunca lo escribas en archivos ni en el reporte.
  - Abre las reservas **una por una y espera ~9 s entre páginas**. Abrir muchas a la vez cierra la sesión de Booking.
- **Qué leer del detalle,** por cada habitación y cada noche:
  - Nombre de la habitación.
  - Nombre completo de la tarifa: plan, promociones y Genius.
  - Precio de la noche en US$ (es el subtotal sin IGV).
  - Comisión de la reserva en US$.
- **Cómo pasar la tarifa a columnas:**
  - El plan (`No reembolsable`, `Flexible Total`, etc.) no es un descuento.
  - Promociones y su % vigente (nov-2026):

    | Promoción | % |
    |---|---|
    | Mobile Rate | 10 % |
    | Late Escape Deal | 15 % |
    | Last Minute Deal | 10 % |
    | Country Rate | 12 % |
    | Black Friday Deal | 40 % |

  - Si una reserva trae varias promociones, cada una va en su columna `promo1`, `promo2` y `promo3`.
  - **Si aparece una promoción que no está en la tabla,** busca su % en el extranet, en *Promociones*. Si no lo encuentras, **no agregues esa reserva**: anótala en «a revisar». Volverá a salir mañana.
  - «Genius discount x%» va como Genius `Fijo` x %. «Genius Dynamic Pricing discount x%» va como `Dinámico` x %. Sin Genius va `—` y 0.
- **Comisión %:** comisión de la reserva ÷ suma de los subtotales de sus noches. Hoy da 15 % o 23 %. Si da otro valor, revisa la lectura antes de seguir. La comisión en US$ va en `comision_informada_usd`, en la primera fila de la reserva.
- **Lee todas las noches de la reserva**, también las que ya pasaron o son de otro mes.

## 3. Escribir la lectura y agregarla
- **Tipo de Cloudbeds:** usa la columna `tipos_cloudbeds` del archivo de pendientes. Si hay varios, empareja cada habitación de Booking con el tipo equivalente.
- **Tarifa base de hoy:** usa el MCP `cloudbeds`, con `planes_tarifa` o `disponibilidad`, por hotel, noche y tipo de habitación. Es la tarifa base, no la de un plan. Si Cloudbeds no ofrece ese tipo esa noche, deja la celda vacía.
- **Hotel:** el valor de la columna `hotel` del archivo de pendientes.
- Escribe `SALIDA\lectura_AAAA-MM-DD.csv` (fecha de hoy) con el formato del CSV de noches de `FORMATO.md`:
  - una fila por habitación y noche;
  - solo las reservas que leíste completas;
  - con la herramienta de escribir archivos (UTF-8). Si un texto lleva coma, ponlo entre comillas dobles. `agregar` valida todo antes de guardar.
- Agrégala:
```
<PY> scripts\desglose_booking.py agregar --lectura <SALIDA>\lectura_AAAA-MM-DD.csv
```
  - Reemplaza las reservas que ya estaban, las pone en `noches_AAAA-MM.csv` del mes de llegada y rehace `reporte_booking_AAAA-MM.xlsx`.
  - **K** se toma del reporte del mes o del anterior. Solo si dice «No hay K», agrega `--k <valor>`.
  - **Código 2 = archivo inválido.** Corrige la lectura según el mensaje y repite. No sigas sin agregar.

## 4. Cargar a Cloudbeds
```
<PY> scripts\desglose_booking.py cargar
<PY> scripts\desglose_booking.py cargar --confirmar
```
- **`cargar` sin `--confirmar`** es la vista previa y no escribe. Si termina con **código 1 (error)**, no confirmes: informa el error.
- **Con código 0, confirma** aunque haya:
  - **«no encontrada»:** aún no llegó a Cloudbeds; se reintenta mañana;
  - **«a releer»:** cambió en Cloudbeds; mañana sale en pendientes;
  - **«a revisar»:** varias reservas activas en Cloudbeds con el mismo N° de Booking; infórmalo;
  - **«omitida»:** no-show; no se toca.
- `--confirmar`:
  - solo escribe lo que cambió;
  - a una reserva **cancelada** que tenía el desglose le agrega una nota de anulación (sus montos no son ingreso) y la pasa a `canceladas.csv`;
  - si no hubo errores, guarda la noche procesada en `estado.json`.
- Cada corrida deja un registro en `PROYECTO\logs\desglose_booking_*.csv`.

## 5. Informe final (corto)
- Noches revisadas y reservas por leer por hotel. Totales de lo cargado: cargadas, sin cambios, canceladas o anuladas, no encontradas, a releer, a revisar y errores.
- Reservas «a revisar» y por qué.
- Ruta del Excel y del registro.
- Si algo falló, qué paso y el mensaje exacto. Nunca inventes resultados.
