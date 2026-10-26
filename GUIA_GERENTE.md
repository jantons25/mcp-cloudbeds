# Guía rápida: consultar Cloudbeds desde Claude

Zentra Hotel. Claude puede **leer** los datos de Cloudbeds y responderte en lenguaje natural. **No puede modificar nada**: no crea, cambia ni anula reservas, tarifas, pagos ni estados de housekeeping.

## Qué puedes consultar

| Tema | Ejemplos de lo que obtienes |
|---|---|
| **El día** | Ocupación, llegadas y salidas (totales, ya realizadas y pendientes), no-show y cancelaciones |
| **Reservas** | Búsqueda por fechas, estado o apellido, y detalle de una reserva (fechas, habitación, canal, total y saldo) |
| **Venta** | Disponibilidad y precio por tipo de habitación, tarifas y promociones vigentes |
| **Operación** | Habitaciones limpias o sucias, libres u ocupadas, quién está en cada habitación |
| **Gestión** | Reservas por canal, tipo de habitación y estado; noches; cancelaciones; ingresos de habitación, ADR, ocupación y RevPAR por periodo |

## 10 preguntas de ejemplo

1. ¿Cómo va el día de hoy?
2. ¿Cuántas llegadas y salidas hay mañana?
3. ¿Qué ocupación tuvimos el 15 de octubre?
4. ¿Hay disponibilidad para 2 adultos del 7 al 9 de noviembre y cuánto cuesta?
5. ¿Qué habitaciones están sucias y libres ahora?
6. ¿Qué llegadas de hoy tienen saldo pendiente?
7. ¿Cuánto facturamos en habitaciones en septiembre y cuál fue el ADR?
8. ¿Qué canal nos trajo más reservas este mes?
9. ¿Cuántas cancelaciones y no-show hubo la semana pasada?
10. ¿Qué tarifas y promociones hay para el próximo fin de semana?

## Consejos

- Habla con normalidad: "hoy", "mañana", "la semana pasada" o "septiembre" se interpretan en **hora de Lima**.
- **Llegadas y salidas:** Claude distingue el total del día, las que ya se hicieron y las que siguen pendientes.
- **Ingresos:** se muestran **sin impuestos (neto)** y **con impuestos (bruto)**. Solo incluyen habitación: sin extras ni pagos. Las cifras ya se compararon con los reportes de Cloudbeds.
- Por privacidad, el email, el teléfono y el documento de los huéspedes aparecen **ocultos** (por ejemplo `j***@g***.com`).
- Cada consulta puede abarcar **hasta 1 año**. Las de ingresos de un año tardan alrededor de 1 minuto; para periodos largos, pregunta por trimestre.
- Si una respuesta te parece rara, pídele a Claude: "muéstrame en qué datos te basaste".

## Si algo falla

| Lo que ves | Qué hacer |
|---|---|
| Claude no menciona Cloudbeds o dice que no tiene acceso | Cierra Claude por completo: **clic derecho en el ícono junto al reloj → Salir**. Vuelve a abrirlo y empieza un chat nuevo |
| "Falta configuración" o "la API key es inválida" | Avisa a Tecnología. **No** pegues claves ni contraseñas en el chat |
| "Cloudbeds limitó las consultas" | Espera un minuto y vuelve a preguntar |
| "Es probable que a la API key le falte el scope…" | Avisa a Tecnología: falta un permiso en Cloudbeds |
| Cualquier otro error | Copia el mensaje completo (incluye un código `X-Request-ID`) y envíalo a Tecnología |

**Soporte:** Juan Antón, Jefe de Tecnología y Sistemas.
