# cloudbeds-mcp

Servidor MCP local (stdio) en Python que permite a Claude Desktop **leer** datos de Cloudbeds (solo GET).

> Documento en construcción. La configuración de Claude Desktop se completa en F2 y la solución de problemas en F5.

## Requisitos

- Python 3.10 o superior
- API key de Cloudbeds con, como mínimo, los scopes `read:hotel`, `read:dashboard`, `read:reservation` y `read:room`

## Instalación

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env   # luego edita .env y completa CLOUDBEDS_API_KEY
```

### macOS (Terminal)

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env          # luego edita .env y completa CLOUDBEDS_API_KEY
```

## Verificación

```powershell
# Windows
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\smoke_test.py
```

```bash
# macOS
./.venv/bin/python -m pytest -q
./.venv/bin/python scripts/smoke_test.py
```

La prueba de humo muestra el usuario que autorizó la key, las propiedades accesibles, la moneda y la zona horaria. Si `CLOUDBEDS_PROPERTY_ID` está vacío, indica el valor a agregar en `.env`.

## Herramientas disponibles

| Herramienta | Qué hace |
|---|---|
| `estado_hotel` | Ocupación, % ocupación, in-house y llegadas/salidas **pendientes** del día (`fecha` opcional, por defecto hoy en Lima) |
| `buscar_reservas` | Lista compacta de reservas filtrando por estado, rango de check-in/check-out y apellido (`max_resultados`, por defecto 50) |
| `detalle_reserva` | Detalle de una reserva por ID (PII enmascarada por defecto; nunca muestra tarjetas, direcciones ni fechas de nacimiento) |
| `disponibilidad` | Tipos de habitación disponibles para vender entre dos fechas, con unidades y tarifa (total de la estadía y promedio por noche) |
| `tipos_habitacion` | Catálogo de tipos: unidades, capacidad y características |
| `habitaciones` | Habitaciones físicas. Con `fecha_desde` y `fecha_hasta` muestra las que no tienen reserva asignada (eso **no** equivale a disponibles para vender) |
| `asignaciones_del_dia` | Qué reserva y huésped hay en cada habitación en una fecha, y qué reservas faltan asignar |
| `estado_housekeeping` | Limpia o sucia, ocupada, bloqueada, estado de recepción, housekeeper y notas (con email y teléfono enmascarados), más un resumen con conteos |
| `fuentes_reserva` | Canales de reserva con ID, si son de terceros, comisión y quién cobra |
| `planes_tarifa` | Tarifa base y promociones por tipo de habitación para un rango de fechas |

| `resumen_dia` | Ocupación del día, llegadas y salidas (total, ya realizadas, pendientes), no-show, cancelaciones y lista corta |
| `resumen_periodo` | Reservas del periodo por estado, fuente y tipo de habitación, noches, estancia media y cancelaciones. `criterio`: `checkin` (llegadas del periodo) o `creacion` (reservas hechas en el periodo) |
| `ingresos_periodo` | Ingresos de habitación por fecha de estadía: bruto y neto, ADR, ocupación, RevPAR y desglose por fuente y por tipo |

### Definiciones de las vistas gerenciales (para cuadrar con los reportes de Cloudbeds)

| Concepto | Definición en este servidor |
|---|---|
| Periodo | Fechas **inclusivas**. Por defecto, el mes en curso. Máximo 366 días |
| Noche vendida (`ingresos_periodo`) | Cada noche de cada habitación no cancelada cuya fecha cae dentro del periodo (fecha de estadía, no de reserva) |
| Ingreso bruto | Suma de las tarifas por noche (`detailedRoomRates`), **con impuestos incluidos** |
| Ingreso neto | `subTotal` de la reserva (sin impuestos ni extras) prorrateado entre sus noches. **Incluye ajustes manuales de precio** que las tarifas por noche no reflejan |
| ADR | Ingreso ÷ noches vendidas (se informa bruto y neto) |
| Ocupación / RevPAR | Noches vendidas ÷ (habitaciones del inventario × días). No se descuentan las habitaciones bloqueadas |
| Excluidas | Canceladas y no-show: en Cloudbeds tienen `total = 0` aunque conserven tarifas |
| No incluye | Extras o productos, pagos, cobros ni impuestos por separado |
| Llegadas del día (`resumen_dia`) | Reservas con check-in ese día, excluidas canceladas y no-show (que se informan aparte) |
| Noches (`resumen_periodo`, criterio `checkin`) | Estadía completa de las reservas que llegan en el periodo, aunque salgan después |

Validación interna: las noches vendidas de una noche coinciden exactamente con las habitaciones ocupadas que reporta `getDashboard` (verificado en 4 fechas).

Rendimiento: `getReservationsWithRateDetails` tarda unos 4.5 s por página de 100 reservas. Las páginas se piden en paralelo (4 a la vez) sin pasar de 4 req/s. Tiempos aproximados: 1 semana, 8 s; 1 mes, 16 s; 1 año, 70 s. Para periodos largos conviene consultar por trimestre.

> **Tarifas:** en `disponibilidad` y `planes_tarifa`, Cloudbeds entrega el **total de la estadía** (verificado: 3 noches × 135 = 405). El servidor calcula también el promedio por noche.

> **Scopes:** si a la key le falta un scope, la herramienta responde cuál falta (`read:room`, `read:housekeeping`, `read:rate`, `read:reservation`, `read:dashboard`). Los scopes no se pueden agregar a una key existente: hay que crear una nueva.

> **Llegadas y salidas:** el dashboard de Cloudbeds (`getDashboard`) cuenta solo las llegadas y salidas que **aún no** hicieron check-in o check-out. El total del día (incluidas las ya realizadas) se obtiene con `buscar_reservas` filtrando por la fecha. Claude está instruido para mostrar las dos cifras.

## Configuración de Claude Desktop

### 1. Ubicar `claude_desktop_config.json`

| Instalación | Ruta |
|---|---|
| Windows, versiones recientes (carpeta `Claude-Data`) | `%LOCALAPPDATA%\Claude-Data\claude_<id>\claude_desktop_config.json` (en esta PC: `claude_pzs8sxrjxfjjc`) |
| Windows (instalador .exe, versiones anteriores) | `%APPDATA%\Claude\claude_desktop_config.json` |
| Windows (Microsoft Store / MSIX, versiones anteriores) | `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Roaming\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

**Recomendado:** abre el archivo desde Claude Desktop, en **Configuración → Desarrollador → Editar configuración**. Así se abre el archivo que la app realmente lee.

> **Ojo (verificado en esta PC, Claude Desktop 3.6556):** las versiones recientes trasladan sus datos a `%LOCALAPPDATA%\Claude-Data\`. En la ubicación antigua queda un marcador `.user-data-left.*` y cualquier config que pongas ahí **se ignora**. Si existe la carpeta `Claude-Data`, edita el archivo que está dentro. Ese archivo ya trae otras claves (`preferences`, `coworkUserFilesPath`). No las borres: solo agrega `mcpServers`.

### 2. Agregar el servidor

**Recomendado:** usa el script. Detecta el archivo correcto, hace backup, conserva el resto de la configuración y verifica que el servidor arranque:

```powershell
.\.venv\Scripts\python.exe scripts\configurar_claude.py            # muestra qué haría
.\.venv\Scripts\python.exe scripts\configurar_claude.py --aplicar  # lo escribe
```

Para hacerlo a mano: reemplaza `<RUTA>` por la ruta absoluta del proyecto. Si el archivo ya tiene otros servidores en `mcpServers`, agrega solo el bloque `"cloudbeds"`.

**Windows:**

```json
{
  "mcpServers": {
    "cloudbeds": {
      "command": "<RUTA>\\.venv\\Scripts\\python.exe",
      "args": ["-m", "cloudbeds_mcp.server"],
      "env": { "PYTHONPATH": "<RUTA>\\src" }
    }
  }
}
```

**macOS:**

```json
{
  "mcpServers": {
    "cloudbeds": {
      "command": "<RUTA>/.venv/bin/python",
      "args": ["-m", "cloudbeds_mcp.server"],
      "env": { "PYTHONPATH": "<RUTA>/src" }
    }
  }
}
```

**No uses `cwd`.** Verificado en Claude Desktop 3.6556: la app borra la clave `cwd` cuando reescribe su config. Lo que hace funcionar al servidor es `env.PYTHONPATH`, que apunta a `src`. El `.env` se busca siempre con ruta absoluta, así que el directorio de trabajo no importa.

### 3. Reiniciar Claude Desktop por completo

Cierra también el ícono de la bandeja del sistema (Windows) o usa Cmd+Q (macOS) y vuelve a abrir la app. En una conversación nueva deben aparecer las herramientas de `cloudbeds`.

### Prueba opcional con MCP Inspector

Requiere Node.js. Descarga el Inspector desde npm y abre una interfaz web. Ejecútalo desde la raíz del proyecto en PowerShell:

```bash
$env:PYTHONPATH="src"; npx @modelcontextprotocol/inspector .venv\Scripts\python.exe -m cloudbeds_mcp.server
```

No se usa `mcp dev src/cloudbeds_mcp/server.py` porque carga el archivo suelto y rompe los imports relativos del paquete.

## Seguridad

- **Solo lectura.** El cliente HTTP solo hace `GET` y solo a los endpoints de una lista blanca. Cualquier otro endpoint se rechaza antes de llegar a la red.
- **API key en el keyring (recomendado).** Se guarda en el Administrador de credenciales de Windows o en el Llavero de macOS. El servidor la busca primero ahí y, si no la encuentra, en `CLOUDBEDS_API_KEY` de `.env`.
  ```powershell
  .\.venv\Scripts\python.exe scripts\guardar_key.py           # pide la key sin mostrarla, la verifica y la guarda
  .\.venv\Scripts\python.exe scripts\guardar_key.py --estado  # muestra de dónde se carga (nunca la key)
  .\.venv\Scripts\python.exe scripts\guardar_key.py --borrar  # la quita del keyring
  ```
  Al guardar, el script ofrece borrar la key de `.env` para que quede solo en el keyring. Para desactivar el keyring: `CLOUDBEDS_USE_KEYRING=false`. Después de cambiar la key, reinicia Claude Desktop.
- `.env` está en `.gitignore`. Nunca lo compartas ni pegues la key en un chat.
- **PII:** por defecto se enmascaran email, teléfono y documento de los huéspedes, también dentro de las notas de housekeeping (`CLOUDBEDS_SHOW_PII=false`). Las tarjetas, direcciones y fechas de nacimiento no se devuelven nunca.
- **Logs:** van solo a stderr, una línea por evento, con endpoint, status, success, latencia y `X-Request-ID`. No incluyen parámetros, key ni datos de huéspedes. Los logs de httpx, que incluyen la URL con parámetros, están silenciados. Auditado en F5 con las 13 herramientas y datos reales: sin hallazgos.
- **Límites:** cualquier rango de fechas admite como máximo 366 días. `buscar_reservas` devuelve hasta 500 reservas. Las vistas gerenciales procesan hasta 5,000 reservas y avisan si las cifras quedan incompletas. `CLOUDBEDS_MAX_RESULTS` acepta valores de 1 a 5,000.
- **Rate limit:** máximo 4 req/s (Cloudbeds permite 5 y puede suspender la key si se excede).

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q --cov=cloudbeds_mcp --cov-report=term-missing
```

Los tests no tocan la red (usan `respx`) ni el keyring real (usan un keyring en memoria). Cobertura en F5: `client.py` 94% y total 94%.

## Solución de problemas

### El MCP no aparece en Claude Desktop
1. **Reinicia por completo:** clic derecho en el ícono de la bandeja → **Salir** (Windows) o Cmd+Q (macOS). Cerrar la ventana no basta.
2. **Revisa que editaste el archivo correcto.** Abre **Configuración → Desarrollador → Editar configuración**. En las versiones recientes de Windows es `%LOCALAPPDATA%\Claude-Data\claude_<id>\claude_desktop_config.json`, y cualquier config en `%APPDATA%\Claude` o en la carpeta `Packages\...\LocalCache` se ignora (ver "Ubicar `claude_desktop_config.json`").
3. **Valida el JSON:** comas, llaves y barras invertidas dobles (`\\`) en las rutas de Windows. Un JSON inválido hace que la app ignore todos los servidores.
4. En **Configuración → Desarrollador**, el servidor `cloudbeds` muestra su estado y el error si falló al arrancar.
5. Revisa que las herramientas estén activadas en el menú de herramientas o conectores del chat.

### Ruta de Python incorrecta
- `command` debe apuntar al Python **del entorno virtual**, no al del sistema: `<RUTA>\.venv\Scripts\python.exe` en Windows o `<RUTA>/.venv/bin/python` en macOS. Con el Python del sistema falla con `ModuleNotFoundError: No module named 'mcp'`.
- Si aparece `No module named 'cloudbeds_mcp'`, falta `env.PYTHONPATH` apuntando a `<RUTA>\src`.

### "Falta configuración" o herramientas que faltan justo después de un cambio
Claude Desktop sigue usando el proceso del servidor que lanzó al abrirse, con el código y la configuración de ese momento. Si cerraste la ventana sin salir desde la bandeja, la app sigue viva con el servidor viejo. Por ejemplo, después de pasar la key al keyring, un servidor anterior a F5 no sabe leerla. Para ver desde cuándo corre:
```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'cloudbeds_mcp.server' } | Select-Object ProcessId, CreationDate
```
Si la hora es anterior al cambio, sal desde la bandeja (clic derecho → Salir) y vuelve a abrir la app.
- Prueba el comando a mano (debe quedarse esperando sin mostrar errores; sal con Ctrl+C):
  ```powershell
  $env:PYTHONPATH="<RUTA>\src"; & "<RUTA>\.venv\Scripts\python.exe" -m cloudbeds_mcp.server
  ```
- Si moviste la carpeta del proyecto, recrea el entorno (`python -m venv .venv` y `pip install -r requirements.txt`) y actualiza las rutas del config.

### Error 401 / "La API key de Cloudbeds es inválida"
- La key está mal copiada, fue revocada o falta. Ejecuta `scripts\guardar_key.py --estado` para ver de dónde se carga, y `scripts\smoke_test.py` para probarla.
- No se reintenta automáticamente, para no arriesgar un bloqueo. Genera una key nueva en Cloudbeds y guárdala con `scripts\guardar_key.py`.

### Error 429 / "Cloudbeds limitó las consultas"
- El servidor ya espera `Retry-After` y reintenta 3 veces. Si el mensaje llega al chat, espera un minuto.
- No ejecutes varias copias del servidor ni otras integraciones con la misma key al mismo tiempo: el límite de 5 req/s es por propiedad y excederlo repetidamente puede **suspender la key**.

### Mensajes `success: false` (HTTP 200 con error)
| Mensaje | Causa | Qué hacer |
|---|---|---|
| "El usuario de Cloudbeds que creó la API key fue desactivado" | La cuenta que autorizó la key ya no está activa | Crear una key nueva con una cuenta activa e **institucional** |
| "La API key no tiene acceso a esa propiedad" | `CLOUDBEDS_PROPERTY_ID` incorrecto o key de otra propiedad | Revisar `.env` (ejecuta `smoke_test.py` para ver el ID correcto) |
| "La propiedad no está activa en Cloudbeds" | Propiedad suspendida o inactiva | Consultar con el administrador de la cuenta Cloudbeds |
| "Es probable que a la API key le falte el scope '…'" | La key se creó sin ese permiso | Crear una key nueva con el scope indicado (no se pueden agregar a una existente) |
| "Cloudbeds rechazó la consulta: …" | Otro error de Cloudbeds (se muestra el texto original) | Anotar el `X-Request-ID` del mensaje y consultar a soporte de Cloudbeds |

### Consultas lentas
`ingresos_periodo` depende de un endpoint lento de Cloudbeds (unos 4.5 s por cada 100 reservas): un mes tarda unos 16 s y un año unos 70 s. Para periodos largos conviene consultar por trimestre.

### Comportamientos de Cloudbeds verificados (no documentados)
- Toma como **verdadero** cualquier booleano distinto de `0`, incluido el texto `"false"`. Por eso el servidor envía los booleanos como `1`/`0`, y `estado_housekeeping` filtra en el propio servidor.
- `getHousekeepingStatus` informa un `total` incorrecto. Se cuentan los elementos reales.
- `getSources` devuelve `data` como lista de listas.
- `getDashboard` devuelve llegadas y salidas como texto, y cuenta solo las **pendientes**.
