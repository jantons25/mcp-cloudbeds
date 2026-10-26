# Pendientes del MCP de Cloudbeds: estado al 26/10/2026

Contexto para continuar en un chat nuevo. El plan original está en `D:\Juanjo\DESCARGAS\PLAN_MCP_CLOUDBEDS.md`. El plan multi-hotel, con sus 5 fases, está en [PLAN_MULTI_HOTEL.md](PLAN_MULTI_HOTEL.md).

## Dónde estamos

- **Plan original:** las fases F0 a F5 están aprobadas y los entregables de F6 están completos. Falta la aceptación con el gerente (punto 4).
- **Multi-hotel:** las 5 fases están completas en código.
  - Un solo MCP atiende a **Zentra Balta, Zentra Plaza y Zentra San José**.
  - Los hoteles se reconocen por su nombre corto, y "la red" agrupa a los tres.
  - Si el usuario no dice el hotel, Claude pregunta.
  - El gerente actualiza con `actualizar.bat` (`git pull`).
- **Tests:** 352 tests pasan, con cobertura del 98 %. Hay 14 herramientas, incluida `hoteles`.
- **Sin verificar con datos reales:** el multi-hotel todavía no se probó contra Cloudbeds, porque no hay keys válidas (punto 1).

## Lo que queda por hacer

### 1. Keys nuevas (urgente; lo hace Tecnología)

- [ ] **La key actual devuelve 401** (`smoke_test.py`, 26/10/2026): fue revocada o se desactivó la cuenta que la creó. Mientras tanto, el MCP no responde.
- [ ] Crear en Cloudbeds **una key por hotel** con una **cuenta institucional** y solo los scopes `read:hotel`, `read:dashboard`, `read:reservation`, `read:room`, `read:housekeeping` y `read:rate`. Confirmar que no tengan `write:*` ni `delete:*`.
- [ ] En la PC de Tecnología:
  1. `scripts\agregar_hotel.py --alias balta`, `--alias plaza` y `--alias san_jose`.
  2. `scripts\agregar_hotel.py --estado`.
  3. `scripts\smoke_test.py`.
- [ ] Anotarlas en `REGISTRO_ACCESOS.local.md`. Es el registro real, no se sube a git; [REGISTRO_ACCESOS.md](REGISTRO_ACCESOS.md) es solo la plantilla.
- [ ] Borrar la key vieja del keyring: `scripts\guardar_key.py --borrar`.

### 2. Prueba real del multi-hotel (fase 3 del plan multi-hotel)

Reiniciar Claude Desktop desde la bandeja y probar:

- [ ] "¿Qué hoteles tienes?"
- [ ] "¿Cómo va el día?": **debe preguntar** de qué hotel.
- [ ] "¿Cómo va hoy Balta?" y "llegadas de San José mañana": deben cuadrar con el dashboard de cada hotel.
- [ ] "¿Cómo va la red hoy?": el total debe ser la suma de los tres.
- [ ] "Ingresos de octubre de la red": comparar con los reportes de Cloudbeds de cada hotel.

### 3. Decidir la visibilidad del repositorio

- [ ] `jantons25/mcp-cloudbeds` es **público**.
  - El historial anterior contiene `REGISTRO_ACCESOS.md` con datos internos: nombre de la key, cuenta creadora y propertyID de Balta. No contiene keys.
  - Desde la fase 5 esos datos van en `REGISTRO_ACCESOS.local.md`.
  - Se recomienda hacerlo **privado**. En ese caso, la PC del gerente necesita un token de GitHub de solo lectura para `git pull` (checklist, sección B).

### 4. Instalación en la PC del gerente y aceptación de F6

Seguir [CHECKLIST_INSTALACION.md](CHECKLIST_INSTALACION.md), secciones A a F:

- [ ] `git clone`. **No usar `robocopy`**: sin un clon de git no se puede actualizar.
- [ ] `.venv`, `requirements.txt`, `.env` (copiado de `.env.example`) y el alta de los 3 hoteles con `agregar_hotel.py`.
- [ ] `scripts\configurar_claude.py --aplicar`, y luego **salir desde la bandeja** y volver a abrir Claude.
- [ ] Entregar [GUIA_GERENTE.md](GUIA_GERENTE.md), impresa o en PDF. Ya incluye los nombres de los hoteles, "la red" y las actualizaciones.
- [ ] El gerente hace **5 consultas sin asistencia**, por ejemplo una de un hotel, una de "la red" y una sin decir el hotel. Se anotan en la sección E del checklist, con la firma de ambos.
- [ ] Probar `actualizar.bat` en la PC del gerente con un cambio menor publicado en `main`.

## Lecciones (para no repetirlas)

- **Ruta real del config** (instalación MSIX de Claude 3.6556): `%LOCALAPPDATA%\Claude-Data\claude_<id>\claude_desktop_config.json`. `configurar_claude.py` ya detecta la correcta.
- **Claude Desktop borra `cwd`** al reescribir su config. Lo que hace funcionar al servidor es `env.PYTHONPATH = <RUTA>\src`.
- **Si al reiniciar sigue el código viejo**, Claude no se cerró de verdad. Compruébalo con la hora de arranque del proceso (README, "Solución de problemas"). Esto vale también después de `actualizar.bat` o de agregar un hotel.
- **Cloudbeds trata `"false"` como verdadero.** Los booleanos se envían como `1`/`0`.
- **Las consultas de ingresos de un año tardan ~70 s.** En la red, los hoteles corren en paralelo.
- **Un repositorio git en una carpeta superior** (por ejemplo, el perfil de usuario) hacía creer que cualquier subcarpeta era un clon. Por eso `actualizar.py` exige que la carpeta del proyecto sea la raíz del repositorio.

## Reglas que siguen vigentes

Solo lectura (GET con allowlist) · las keys nunca se imprimen, nunca van en el código, en `hoteles.json` ni en el chat · `.env`, `hoteles.json` y `REGISTRO_ACCESOS.local.md` nunca se suben · logs solo a stderr y sin datos personales · PII enmascarada por defecto · máximo 4 req/s por key · no avanzar sin aprobación explícita.

## Archivos clave

| Archivo | Para qué |
|---|---|
| `src/cloudbeds_mcp/server.py` | Las 14 herramientas MCP, el parámetro `hotel` y la ejecución en paralelo para "la red" |
| `src/cloudbeds_mcp/hotels.py` | Registro de hoteles: búsqueda por nombre, "red", clientes y límite de peticiones por key |
| `src/cloudbeds_mcp/config.py` | `.env`, `hoteles.json` y origen de cada key |
| `src/cloudbeds_mcp/client.py` | Cliente HTTP: allowlist, rate limit y reintentos |
| `src/cloudbeds_mcp/aggregations.py` | Resúmenes, ingresos y totales de la red (`merge_*`) |
| `src/cloudbeds_mcp/admin.py`, `updater.py` | Lógica de `agregar_hotel.py` y `actualizar.py` |
| `scripts/agregar_hotel.py` | Alta, estado y baja de hoteles (key en el keyring) |
| `scripts/actualizar.py`, `actualizar.bat` | Actualización con `git pull` |
| `scripts/smoke_test.py` | Prueba de conexión de todos los hoteles |
| `scripts/configurar_claude.py` | Configurar Claude Desktop |
| `scripts/guardar_key.py` | Key de la instalación de un solo hotel |
| `README.md` | Documentación técnica y solución de problemas |

## Para el chat nuevo

Abre el chat en `D:\Juanjo\PROYECTOS\mcp-cloudbeds` y empieza con:

> Lee PENDIENTES.md. Seguimos con la prueba real del multi-hotel y la entrega al gerente.
