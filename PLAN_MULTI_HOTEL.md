# Plan: soporte multi-hotel en el MCP de Cloudbeds (v2, por fases)

> **Estado (26/10/2026):** fases 1 y 2 **completas**. Fase 3 **completa en código**, sin commit: 338 tests pasan, cobertura 98 %, 14 herramientas (incluida `hoteles`).
> Fase 3 entregada: `scripts/agregar_hotel.py` (lógica en `admin.py`), `smoke_test.py` multi-hotel, `scripts/actualizar.py` + `actualizar.bat` (lógica en `updater.py`, probada con repositorios git reales) y `CHECKLIST_INSTALACION.md` con `git clone`, alta de hoteles y sección F de actualizaciones.
> **Falta de la fase 3:** la prueba real, que necesita las 3 keys nuevas porque la actual devuelve 401, y hacer commit y push para que la PC del gerente pueda clonar. Las fases 4 y 5 están pendientes.
> Nota sobre la fase 2: mientras no esté la fase 4, ninguna herramienta acepta "red". La descripción del parámetro le indica al modelo que consulte cada hotel por separado. La etiqueta `"hotel"` solo aparece con `hoteles.json`; en modo legacy las respuestas no cambian.
> Para continuar, abre un chat en `D:\Juanjo\PROYECTOS\mcp-cloudbeds` y escribe:
> *"Lee PLAN_MULTI_HOTEL.md y PENDIENTES.md. Sigue con la siguiente fase pendiente, con tests en verde."*
> Estado base: 147 tests pasan, cobertura 95 %, 13 herramientas MCP, un solo hotel (Zentra Balta, propertyID 318358).

## Objetivo

Una sola instancia del MCP atiende a los hoteles del grupo: **Zentra Balta, Zentra Plaza y Zentra San José**
(puede haber más). El gerente pregunta por el nombre corto ("¿cómo va Balta?", "llegadas de San José") y usa
**"red"** para referirse a los tres ("resumen de hoy de la red"). Si el modelo no sabe a qué hotel se refiere,
**pregunta**. Las reglas actuales siguen vigentes: solo lectura, la key nunca se imprime, PII enmascarada,
máximo 4 req/s por key y logs solo a stderr.

## Decisiones confirmadas

| Tema | Decisión |
|---|---|
| Keys | Una API key por hotel. También se admite una key que vea varias propiedades (se distingue por `property_id`). |
| Selección de hotel | Parámetro opcional `hotel` en las 13 herramientas. Una sola instancia del MCP. |
| Nombres | Se acepta el alias, el nombre completo o el nombre sin la marca: "Balta", "Plaza", "San José" o "San Jose". Se ignoran "hotel", "Zentra" (la palabra común a todos los nombres) y artículos. |
| Toda la red | `hotel="red"`, y también "todos", "grupo", "toda la red" o "los tres". |
| Hotel omitido | Con un solo hotel se usa ese. Con varios, **no hay predeterminado**: la herramienta devuelve la lista de hoteles y el modelo le pregunta al gerente. Se puede definir un `predeterminado` en el JSON, pero no se recomienda. |
| Descubrimiento | La lista de hoteles va en la descripción del parámetro `hotel` de cada herramienta, así el modelo traduce el nombre a un alias sin hacer una llamada extra. |
| Config | `hoteles.json` sin secretos, generado en cada PC por `scripts/agregar_hotel.py`. Las keys se guardan en el keyring con el alias. |
| Actualizaciones | El gerente actualiza con `git pull` (script `scripts/actualizar.py`). Ver la fase 3. |

## Hallazgos de la revisión del 26/10/2026

- **La key actual devuelve 401.** `smoke_test.py` responde *"La API key de Cloudbeds es inválida, está ausente o fue revocada"*. Puede que se haya revocado o que se haya desactivado la cuenta que la creó. Hasta crear las keys nuevas, el MCP actual no responde. No bloquea las fases 1 y 2, porque los tests usan keys falsas.
- **El repositorio `jantons25/mcp-cloudbeds` es PÚBLICO.** Contiene `REGISTRO_ACCESOS.md`, con el nombre de la key, el user_id de la cuenta creadora y el propertyID, y `PENDIENTES.md`. No hay keys en el historial: se revisó buscando `cbat_` y solo aparecen valores de prueba. Se recomienda hacerlo **privado**. Si se hace privado, la PC del gerente necesita credenciales de solo lectura para `git pull`: un *fine-grained token* de solo lectura del repo guardado en el Administrador de credenciales de Git, o una *deploy key* de solo lectura. Por eso `hoteles.json` **no se sube** al repositorio (`.gitignore`).
- **Tests que dejarán de pasar en la fase 2**, si no se ajustan. Hoy los 147 pasan:
  1. `tests/test_aggregations.py:176` reemplaza `server._today` por `lambda: date(2026, 2, 14)`, sin argumentos. Cuando `_today` reciba la zona horaria del hotel, la lambda fallará con `TypeError`. Solución: `_today(tz=None)` con parámetro opcional y la lambda con `*_`.
  2. `tests/test_tools.py:209` reemplaza `server.load_settings` para simular que falta la key. Con el registro, el servidor cargará con `load_hotels()` y ese reemplazo ya no tendrá efecto. Solución: el servidor llama a una única función `server._load_registry()`, que en modo legacy sigue usando `load_settings`, y el test reemplaza esa función.

## Fases

Cada fase deja `pytest` en verde. No se avanza a la siguiente sin aprobación.

### Fase 1: configuración y registro de hoteles (sin cambios visibles para el usuario)

- `config.py`:
  - `Settings` gana `hotel_alias="principal"`, `hotel_name=None` y `currency=None`, con valores por defecto para no romper nada. `__repr__` los muestra y sigue sin exponer la key.
  - `load_catalog(path)`: lee y valida `hoteles.json`, **sin secretos**. El servidor la usará al arrancar para escribir la descripción del parámetro `hotel`.
  - `load_hotels(env_path, hoteles_path) -> HotelsConfig`: catálogo y keys.
    - Sin `hoteles.json`: modo legacy idéntico a hoy (`load_settings()`, alias `principal`).
    - Validaciones:
      - alias `^[a-z0-9_]{1,32}$` y único;
      - `nombre` obligatorio;
      - `property_id` obligatorio y único;
      - `tz` válida (por defecto `CLOUDBEDS_TZ`);
      - `moneda` con formato ISO de 3 letras (opcional);
      - claves desconocidas, error;
      - un nombre que choque con las palabras de grupo, error.
    - La key de cada hotel se busca en este orden:
      1. keyring `CLOUDBEDS_API_KEY:<alias>`;
      2. la variable de entorno `CLOUDBEDS_API_KEY_<ALIAS>`;
      3. la key legacy (keyring `CLOUDBEDS_API_KEY` o `.env`), solo para el hotel cuyo `property_id` coincide con `CLOUDBEDS_PROPERTY_ID`, o si hay un único hotel.
    - Un hotel sin key no tumba el servidor: queda como no disponible y se explica el motivo. Si ninguno tiene key, se lanza `ConfigError`.
  - `show_pii` y `max_results` siguen siendo globales, en `.env`.
- `errors.py`: `HotelError` (hotel no encontrado, ambiguo, sin key o no indicado), con un mensaje en español que lista los hoteles.
- `hotels.py` (nuevo):
  - `normalizar()`: minúsculas, sin tildes ni signos, sin "hotel", artículos ni la palabra de marca común a todos los nombres.
  - `HotelRegistry`:
    - `es_red(texto)`.
    - `client(texto)`: un solo hotel; "red" da error en las herramientas operativas.
    - `clients(texto)`: uno o todos los disponibles.
    - `no_disponibles()`, `describe()` (sin secretos) y `descripcion_parametro()`, el texto del parámetro `hotel`.
    - `aclose()`.
    - `HotelRegistry.single(client)`: compatibilidad con `server.set_client()`.
  - Búsqueda de un hotel, en orden: alias exacto, nombre o `otros_nombres` (texto exacto o pegado: "sanjose"), y por último palabras contenidas, que tienen que apuntar a un solo hotel ("san", "jose"). Más de un candidato da un error de ambigüedad. Ninguno da un error con la lista de hoteles.
  - Los clientes se crean cuando se usan por primera vez. Hay un `RateLimiter` por key, compartido entre los hoteles que usan la misma key.
- `client.py`: parámetro opcional `limiter=` en `CloudbedsClient`. Por defecto crea el suyo, como hoy.
- `hoteles.example.json` (se sube, sin IDs reales) y `.gitignore` con `hoteles.json`.
- Tests nuevos:
  - Config: legacy, JSON con 3 hoteles, validaciones, orden de las keys, hotel sin key, `repr`.
  - Normalización y búsqueda: "Balta", "zentra plaza", "San Jose", "SAN JOSÉ", "sanjose", "hotel balta", "red", "toda la red", "los tres", ambigüedad, no encontrado.
  - Limiter compartido, carga diferida y `aclose`.

### Fase 2: servidor

- `_registry` en lugar de `_client`. `set_client(client)` se mantiene y crea un registro de un solo hotel. Se agrega `_load_registry()`.
- Las 13 herramientas ganan el parámetro `hotel`. Su descripción se genera con `descripcion_parametro()`, que lista los hoteles, la palabra "red" y la indicación "si el gerente no lo dice y hay varios, pregúntale".
- `_today(tz=None)`, `_stay` y `_period` usan la zona horaria del hotel. Se quita "hora de Lima" de `instructions`, `_fecha_param` y `_period`. Los títulos y descripciones que dicen "del hotel" pasan a hablar del hotel elegido.
- `_tag(out, client)`: cada respuesta JSON empieza con `"hotel": {"alias", "nombre"}`.
- Herramienta nueva `hoteles`: alias, nombre, propertyID, zona horaria, moneda y disponibilidad. Con `verificar=true`, consulta `getHotelDetails`.
- `HotelError` se captura junto a `CloudbedsError` y `ConfigError`. `_error()` no le agrega "falta configuración".
- Herramientas operativas (`detalle_reserva`, `asignaciones_del_dia`, `habitaciones`, `estado_housekeeping`, `tipos_habitacion`, `fuentes_reserva`, `planes_tarifa`, `disponibilidad`): con "red" devuelven un mensaje que pide elegir un hotel.
- Ajustar los 2 tests descritos en los hallazgos. Tests con respx y 2 o 3 hoteles: cada herramienta envía el `propertyID` y la `x-api-key` del hotel pedido, el hotel omitido con varios hoteles produce un mensaje con la lista, y una zona horaria distinta cambia "hoy".

### Fase 3: alta de hoteles, actualización por git y prueba real

- `scripts/agregar_hotel.py`:
  1. Pide el alias y la key sin eco.
  2. Verifica la key con `userinfo` y `getHotels`.
  3. Deja elegir la propiedad si la key ve varias.
  4. Escribe o actualiza la entrada de `hoteles.json` con el nombre, `property_id`, zona horaria y moneda reales.
  5. Guarda la key en el keyring (`CLOUDBEDS_API_KEY:<alias>`).

  Opciones: `--estado`, una tabla por hotel con el origen de cada key (sin mostrarla), y `--borrar <alias>`.
- `scripts/guardar_key.py`: sin cambios en su uso (key legacy). Se agrega una nota que remite a `agregar_hotel.py`.
- `scripts/smoke_test.py`: recorre todos los hoteles configurados y marca los que fallan sin detenerse.
- `scripts/actualizar.py`:
  1. `git pull --ff-only`.
  2. Si cambió `requirements.txt`, ejecuta `pip install -r requirements.txt` en el `.venv`.
  3. Ejecuta `smoke_test` de forma opcional.
  4. Recuerda **salir de Claude desde la bandeja** y volver a abrirlo.

  Si hay cambios locales, se detiene y no toca nada.
- `CHECKLIST_INSTALACION.md`: la instalación en la PC del gerente pasa de `robocopy` a `git clone`, y se agrega el paso de alta de los 3 hoteles.
- Prueba real: crear las 3 keys nuevas (cuenta institucional, solo `read:*`), darlas de alta y comprobar en Claude Desktop "lista los hoteles", "¿cómo va Balta?" y "llegadas de San José".

### Fase 4: consolidado de la red

- `hotel="red"` en `estado_hotel`, `resumen_dia` y `buscar_reservas` (para preguntas como "¿en qué hotel está Pérez?"); después en `resumen_periodo` e `ingresos_periodo`.
- Los hoteles se consultan en paralelo con `asyncio.gather(return_exceptions=True)`. Si un hotel falla, el error se muestra en su entrada (`{"error": ...}`) y los demás siguen. Los hoteles sin key se listan en `advertencias`.
- Salida: `{"hoteles": {alias: {...}}, "total_red": {...}, "advertencias": [...]}`.
- `total_red`:
  - Conteos sumados.
  - Ocupación de la red = suma de habitaciones ocupadas entre suma de habitaciones. El inventario de cada hotel sale de `getRoomTypes` y el registro lo guarda un día.
  - Importes sumados solo si todos los hoteles tienen la misma moneda, tomada de `hoteles.json`. Con monedas distintas no se suman y se avisa.
  - ADR y RevPAR se recalculan desde los totales.
- `aggregations.py`: `merge_day_summaries`, `merge_period_summaries` y `merge_revenue`, testeadas por separado.

### Fase 5: documentación

- `README.md`: configuración multi-hotel, `hotel=`, "red", actualización por git y solución de problemas.
- `.env.example`: nota sobre `hoteles.json`.
- `GUIA_GERENTE.md`: ejemplos con Balta, Plaza, San José y "la red".
- `REGISTRO_ACCESOS.md`: una fila por key y hotel. Si el repositorio sigue público, mover los datos internos a un archivo no versionado.
- `PENDIENTES.md`.

## Verificación final

- `pytest`: todo en verde y cobertura de al menos 94 %.
- `agregar_hotel.py --estado` y `smoke_test.py` muestran los 3 hoteles.
- En Claude Desktop, tras salir desde la bandeja: "lista los hoteles", "¿cómo va el día?" (debe preguntar qué hotel), "resumen de hoy de Plaza" y "resumen de hoy de la red". Cuadrar las cifras con el dashboard de cada hotel.
- `actualizar.py` en la PC del gerente trae los cambios sin pasos manuales, salvo reiniciar Claude.

## Reglas del proyecto que siguen vigentes

Solo lectura (GET con allowlist) · la key nunca se imprime, nunca va en el código ni en el chat · `.env` y `hoteles.json` no se suben al repositorio · logs solo a stderr y sin datos personales · PII enmascarada por defecto · máximo 4 req/s por key · no avanzar sin aprobación explícita.
