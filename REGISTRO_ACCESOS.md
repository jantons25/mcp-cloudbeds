# Registro de acceso: API key de Cloudbeds para el MCP de Claude

Para la matriz de accesos del Plan Maestro. Se llena **una fila por cada key** (una por PC o instalación).

**Leyenda:** ✅ verificado por API · ✏️ completar a mano (no se puede obtener por API) · ⚠️ requiere acción

## Key actual (PC de Tecnología, fase de desarrollo)

| Campo | Valor |
|---|---|
| Nombre de la key en Cloudbeds | ✏️ Ricardo-Nexian-os (ver en Cloudbeds → configuración de API / credenciales) |
| Sistema que la usa | MCP local de Claude Desktop (`cloudbeds-mcp`), **solo lectura** |
| Propiedad | ✅ Zentra Balta, propertyID **318358** (PEN, America/Lima) |
| Cuenta creadora (autorizó la conexión) | ✅ **Juan Antón**, user_id 573347 (según `userinfo`) |
| Tipo de cuenta creadora | ⚠️ **Personal.** Si esa cuenta se desactiva, la key deja de funcionar. Se recomienda recrearla con una cuenta **institucional** |
| Scopes usados y verificados | ✅ `read:hotel`, `read:dashboard`, `read:reservation`, `read:room`, `read:housekeeping`, `read:rate` |
| Scopes no usados | `read:guest` (no lo usa ninguna herramienta) |
| Scopes de escritura | ✏️ Confirmar en Cloudbeds que la key **no** tiene ningún `write:*` ni `delete:*`. El servidor nunca escribe (allowlist de GET), pero el mínimo privilegio se aplica en la key |
| Fecha de creación | ✏️ 26/10/2026 |
| Dónde está guardada | ✅ Administrador de credenciales de Windows de la PC de Tecnología (servicio `cloudbeds-mcp`, usuario `CLOUDBEDS_API_KEY`). En `.env` está vacía |
| Responsable | Juan Antón, Jefe de Tecnología y Sistemas |
| Rotación sugerida | ✏️ **6 meses después de la fecha de creación** (26/04/2026), o de inmediato si cambia la cuenta creadora, se sospecha una filtración o se retira la PC |
| Fecha de registro | 26/10/2026 |

## Key de la PC del gerente (a crear en la entrega)

| Campo | Valor |
|---|---|
| Nombre de la key en Cloudbeds | ✏️ sugerido: `mcp-claude-gerencia-<PC>` |
| Cuenta creadora | ✏️ cuenta **institucional** (no personal) |
| Scopes a otorgar (mínimos) | `read:hotel`, `read:dashboard`, `read:reservation`, `read:room`, `read:housekeeping`, `read:rate` |
| Fecha de creación | ✏️ 26/04/2026 |
| Dónde se guarda | Administrador de credenciales (Windows) o Llavero (macOS) de la PC del gerente, servicio `cloudbeds-mcp` |
| Responsable | Juan Antón, Jefe de Tecnología y Sistemas |
| Rotación sugerida | ✏️ creación + 6 meses: 26/04/2026 |

## Qué puede hacer la integración (para auditoría)

- **Endpoints permitidos (solo GET):** `userinfo`, `getHotels`, `getHotelDetails`, `getDashboard`, `getReservations`, `getReservation`, `getReservationsWithRateDetails`, `getAvailableRoomTypes`, `getRoomTypes`, `getRooms`, `getReservationAssignments`, `getHousekeepingStatus`, `getSources`, `getRatePlans`. Cualquier otro se rechaza antes de llegar a la red.
- **Datos personales:** email, teléfono y documento se enmascaran (`CLOUDBEDS_SHOW_PII=false`). Tarjetas, direcciones y fechas de nacimiento nunca se devuelven.
- **Logs:** solo endpoint, status, success, latencia y X-Request-ID, hacia stderr. Auditados en F5 sin hallazgos.
- **Rate limit:** máximo 4 req/s (Cloudbeds permite 5).

## Procedimiento de rotación o revocación

1. Crear la key nueva en Cloudbeds (cuenta institucional, scopes de la tabla).
2. En cada PC: `scripts\guardar_key.py`, que reemplaza la anterior, y luego `scripts\guardar_key.py --estado`.
3. Reiniciar Claude Desktop desde la bandeja (clic derecho → Salir) y hacer una consulta de prueba.
4. **Revocar la key anterior** en Cloudbeds y actualizar este registro con las fechas.
