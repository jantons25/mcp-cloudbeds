# Guía rápida: consultar Cloudbeds desde Claude

Red Zentra: **Zentra Balta, Zentra Plaza y Zentra San José**. Claude puede **leer** los datos de Cloudbeds de los tres hoteles y responderte en lenguaje natural. **No puede modificar nada**: no crea, cambia ni anula reservas, tarifas, pagos ni estados de housekeeping.

## Cómo nombrar los hoteles

| Para consultar | Puedes decir |
|---|---|
| Zentra Balta | "Balta", "el Balta", "Zentra Balta" |
| Zentra Plaza | "Plaza", "Zentra Plaza" |
| Zentra San José | "San José", "San Jose" |
| Los tres juntos | "**la red**", "toda la red", "todos los hoteles", "el grupo" |

- **No hace falta decir "Zentra"** ni escribir tildes.
- **Si no dices de qué hotel hablas, Claude te preguntará** antes de consultar. Es normal: así nunca te da cifras del hotel equivocado.
- Cada respuesta indica **de qué hotel** son los datos.

## Qué puedes consultar

| Tema | Ejemplos de lo que obtienes | ¿Para la red? |
|---|---|---|
| **El día** | Ocupación, llegadas y salidas (totales, ya realizadas y pendientes), no-show y cancelaciones | ✅ cada hotel y el total |
| **Reservas** | Búsqueda por fechas, estado o apellido, y detalle de una reserva (fechas, habitación, canal, total y saldo) | ✅ la búsqueda: "¿en qué hotel está…?" |
| **Gestión** | Reservas por canal, tipo de habitación y estado; noches; cancelaciones; ingresos de habitación, ADR, ocupación y RevPAR por periodo | ✅ cada hotel y el total |
| **Venta** | Disponibilidad y precio por tipo de habitación, tarifas y promociones vigentes | Hotel por hotel |
| **Operación** | Habitaciones limpias o sucias, libres u ocupadas, quién está en cada habitación | Hotel por hotel |

## 12 preguntas de ejemplo

1. ¿Cómo va hoy **Balta**?
2. ¿Cómo va **la red** hoy?
3. ¿Cuántas llegadas y salidas tiene **San José** mañana?
4. ¿Qué ocupación tuvo **Plaza** el 15 de octubre?
5. ¿En qué hotel está alojado el señor **Pérez**?
6. ¿Hay disponibilidad en **Balta** para 2 adultos del 7 al 9 de noviembre y cuánto cuesta?
7. ¿Qué habitaciones de **Plaza** están sucias y libres ahora?
8. ¿Qué llegadas de hoy en **San José** tienen saldo pendiente?
9. ¿Cuánto facturó **la red** en habitaciones en septiembre, y cuánto cada hotel?
10. ¿Qué canal nos trajo más reservas este mes en **toda la red**?
11. ¿Cuántas cancelaciones y no-show hubo la semana pasada en **Balta**?
12. Compara la ocupación de este mes de **los tres hoteles**.

## Consejos

- Habla con normalidad: "hoy", "mañana", "la semana pasada" o "septiembre" se interpretan en la **hora de cada hotel (Lima)**.
- **La red** muestra el total y el detalle de cada hotel. Los porcentajes de la red (ocupación, ADR, RevPAR) se calculan sobre el total, no como promedio de los hoteles.
- Si un hotel no responde, Claude te avisa que **el total de la red no lo incluye**. Ese total queda incompleto: no lo uses para reportes hasta revisarlo.
- **Llegadas y salidas:** Claude distingue el total del día, las que ya se hicieron y las que siguen pendientes.
- **Ingresos:** se muestran **sin impuestos (neto)** y **con impuestos (bruto)**. Solo incluyen habitación: sin extras ni pagos. Las cifras ya se compararon con los reportes de Cloudbeds.
- Por privacidad, el email, el teléfono y el documento de los huéspedes aparecen **ocultos** (por ejemplo `j***@g***.com`).
- Cada consulta puede abarcar **hasta 1 año**. Las de ingresos de un año tardan alrededor de 1 minuto; para periodos largos, pregunta por trimestre.
- Si una respuesta te parece rara, pídele a Claude: "muéstrame en qué datos te basaste".

## Actualizaciones

Cuando Tecnología te avise de una versión nueva:

1. Abre la carpeta del programa (por ejemplo `C:\Zentra\mcp-cloudbeds`) y haz **doble clic en `actualizar.bat`**.
2. Espera el mensaje **"Listo"** y pulsa una tecla para cerrar la ventana.
3. Cierra Claude por completo: **clic derecho en el ícono junto al reloj → Salir**. Vuelve a abrirlo.

Si aparece **"[ALTO]"** o **"[ERROR]"**, no intentes arreglarlo: envía una foto del mensaje a Tecnología. Claude seguirá funcionando con la versión anterior.

## Si algo falla

| Lo que ves | Qué hacer |
|---|---|
| Claude no menciona Cloudbeds o dice que no tiene acceso | Cierra Claude por completo: **clic derecho en el ícono junto al reloj → Salir**. Vuelve a abrirlo y empieza un chat nuevo |
| Claude te pregunta "¿de qué hotel?" | Es normal: responde Balta, Plaza, San José o "la red" |
| "No encontré el hotel…" | Usa uno de los nombres de la tabla de arriba |
| "No hay API key de…" o "el total de la red NO incluye…" | Avisa a Tecnología: ese hotel no está conectado en tu PC |
| "Falta configuración" o "la API key es inválida" | Avisa a Tecnología. **No** pegues claves ni contraseñas en el chat |
| "Cloudbeds limitó las consultas" | Espera un minuto y vuelve a preguntar |
| "Es probable que a la API key le falte el scope…" | Avisa a Tecnología: falta un permiso en Cloudbeds |
| Cualquier otro error | Copia el mensaje completo (incluye un código `X-Request-ID`) y envíalo a Tecnología |

**Soporte:** Juan Antón, Jefe de Tecnología y Sistemas.
