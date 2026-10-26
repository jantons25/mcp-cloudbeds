# cloudbeds-mcp

Servidor MCP local (stdio) en Python que permite a Claude Desktop **leer** datos de Cloudbeds (solo GET) de uno o varios hoteles. Hoy atiende la red Zentra: **Zentra Balta, Zentra Plaza y Zentra San José**.

## Requisitos

- Python 3.10 o superior
- Git, para instalar y actualizar con `git clone` / `git pull`
- Una API key de Cloudbeds por hotel, con los scopes `read:hotel`, `read:dashboard`, `read:reservation`, `read:room`, `read:housekeeping` y `read:rate`. Una misma key que vea varias propiedades también sirve.

## Instalación

### Windows (PowerShell)

```powershell
git clone https://github.com/jantons25/mcp-cloudbeds.git C:\Zentra\mcp-cloudbeds
cd C:\Zentra\mcp-cloudbeds
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe scripts\agregar_hotel.py --alias balta     # repetir con plaza y san_jose
```

### macOS (Terminal)

```bash
git clone https://github.com/jantons25/mcp-cloudbeds.git ~/mcp-cloudbeds
cd ~/mcp-cloudbeds
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
./.venv/bin/python scripts/agregar_hotel.py --alias balta            # repetir con plaza y san_jose
```

La instalación paso a paso para la PC del gerente está en [CHECKLIST_INSTALACION.md](CHECKLIST_INSTALACION.md).

## Varios hoteles

### Cómo se configura

| Qué | Dónde | ¿Secreto? | ¿En git? |
|---|---|---|---|
| Lista de hoteles: alias, nombre, propertyID, zona horaria y moneda | `hoteles.json`, en la raíz del proyecto | No | No: cada PC tiene el suyo |
| API key de cada hotel | Keyring del sistema, usuario `CLOUDBEDS_API_KEY:<alias>` | **Sí** | Nunca |
| Opciones comunes: PII, tope de resultados y zona horaria por defecto | `.env` | Puede tenerlo | No |

`scripts/agregar_hotel.py` arma `hoteles.json` y guarda la key en el keyring:

1. Pide la key sin mostrarla.
2. La verifica con `userinfo` y `getHotels`.
3. Toma de Cloudbeds el nombre, propertyID, zona horaria y moneda, así que no se tipean.
4. Escribe el archivo solo si queda válido.

```powershell
.\.venv\Scripts\python.exe scripts\agregar_hotel.py                 # agrega o actualiza un hotel (propone el alias)
.\.venv\Scripts\python.exe scripts\agregar_hotel.py --alias plaza   # con el alias decidido
.\.venv\Scripts\python.exe scripts\agregar_hotel.py --estado        # hoteles y de dónde sale cada key (nunca la muestra)
.\.venv\Scripts\python.exe scripts\agregar_hotel.py --borrar plaza  # quita la key y, si confirmas, el hotel
```

Ejemplo de `hoteles.json` (hay una plantilla en [hoteles.example.json](hoteles.example.json)):

```json
{
  "hoteles": [
    {"alias": "balta", "nombre": "Zentra Balta", "property_id": "...", "tz": "America/Lima", "moneda": "PEN"},
    {"alias": "plaza", "nombre": "Zentra Plaza", "property_id": "...", "tz": "America/Lima", "moneda": "PEN"},
    {"alias": "san_jose", "nombre": "Zentra San José", "property_id": "...", "tz": "America/Lima", "moneda": "PEN",
     "otros_nombres": ["San José de Lima"]}
  ]
}
```

| Campo | Regla |
|---|---|
| `alias` | Obligatorio. Minúsculas, números y `_`, máximo 32, único |
| `nombre` | Obligatorio. No puede coincidir con otro hotel ni con una palabra de la red |
| `property_id` | Obligatorio y único |
| `tz` | Opcional; si falta, se usa `CLOUDBEDS_TZ` |
| `moneda` | Opcional; código ISO de 3 letras |
| `otros_nombres` | Opcional; otras formas en que el gerente llama al hotel |
| `predeterminado` | Opcional, a nivel raíz: hotel que se usa si no se indica ninguno. **No se recomienda**: sin él, Claude pregunta |
| `nombres_red` | Opcional, a nivel raíz: palabras extra para referirse a todos los hoteles |
| Campos que empiezan por `_` | Son comentarios y se ignoran |
| Cualquier campo con "key", "token" o "password" | Se rechaza con un error |

**Orden en que se busca la key de cada hotel:**

1. Keyring `CLOUDBEDS_API_KEY:<alias>`.
2. Variable de entorno `CLOUDBEDS_API_KEY_<ALIAS>`, por ejemplo `CLOUDBEDS_API_KEY_SAN_JOSE`.
3. La key de la instalación de un solo hotel (`guardar_key.py` o `CLOUDBEDS_API_KEY`). Solo vale para el hotel cuyo `property_id` coincide con `CLOUDBEDS_PROPERTY_ID`, o si hay un solo hotel.

Un hotel sin key **no detiene el servidor**: queda marcado como no disponible y los demás funcionan. Si ningún hotel tiene key, es un error de configuración.

**Sin `hoteles.json`** el servidor funciona en modo de un solo hotel, exactamente como antes: key en `guardar_key.py` o `.env`, y `CLOUDBEDS_PROPERTY_ID`.

### Cómo se elige el hotel en el chat

Todas las herramientas tienen un parámetro opcional `hotel`. Su descripción le lista a Claude los hoteles configurados y le indica que **pregunte** si el usuario no dice de cuál habla.

- **Se acepta** el alias, el nombre completo o el nombre corto: "Balta", "zentra plaza", "San José", "san jose" o "sanjose".
- **Se ignoran** mayúsculas, tildes, la palabra "hotel", artículos y la marca. La marca es la palabra común a todos los nombres, "Zentra", y se detecta sola, sin estar fija en el código.
- **Si no se dice el hotel y hay varios**, la herramienta responde "Indica de qué hotel quieres la información…" con la lista, sin consultar Cloudbeds.
- **La red:** `hotel="red"`, y también "la red", "toda la red", "todos", "todos los hoteles", "grupo", "los tres" o "consolidado".
- **Cada respuesta empieza por** `"hotel": {"alias", "nombre"}`, para que nunca se mezclen cifras de hoteles distintos.

## Herramientas disponibles

La columna **Red** indica si la herramienta acepta `hotel="red"` y devuelve el total de los hoteles. Las demás son de un solo hotel, porque un ID de reserva o un número de habitación solo tiene sentido dentro de un hotel.

| Herramienta | Red | Qué hace |
|---|---|---|
| `hoteles` | — | Lista los hoteles configurados y si tienen key en esta PC. Con `verificar=true` comprueba cada key en Cloudbeds |
| `estado_hotel` | ✅ | Ocupación, % ocupación, in-house y llegadas/salidas **pendientes** del día (`fecha` opcional; por defecto, hoy en la zona horaria del hotel) |
| `buscar_reservas` | ✅ | Lista compacta de reservas filtrando por estado, rango de check-in/check-out y apellido (`max_resultados`, por defecto 50, por hotel). En la red sirve para "¿en qué hotel está el Sr. Pérez?" |
| `detalle_reserva` | | Detalle de una reserva por ID (PII enmascarada por defecto; nunca muestra tarjetas, direcciones ni fechas de nacimiento) |
| `disponibilidad` | | Tipos de habitación disponibles para vender entre dos fechas, con unidades y tarifa (total de la estadía y promedio por noche) |
| `tipos_habitacion` | | Catálogo de tipos: unidades, capacidad y características |
| `habitaciones` | | Habitaciones físicas. Con `fecha_desde` y `fecha_hasta` muestra las que no tienen reserva asignada (eso **no** equivale a disponibles para vender) |
| `asignaciones_del_dia` | | Qué reserva y huésped hay en cada habitación en una fecha, y qué reservas faltan asignar |
| `estado_housekeeping` | | Limpia o sucia, ocupada, bloqueada, estado de recepción, housekeeper y notas (con email y teléfono enmascarados), más un resumen con conteos |
| `fuentes_reserva` | | Canales de reserva con ID, si son de terceros, comisión y quién cobra |
| `planes_tarifa` | | Tarifa base y promociones por tipo de habitación para un rango de fechas |
| `resumen_dia` | ✅ | Ocupación del día, llegadas y salidas (total, ya realizadas, pendientes), no-show, cancelaciones y lista corta |
| `resumen_periodo` | ✅ | Reservas del periodo por estado, fuente y tipo de habitación, noches, estancia media y cancelaciones. `criterio`: `checkin` (llegadas del periodo) o `creacion` (reservas hechas en el periodo) |
| `ingresos_periodo` | ✅ | Ingresos de habitación por fecha de estadía: bruto y neto, ADR, ocupación, RevPAR y desglose por fuente y por tipo |

### Respuestas de la red

```json
{
  "red": {"hoteles_incluidos": ["Zentra Balta", "Zentra Plaza"], "hoteles_no_incluidos": ["Zentra San José (sin API key en esta PC)"]},
  "total_red": { "...": "suma de la red" },
  "hoteles": {"balta": {"nombre": "Zentra Balta", "...": "resultado normal"}, "plaza": {"...": "..."}},
  "advertencia": "El total de la red NO incluye: Zentra San José (sin API key en esta PC). Menciónalo al responder."
}
```

- **Consulta:** los hoteles se consultan **en paralelo**. Cada key tiene su propio límite de 4 req/s, y los hoteles que comparten key también comparten ese límite.
- **Hotel con error:** si un hotel falla, su entrada muestra el error y los demás responden igual. El total de la red solo incluye a los que respondieron y lo advierte.
- **Qué se suma:** se suman los conteos. Ocupación, ADR, RevPAR, estancia media y porcentaje de cancelaciones se **recalculan desde los totales**, no como promedio de porcentajes.
- **Moneda:** los importes solo se suman si todos los hoteles tienen la misma moneda. Si no, `total_red` trae `moneda: null` y `advertencia_moneda`, y solo suma noches y ocupación.
- **Inventario:** para la ocupación de la red se usan las habitaciones del inventario de cada hotel (`getRoomTypes`), que se consultan **una vez al día** por hotel. Si no se conoce el inventario de todos, el % de la red queda vacío.
- **Zonas horarias:** si los hoteles están en zonas horarias distintas, "hoy" es el de cada hotel y el total lo indica con `fechas_por_hotel`.

### Definiciones de las vistas gerenciales (para cuadrar con los reportes de Cloudbeds)

| Concepto | Definición en este servidor |
|---|---|
| Periodo | Fechas **inclusivas**. Por defecto, el mes en curso en la zona horaria del hotel. Máximo 366 días |
| Noche vendida (`ingresos_periodo`) | Cada noche de cada habitación no cancelada cuya fecha cae dentro del periodo (fecha de estadía, no de reserva) |
| Ingreso bruto | Suma de las tarifas por noche (`detailedRoomRates`), **con impuestos incluidos** |
| Ingreso neto | `subTotal` de la reserva (sin impuestos ni extras) prorrateado entre sus noches. **Incluye ajustes manuales de precio** que las tarifas por noche no reflejan |
| ADR | Ingreso ÷ noches vendidas (se informa bruto y neto) |
| Ocupación / RevPAR | Noches vendidas ÷ (habitaciones del inventario × días). No se descuentan las habitaciones bloqueadas |
| Excluidas | Canceladas y no-show: en Cloudbeds tienen `total = 0` aunque conserven tarifas |
| No incluye | Extras o productos, pagos, cobros ni impuestos por separado |
| Llegadas del día (`resumen_dia`) | Reservas con check-in ese día, excluidas canceladas y no-show (que se informan aparte) |
| Noches (`resumen_periodo`, criterio `checkin`) | Estadía completa de las reservas que llegan en el periodo, aunque salgan después |
| Ocupación de la red | Suma de habitaciones ocupadas ÷ suma de habitaciones del inventario de los hoteles incluidos |

Validación interna: las noches vendidas de una noche coinciden exactamente con las habitaciones ocupadas que reporta `getDashboard` (verificado en 4 fechas).

Rendimiento: `getReservationsWithRateDetails` tarda unos 4.5 s por página de 100 reservas. Las páginas se piden en paralelo (4 a la vez) sin pasar de 4 req/s. Tiempos aproximados: 1 semana, 8 s; 1 mes, 16 s; 1 año, 70 s. En la red, los hoteles corren en paralelo y el tiempo total se acerca al del hotel más lento. Para periodos largos conviene consultar por trimestre.

> **Tarifas:** en `disponibilidad` y `planes_tarifa`, Cloudbeds entrega el **total de la estadía** (verificado: 3 noches × 135 = 405). El servidor calcula también el promedio por noche.

> **Scopes:** si a la key le falta un scope, la herramienta responde cuál falta (`read:room`, `read:housekeeping`, `read:rate`, `read:reservation`, `read:dashboard`). Los scopes no se pueden agregar a una key existente: hay que crear una nueva.

> **Llegadas y salidas:** el dashboard de Cloudbeds (`getDashboard`) cuenta solo las llegadas y salidas que **aún no** hicieron check-in o check-out. El total del día (incluidas las ya realizadas) se obtiene con `buscar_reservas` filtrando por la fecha. Claude está instruido para mostrar las dos cifras.

## Verificación

```powershell
# Windows
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\agregar_hotel.py --estado
.\.venv\Scripts\python.exe scripts\smoke_test.py
```

```bash
# macOS
./.venv/bin/python -m pytest -q
./.venv/bin/python scripts/agregar_hotel.py --estado
./.venv/bin/python scripts/smoke_test.py
```

Con `hoteles.json`, la prueba de humo revisa **cada hotel**: key, acceso a su propiedad, nombre y moneda en Cloudbeds. Marca los que fallan sin detenerse. Sin `hoteles.json` prueba el único hotel de `.env` y, si `CLOUDBEDS_PROPERTY_ID` está vacío, indica el valor a agregar.

## Actualizaciones (git pull)

En la PC del gerente: doble clic en **`actualizar.bat`**, o `.\.venv\Scripts\python.exe scripts\actualizar.py [--probar]`. Después hay que **salir de Claude desde la bandeja** y volver a abrirlo.

`scripts/actualizar.py`:
- **Se detiene sin tocar nada** si hay archivos del proyecto modificados en esa PC, o si la carpeta no es la raíz de un clon de git (por ejemplo, una copia hecha con `robocopy`).
- **Descarga solo en línea recta** (`git pull --ff-only`). Nunca mezcla historias.
- **Reinstala las dependencias** si cambió `requirements.txt`.
- **Comprueba que el servidor nuevo se importe** antes de pedir el reinicio.
- **No toca** `.env`, `hoteles.json` ni el keyring, que no están en git.

Para publicar una mejora: haz commit y push a `main` desde la PC de Tecnología y avisa al gerente que ejecute `actualizar.bat`. Un **hotel nuevo no requiere actualizar el código**: basta con `agregar_hotel.py` en cada PC.

> **Repositorio público:** cualquiera puede leer lo que se sube. No subas `.env`, `hoteles.json`, keys ni datos internos (por eso el registro de accesos real va en `REGISTRO_ACCESOS.local.md`, que no está en git). Si el repositorio se hace privado, la PC del gerente necesita un token de GitHub **de solo lectura** para `git pull` (ver el checklist, sección B).

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

Se registra **una sola** entrada `cloudbeds`, que atiende a todos los hoteles. Para hacerlo a mano: reemplaza `<RUTA>` por la ruta absoluta del proyecto. Si el archivo ya tiene otros servidores en `mcpServers`, agrega solo el bloque `"cloudbeds"`.

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

**No uses `cwd`.** Verificado en Claude Desktop 3.6556: la app borra la clave `cwd` cuando reescribe su config. Lo que hace funcionar al servidor es `env.PYTHONPATH`, que apunta a `src`. El `.env` y `hoteles.json` se buscan siempre con ruta absoluta, así que el directorio de trabajo no importa.

### 3. Reiniciar Claude Desktop por completo

Cierra también el ícono de la bandeja del sistema (Windows) o usa Cmd+Q (macOS) y vuelve a abrir la app. En una conversación nueva deben aparecer las 14 herramientas de `cloudbeds`.

La lista de hoteles se lee **al arrancar** el servidor. Después de agregar o quitar un hotel, reinicia Claude Desktop desde la bandeja.

### Prueba opcional con MCP Inspector

Requiere Node.js. Descarga el Inspector desde npm y abre una interfaz web. Ejecútalo desde la raíz del proyecto en PowerShell:

```bash
$env:PYTHONPATH="src"; npx @modelcontextprotocol/inspector .venv\Scripts\python.exe -m cloudbeds_mcp.server
```

No se usa `mcp dev src/cloudbeds_mcp/server.py` porque carga el archivo suelto y rompe los imports relativos del paquete.

## Seguridad

- **Solo lectura.** El cliente HTTP solo hace `GET` y solo a los endpoints de una lista blanca. Cualquier otro endpoint se rechaza antes de llegar a la red.
- **API keys en el keyring.** Se guardan en el Administrador de credenciales de Windows o en el Llavero de macOS, una por hotel (`agregar_hotel.py`). En el modo de un solo hotel se usa `guardar_key.py`:
  ```powershell
  .\.venv\Scripts\python.exe scripts\guardar_key.py           # pide la key sin mostrarla, la verifica y la guarda
  .\.venv\Scripts\python.exe scripts\guardar_key.py --estado  # muestra de dónde se carga (nunca la key)
  .\.venv\Scripts\python.exe scripts\guardar_key.py --borrar  # la quita del keyring
  ```
  Al guardar, el script ofrece borrar la key de `.env` para que quede solo en el keyring. Para desactivar el keyring: `CLOUDBEDS_USE_KEYRING=false`. Después de cambiar una key, reinicia Claude Desktop.
- **Aislamiento entre hoteles.** Cada hotel consulta con su propia key y su propio `propertyID`. Los tests verifican que ninguna key aparezca en logs ni en respuestas, y que en la red cada hotel use la suya.
- **Fuera del repositorio:** `.env`, `hoteles.json` y `REGISTRO_ACCESOS.local.md` están en `.gitignore`. Nunca los compartas ni pegues una key en un chat.
- **PII:** por defecto se enmascaran email, teléfono y documento de los huéspedes, también dentro de las notas de housekeeping (`CLOUDBEDS_SHOW_PII=false`). Las tarjetas, direcciones y fechas de nacimiento no se devuelven nunca.
- **Logs:** van solo a stderr, una línea por evento, con endpoint, status, success, latencia y `X-Request-ID`. No incluyen parámetros, key ni datos de huéspedes. Los logs de httpx, que incluyen la URL con parámetros, están silenciados. Auditado en F5 con las 13 herramientas y datos reales: sin hallazgos.
- **Límites:** cualquier rango de fechas admite como máximo 366 días. `buscar_reservas` devuelve hasta 500 reservas por hotel. Las vistas gerenciales procesan hasta 5,000 reservas por hotel y avisan si las cifras quedan incompletas. `CLOUDBEDS_MAX_RESULTS` acepta valores de 1 a 5,000.
- **Rate limit:** máximo 4 req/s por key (Cloudbeds permite 5 y puede suspender la key si se excede). Los hoteles que comparten key comparten el límite.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q --cov=cloudbeds_mcp --cov-report=term-missing
```

Los tests no tocan la red (usan `respx`) ni el keyring real (usan un keyring en memoria). Los de `actualizar.py` usan repositorios git reales en una carpeta temporal. Estado al cierre del soporte multi-hotel: 352 tests y cobertura total del 98 %.

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
Claude Desktop sigue usando el proceso del servidor que lanzó al abrirse, con el código y la configuración de ese momento. Si cerraste la ventana sin salir desde la bandeja, la app sigue viva con el servidor viejo. Lo mismo pasa después de `actualizar.bat` o de agregar un hotel. Para ver desde cuándo corre:
```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'cloudbeds_mcp.server' } | Select-Object ProcessId, CreationDate
```
Si la hora es anterior al cambio, sal desde la bandeja (clic derecho → Salir) y vuelve a abrir la app.
- Prueba el comando a mano (debe quedarse esperando sin mostrar errores; sal con Ctrl+C):
  ```powershell
  $env:PYTHONPATH="<RUTA>\src"; & "<RUTA>\.venv\Scripts\python.exe" -m cloudbeds_mcp.server
  ```
- Si moviste la carpeta del proyecto, recrea el entorno (`python -m venv .venv` y `pip install -r requirements.txt`) y actualiza las rutas del config.

### Mensajes sobre hoteles
| Mensaje | Causa | Qué hacer |
|---|---|---|
| "Indica de qué hotel quieres la información…" | Hay varios hoteles y la pregunta no dijo cuál | Es lo esperado: Claude debe preguntarle al usuario |
| "No encontré el hotel '…'" / "puede ser más de un hotel" | El nombre no coincide con ninguno, o coincide con varios | Usar el alias o el nombre corto; agregar `otros_nombres` en `hoteles.json` si el gerente usa otro nombre |
| "No hay API key de … en esta PC" | Ese hotel no tiene key en el keyring de esta PC | `scripts\agregar_hotel.py --alias <alias>` y reiniciar Claude |
| "Esta consulta es de un solo hotel" | Se pidió "red" en una herramienta operativa | Es lo esperado: Claude consulta cada hotel por separado |
| "El total de la red NO incluye: …" | Un hotel falló o no tiene key | Revisar ese hotel con `smoke_test.py` |
| "hoteles.json: …" (falta configuración) | El archivo tiene un error de formato o validación | Corregirlo, o regenerarlo con `agregar_hotel.py`; `agregar_hotel.py --estado` muestra el error |
| "La propiedad … ya está registrada con el alias '…'" | Se intentó dar de alta la misma propiedad con otro alias | Usar el alias existente o borrarlo antes con `--borrar` |

### `actualizar.bat` no actualiza
| Mensaje | Qué hacer |
|---|---|
| "[ALTO] Hay archivos del proyecto modificados" | Alguien editó archivos en esa PC. Revisar con `git status` y descartarlos (`git checkout -- <archivo>`) o avisar a Tecnología |
| "no es un clon de git" | La instalación se copió con `robocopy`. Reinstalar con `git clone` (checklist, sección B); el keyring se conserva |
| "No se pudo actualizar" | Sin internet, credenciales de GitHub vencidas (repo privado) o historia local distinta. Ejecutar `git pull --ff-only` a mano para ver el detalle |
| "La versión nueva no arranca" | Error en la versión publicada. Avisar a Tecnología; volver a la anterior con `git reset --hard HEAD@{1}` |

### Error 401 / "La API key de Cloudbeds es inválida"
- La key está mal copiada, fue revocada o falta. Ejecuta `scripts\agregar_hotel.py --estado` (o `guardar_key.py --estado` con un solo hotel) para ver de dónde se carga, y `scripts\smoke_test.py` para probarla.
- No se reintenta automáticamente, para no arriesgar un bloqueo. Genera una key nueva en Cloudbeds y guárdala con `scripts\agregar_hotel.py --alias <alias>`.

### Error 429 / "Cloudbeds limitó las consultas"
- El servidor ya espera `Retry-After` y reintenta 3 veces. Si el mensaje llega al chat, espera un minuto.
- No ejecutes varias copias del servidor ni otras integraciones con la misma key al mismo tiempo: excederlo repetidamente puede **suspender la key**.

### Mensajes `success: false` (HTTP 200 con error)
| Mensaje | Causa | Qué hacer |
|---|---|---|
| "El usuario de Cloudbeds que creó la API key fue desactivado" | La cuenta que autorizó la key ya no está activa | Crear una key nueva con una cuenta activa e **institucional** |
| "La API key no tiene acceso a esa propiedad" | `property_id` incorrecto o key de otra propiedad | Volver a dar de alta el hotel con `agregar_hotel.py`, que toma el ID de Cloudbeds |
| "La propiedad no está activa en Cloudbeds" | Propiedad suspendida o inactiva | Consultar con el administrador de la cuenta Cloudbeds |
| "Es probable que a la API key le falte el scope '…'" | La key se creó sin ese permiso | Crear una key nueva con el scope indicado (no se pueden agregar a una existente) |
| "Cloudbeds rechazó la consulta: …" | Otro error de Cloudbeds (se muestra el texto original) | Anotar el `X-Request-ID` del mensaje y consultar a soporte de Cloudbeds |

### Consultas lentas
`ingresos_periodo` depende de un endpoint lento de Cloudbeds (unos 4.5 s por cada 100 reservas): un mes tarda unos 16 s y un año unos 70 s. En la red, los hoteles corren en paralelo. Para periodos largos conviene consultar por trimestre.

### Comportamientos de Cloudbeds verificados (no documentados)
- Toma como **verdadero** cualquier booleano distinto de `0`, incluido el texto `"false"`. Por eso el servidor envía los booleanos como `1`/`0`, y `estado_housekeeping` filtra en el propio servidor.
- `getHousekeepingStatus` informa un `total` incorrecto. Se cuentan los elementos reales.
- `getSources` devuelve `data` como lista de listas.
- `getDashboard` devuelve llegadas y salidas como texto, y cuenta solo las **pendientes**.
