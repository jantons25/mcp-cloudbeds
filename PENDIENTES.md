# Pendientes del MCP de Cloudbeds: estado al 26/10/2026

Contexto para continuar en un chat nuevo. El plan original está en `D:\Juanjo\DESCARGAS\PLAN_MCP_CLOUDBEDS.md`.

## Dónde estamos

Las fases **F0 a F5 están aprobadas**. Los **entregables de F6 están completos**. Lo único que falta es la **aceptación con el gerente**. F6 es la última fase del plan; la v2 queda fuera de alcance.

**Verificado el 26/10/2026 a las 14:22**, después de reiniciar Claude Desktop desde la bandeja:

- Claude Desktop (PID 36236) arrancó a las 14:22:33, y sus servidores `cloudbeds_mcp.server` a las 14:22:36–38. Es el **código actual**.
- `resumen_dia` desde Claude respondió con datos reales: ocupación 45.45 %, 8 llegadas (2 pendientes), 6 salidas (1 pendiente). Las cifras coinciden con el dashboard.
- La key se lee del **keyring** de Windows (servicio `cloudbeds-mcp`). En `.env` está vacía.
- `pytest`: 147/147 tests pasan. Cobertura total 95 %, `client.py` 94 %.

## Lo que queda por hacer

### 1. Completar el registro de accesos (lo hace el usuario)

En [REGISTRO_ACCESOS.md](REGISTRO_ACCESOS.md) hay campos ✏️ que no se pueden obtener por API:

- [ ] Nombre de la key en Cloudbeds
- [ ] Fecha de creación de la key
- [ ] Confirmar en Cloudbeds que la key **no** tiene scopes `write:*` ni `delete:*`
- [ ] Fecha de rotación (creación + 6 meses)

### 2. Key para la PC del gerente (recomendado)

- [ ] Crear en Cloudbeds una key nueva con una **cuenta institucional**. La actual la autorizó la cuenta personal de Juan Antón (user_id 573347): si esa cuenta se desactiva, la key deja de funcionar.
- [ ] Darle solo los scopes `read:hotel`, `read:dashboard`, `read:reservation`, `read:room`, `read:housekeeping` y `read:rate`.
- [ ] Anotarla en la segunda tabla de `REGISTRO_ACCESOS.md`.

### 3. Instalación en la PC del gerente

Seguir [CHECKLIST_INSTALACION.md](CHECKLIST_INSTALACION.md), secciones A a D:

- [ ] Copiar el proyecto **sin secretos** (el checklist trae el comando `robocopy`).
- [ ] Crear el `.venv`, instalar `requirements.txt` y copiar `.env.example` a `.env`.
- [ ] Ejecutar `scripts\guardar_key.py`. El técnico escribe la key; nunca se pega en un chat.
- [ ] Ejecutar `scripts\guardar_key.py --estado`, que debe decir "keyring", y `scripts\smoke_test.py`.
- [ ] Ejecutar `scripts\configurar_claude.py`, revisar la ruta que detecta y luego ejecutar `scripts\configurar_claude.py --aplicar`.
- [ ] **Salir desde la bandeja** (clic derecho → Salir) y volver a abrir Claude. Cerrar solo la ventana no basta.

### 4. Aceptación de F6 (criterio del plan)

- [ ] Entregar [GUIA_GERENTE.md](GUIA_GERENTE.md), impresa o en PDF.
- [ ] El gerente hace **5 consultas sin asistencia**. Se anotan en la tabla de la sección E del checklist, con la firma de ambos.
- [ ] Cuando las 5 respondan bien, F6 queda **cerrada** y el plan termina.

## Lecciones de esta instalación (para no repetirlas)

- **Ruta real del config** (instalación MSIX de Claude 3.6556): `%LOCALAPPDATA%\Claude-Data\claude_<id>\claude_desktop_config.json`. La ruta `Packages\...\LocalCache\Roaming\Claude` es una ubicación abandonada. `configurar_claude.py` ya detecta la correcta.
- **Claude Desktop borra `cwd`** al reescribir su config. Lo que hace funcionar al servidor es `env.PYTHONPATH = <RUTA>\src`.
- **Si al reiniciar sigue el código viejo**, Claude no se cerró de verdad. Compruébalo con la hora de arranque del proceso (comando en el README, sección "Solución de problemas").
- **Cloudbeds trata `"false"` como verdadero.** Los booleanos se envían como `1`/`0`, y el filtro de ocupada/libre de housekeeping se aplica localmente.
- **Las consultas de ingresos de un año tardan ~70 s.** Es normal: la API da ~4.5 s por página, y está documentado en el README.

## Reglas del plan que siguen vigentes

Solo lectura (GET con allowlist) · la key nunca se imprime, nunca va en el código ni en el chat · `.env` nunca se entrega · logs solo a stderr y sin datos personales · PII enmascarada por defecto · máximo 4 req/s · no avanzar sin aprobación explícita.

## Archivos clave

| Archivo | Para qué |
|---|---|
| `src/cloudbeds_mcp/server.py` | Las 13 herramientas MCP |
| `src/cloudbeds_mcp/client.py` | Cliente HTTP: allowlist, rate limit, reintentos |
| `src/cloudbeds_mcp/aggregations.py` | Resúmenes e ingresos (F4) |
| `src/cloudbeds_mcp/desktop_config.py` | Detección y escritura del config de Claude |
| `scripts/guardar_key.py` | Guardar, consultar o borrar la key del keyring |
| `scripts/configurar_claude.py` | Configurar Claude Desktop |
| `scripts/smoke_test.py` | Prueba rápida de conexión |
| `README.md` | Documentación técnica y solución de problemas |

## Para el chat nuevo

Abre el chat en `D:\Juanjo\PROYECTOS\mcp-cloudbeds` y empieza con:

> Lee PENDIENTES.md. Seguimos con la entrega de F6 al gerente.
