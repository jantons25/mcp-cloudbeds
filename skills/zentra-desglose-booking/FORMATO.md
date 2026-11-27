# Formato del desglose de Booking

## 0. Archivos de `reportes\booking\`

| Archivo | Quién lo escribe | Qué es |
|---|---|---|
| `pendientes_AAAA-MM-DD.csv` | `pendientes` | Reservas de Booking en Cloudbeds que hay que leer en el extranet |
| `lectura_AAAA-MM-DD.csv` | Claude | Lo leído en Booking ese día; mismo formato que el CSV de noches |
| `noches_AAAA-MM.csv` | `agregar` | Dato fuente del mes de llegada: todas las reservas leídas |
| `reporte_booking_AAAA-MM.xlsx` | `agregar` | El reporte del mes |
| `canceladas.csv` | `cargar --confirmar` | Filas de las reservas que se cancelaron después de leerlas |
| `estado.json` | `agregar` y `cargar --confirmar` | Última noche procesada y diferencias Booking/Cloudbeds aceptadas |

**Columnas de `pendientes_AAAA-MM-DD.csv`:**
- `hotel`, `reserva_booking`, `reserva_cloudbeds`;
- `llegada`, `salida`, `noches_hab` (habitaciones × noches);
- `tipos_cloudbeds`, `estado_cloudbeds`;
- `motivo`: `nueva`, `modificada` u `otra sede`;
- `huella_cloudbeds`: la usa el script; no la cambies.

Copia toda la carpeta si cambias de PC. Sin ella, el script vuelve a pedir que se lean en Booking todas las reservas en casa y futuras.


## 1. CSV de noches (`noches_AAAA-MM.csv`): el dato fuente

**Reglas del archivo**
- Codificación UTF-8. Separador coma (`,`) o punto y coma (`;`).
- Primera fila con estos encabezados exactos, en cualquier orden.
- **Una fila por habitación y noche.** Una reserva de 2 habitaciones y 3 noches lleva 6 filas.

**Columnas**

| Columna | Obligatoria | Formato | Ejemplo |
|---|---|---|---|
| `hotel` | sí | Nombre del hotel en Cloudbeds | `Zentra Balta`, `Zentra Plaza`, `Zentra San José` |
| `reserva_booking` | sí | N° de reserva de Booking, solo dígitos | `6280864979` |
| `habitacion_booking` | no | Como la muestra Booking | `Standard Doble` |
| `tipo_cloudbeds` | no | Tipo de habitación en Cloudbeds | `Doble Standard` |
| `noche` | sí | `AAAA-MM-DD` (también `DD/MM/AAAA`) | `2026-11-26` |
| `plan` | no | Plan de tarifa (no es descuento) | `No reembolsable` |
| `tarifa_base_cb` | no | S/ de la tarifa base de Cloudbeds hoy; vacío si no hay | `150` |
| `promocion` | no | Nombres separados por `;`, o `Sin promoción` | `Last Minute Deal; Mobile Rate` |
| `promo1` `promo2` `promo3` | no | % de cada promoción: `0.1`, `10` o `10%`; vacío si no hay | `0.1` |
| `genius_pct` | no | % Genius; `0` si no hay | `0.25` |
| `genius_tipo` | no | `Fijo`, `Dinámico` o `—` (debe ser `Fijo` o `Dinámico` si hay %) | `Dinámico` |
| `subtotal_usd` | sí | Precio de esa noche en Booking, US$ sin IGV, mayor que 0 | `33.53` |
| `comision_pct` | sí | % de comisión: `0.23`, `23` o `23%` | `0.23` |
| `comision_informada_usd` | no | Comisión total que informa Booking, en **la primera fila** de la reserva | `7.71` |

**Números y validación**
- Decimales con punto. Se acepta coma decimal solo en celdas sin separador de miles.
- Los porcentajes mayores que 1 se toman como «por cien»: `23` equivale a 23 %.
- El script rechaza el archivo, y dice la fila, si:
  - falta una columna obligatoria;
  - una celda numérica trae texto o una fórmula;
  - una fecha es inválida;
  - un % está fuera de rango;
  - una misma reserva aparece en dos hoteles.

## 2. Excel del reporte (`reporte_booking_AAAA-MM.xlsx`)
Lo genera `desglose_booking.py generar` y tiene cuatro hojas.

**Reporte por noche**
- Título en la fila 1 y encabezados en la fila 4. Datos desde la fila 5, más una fila TOTAL.
- Las celdas en azul son datos; las negras son fórmulas.

| Col | Encabezado | Tipo |
|---|---|---|
| A | Hotel | dato |
| B | N° reserva Booking | dato |
| C | Habitación (Booking) | dato |
| D | Tipo de habitación en Cloudbeds | dato |
| E | Noche | dato |
| F | Plan de tarifa | dato |
| G | 1. Tarifa base Cloudbeds hoy (S/) | dato |
| H | 2. Precio original Booking (US$ sin IGV) | `=R/((1-M)*(1-O))` |
| I | 3. Promoción: nombre | dato |
| J–L | Promo 1 %, Promo 2 %, Promo 3 % | dato |
| M | 3. Promoción: % combinado | `=1-(1-J)(1-K)(1-L)` |
| N | 3. Promoción: monto (US$) | `=H*M` |
| O | 4. Genius % | dato |
| P | 4. Genius: monto (US$) | `=(H-N)*O` |
| Q | 4. Genius: tipo | dato |
| R | 5. Subtotal sin IGV (US$) | dato |
| S | 6. Comisión Booking % | dato |
| T | 6. Comisión Booking: monto (US$) | `=R*S` |
| U | 7. Neto para el hotel (US$) | `=R-T` |
| V | Base implícita (S/) | `=H*K` |
| W | Dif. base implícita vs Cloudbeds hoy | `=V/G-1` |

**Resumen por reserva**
- Suma las noches de cada reserva.
- Incluye la columna «Comisión informada por Booking (US$)», que es dato.

**Resumen por hotel:** totales por hotel.

**Parámetros y notas:** la celda **B4** guarda **K**, en S/ por US$.

**Cómo lo lee el script**
- `cargar` y `validar` buscan las columnas **por su encabezado**, no por su posición.
- Solo usan las columnas de datos: las fórmulas se recalculan en Python, así que el Excel no necesita abrirse en Excel antes.
- Un Excel hecho a mano también sirve si respeta los nombres de hoja y los encabezados de las columnas de datos.

## 3. Lo que se escribe en cada reserva de Cloudbeds (8 datos)

| # | Campo personalizado (shortcode) | Ejemplo (Booking 6280864979) |
|---|---|---|
| 1 | Booking: tarifa base Cloudbeds (`bk_base_cb`) | `S/ 150.00 (tarifa hoy)` |
| 2 | Booking: precio original (`bk_original`) | `US$ 49.67 sin IGV` |
| 3 | Booking: promoción (`bk_promo`) | `Mobile Rate 10 %: -US$ 4.97` |
| 4 | Booking: Genius (`bk_genius`) | `Genius 25 % dinámico: -US$ 11.18` |
| 5 | Booking: subtotal sin IGV (`bk_subtotal`) | `US$ 33.53` |
| 6 | Booking: comisión (`bk_comision`) | `23 %: US$ 7.71` |
| 7 | Booking: neto hotel (`bk_neto`) | `US$ 25.82 (52 % del original)` |
| 8 | Nota de la reserva | El cálculo noche por noche, con el nombre del archivo y la fecha de carga |

**Cómo se escriben**
- Cada campo admite hasta 60 caracteres.
- Si la reserva tiene varias noches, los montos son la suma y el texto dice «en N noches» (o «noches-hab.» si tiene varias habitaciones).
- La comisión usa la informada por Booking si está; si no, la calculada.
- **Campos en un hotel nuevo:** si no existen, el script los crea la primera vez. Son de tipo texto, no obligatorios y solo visibles en la ficha de la reserva.
- **Nota:** se agrega cuando algún campo cambió o cuando la reserva aún no tiene la nota del desglose. Si no, no se toca la reserva.
- **Reserva cancelada que ya tenía el desglose:** se agrega una sola nota que empieza con `ANULADO · Desglose Booking <N°>`. Dice que no se consideren como ingreso los montos de los campos. Los campos no se borran. La reserva sale del Excel y pasa a `canceladas.csv`.
- **Fechas o habitaciones distintas entre Cloudbeds y lo leído:** no se escribe nada y la reserva vuelve a `pendientes` como `modificada`. Si después de releerla Booking sigue distinto (cambio hecho solo en Cloudbeds), se carga lo leído en Booking y se avisa.
