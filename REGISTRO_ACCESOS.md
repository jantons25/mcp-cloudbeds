# Registro de acceso: API keys de Cloudbeds para el MCP de Claude (plantilla)

Para la matriz de accesos del Plan Maestro. Se llena **una tabla por cada key**, por PC y por hotel.

> **El repositorio es público.** Este archivo es solo la plantilla. El registro real, con nombres de keys, cuentas, IDs y fechas, se lleva en **`REGISTRO_ACCESOS.local.md`**, que está en `.gitignore` y no se sube. Para empezar uno nuevo, copia esta plantilla con ese nombre.

**Leyenda:** ✅ verificado por API · ✏️ completar a mano (no se puede obtener por API) · ⚠️ requiere acción

## Key por hotel y PC

| Campo | Valor |
|---|---|
| Hotel / alias en `hoteles.json` | ✏️ ej. Zentra Plaza / `plaza` |
| PC donde se usa | ✏️ ej. PC del gerente |
| Nombre de la key en Cloudbeds | ✏️ sugerido: `mcp-claude-<pc>-<alias>` |
| Sistema que la usa | MCP local de Claude Desktop (`cloudbeds-mcp`), **solo lectura** |
| Propiedad | ✅ nombre, propertyID, moneda y zona horaria (los muestra `scripts/agregar_hotel.py`) |
| Cuenta creadora (autorizó la conexión) | ✅ la muestra `agregar_hotel.py` / `smoke_test.py` (según `userinfo`). Debe ser una cuenta **institucional**: si una cuenta personal se desactiva, la key deja de funcionar |
| Scopes mínimos | `read:hotel`, `read:dashboard`, `read:reservation`, `read:room`, `read:housekeeping`, `read:rate` |
| Scopes de escritura | ✏️ Confirmar en Cloudbeds que la key **no** tiene ningún `write:*` ni `delete:*`. El servidor nunca escribe (allowlist de GET), pero el mínimo privilegio se aplica en la key |
| Fecha de creación | ✏️ |
| Dónde está guardada | Administrador de credenciales (Windows) o Llavero (macOS) de esa PC: servicio `cloudbeds-mcp`, usuario `CLOUDBEDS_API_KEY:<alias>`. Nunca en `.env`, `hoteles.json`, el código ni un chat |
| Responsable | ✏️ |
| Rotación sugerida | ✏️ **6 meses después de la creación**, o de inmediato si cambia la cuenta creadora, se sospecha una filtración o se retira la PC |
| Fecha de registro | ✏️ |

## Qué puede hacer la integración (para auditoría)

- **Endpoints permitidos (solo GET):** `userinfo`, `getHotels`, `getHotelDetails`, `getDashboard`, `getReservations`, `getReservation`, `getReservationsWithRateDetails`, `getAvailableRoomTypes`, `getRoomTypes`, `getRooms`, `getReservationAssignments`, `getHousekeepingStatus`, `getSources`, `getRatePlans`. Cualquier otro se rechaza antes de llegar a la red.
- **Aislamiento entre hoteles:** cada hotel consulta con su propia key y su `propertyID`. En las consultas de "la red" cada hotel sigue usando su propia key.
- **Datos personales:** email, teléfono y documento se enmascaran (`CLOUDBEDS_SHOW_PII=false`). Tarjetas, direcciones y fechas de nacimiento nunca se devuelven.
- **Logs:** solo endpoint, status, success, latencia y X-Request-ID, hacia stderr. Auditados en F5 sin hallazgos; los tests verifican que ninguna key aparezca en logs ni respuestas.
- **Rate limit:** máximo 4 req/s por key (Cloudbeds permite 5).

## Procedimiento de rotación o revocación

1. Crear la key nueva en Cloudbeds (cuenta institucional, scopes mínimos).
2. En cada PC: `scripts\agregar_hotel.py --alias <alias>` (reemplaza la anterior) y luego `scripts\agregar_hotel.py --estado`.
3. Reiniciar Claude Desktop desde la bandeja (clic derecho → Salir) y hacer una consulta de prueba de ese hotel.
4. **Revocar la key anterior** en Cloudbeds y actualizar `REGISTRO_ACCESOS.local.md` con las fechas.
