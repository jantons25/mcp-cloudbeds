# Plan: varias API keys por hotel y datos financieros en el MCP de Cloudbeds

> **Estado (22/11/2026):** **implementado con la API contable.** Herramientas nuevas `extras_periodo`, `pagos_periodo` y `resumen_financiero`, con soporte para "la red"; 408 tests pasan (98 %). Probadas con datos reales de Balta del 15/11/2026: 100 % de los medios de pago identificados y la habitación cuadra con `ingresos_periodo`. Falta cuadrar contra los informes de Cloudbeds y, si Cloudbeds lo habilita, pasar a Insights.
>
> Antes: **Decisión: opción A.** Una sola key con los 8 scopes de lectura, que ve las 3 propiedades, guardada para `balta`, `plaza` y `san_jose`. Las fases 1 y 2 (varias keys por hotel) ya no hacen falta.
> Sondeo con `scripts/sondear_api.py`. Rondas 1 y 2 hechas en Balta con el 15/11/2026. Ronda 3 pendiente: espera que Tecnología dé permiso de Insights al usuario de la key.

## Hallazgos de la fase 0

**Ronda 1 (Balta, 15/11/2026):**

- `read:item` y `read:payment` funcionan: 72 ítems en 7 categorías y 8 medios de pago (Tarjeta de Crédito, Transferencia Bancaria, Efectivo, Tarjeta de Débito, Factura, Onsite Terminal, Yape, Plin).
- `getTransactions` y `getPayments` **no existen en v1.3** (404). Se descarta el plan B en v1.3.
- **La API contable acepta la key** con `Authorization: Bearer` y `X-Property-ID`. 70 transacciones por `service_date`: 37 ITEM, 23 PAYMENT y 10 ROOM, todas con `sourceKind` RESERVATION y moneda PEN.
- **Los montos parecen 100 veces más chicos de lo real.** Con `amount / 10^currencyScale`, el total de habitación del día daba una cifra imposible. Ronda 2: ver los montos crudos y la escala.
- **Los extras no se cruzan con el catálogo por `externalRelationId`** (0 de 37). Ronda 2: probar el cruce por el nombre del ítem en `description`.
- **Códigos internos:** 2000 y 2000V (ítem y su anulación) en ITEM; 9000, 9100 y 9200 en PAYMENT; 1000 y 8000 en ROOM. Hipótesis por confirmar: el código 9xxx distingue el tipo de pago.
- El filtro de pagos por `transaction_datetime` + `external_relation_kind` devolvió **HTTP 400** sin mensaje. Ronda 2: probar variantes y mostrar el error.
- **Insights está disponible con esta key** (`X-API-KEY`): datasets 1 Financiero, 2 Huéspedes, 3 Reservas, 5 Pago, 6 Factura, 7 Ocupación, 8 House Keeping, 10 Desembolso, 14 Groups and Events y 18 Fiscal Documents. Puede ser la mejor fuente para los tres puntos, porque usa las mismas definiciones que los reportes de Cloudbeds. Ronda 2: listar las columnas de los datasets 1 y 5 y probar una consulta agregada.

**Ronda 2 (Balta, 15/11/2026):**

- **Montos:** `amount` ya viene en soles (169.64) y `currencyScale` = 2 es la cantidad de decimales. El script dividía por 100 por error; ya está corregido.
- **ROOM:** el código 1000 es la tarifa (169.64) y el 8000 parece su impuesto (20.36). La habitación ya la cubre `ingresos_periodo`.
- **Extras por rubro (API contable):** 32 de 37 se cruzan con el catálogo **por el nombre del ítem** en `description`; por id, ninguno. De los 5 sin cruce, 2 eran anulaciones (2000V). Funciona, pero depende del texto: si alguien renombra un ítem, se pierde el cruce.
- **Pagos (API contable):** el filtro que funciona es el **rango de `transaction_datetime`**, filtrando PAYMENT del lado del MCP. `external_relation_kind` solo se acepta junto con `external_relation_id`, y `business_date` no sirve como filtro único.
- **Medio de pago:** los 23 pagos se reconocieron por la descripción. **El código interno no alcanza:** 9000 mezcla débito y Yape; 9100 = efectivo; 9200 = transferencia.
- **Qué día cuenta un pago:** 5 de los 23 tienen `businessDate` distinto del día de la transacción (cierre de caja). Hay que decidir si "cobro del día" va por fecha contable o por fecha de transacción.
- **Insights:** el dataset Financiero (92 columnas) trae justo lo que hace falta: `item_service_category`, `payment_method`, `debit_amount`, `credit_amount`, `business_date`, `service_date` y `transaction_type`. Pero **la consulta responde 403**: *"User does not have permission to VIEW report"*. La key ve los datasets pero no puede ejecutar reportes: al usuario que la autorizó le falta el permiso de Insights.
- Ojo: Financiero y Pago también tienen columnas con datos personales (nombre del huésped, últimos 4 dígitos de la tarjeta, nombre en la factura). El MCP nunca las debe pedir.

**Revisión en Cloudbeds (22/11/2026):**

- El usuario que autorizó la key es **Organization Admin** y la organización no tiene funciones (roles) personalizadas. No falta ningún permiso de usuario que se pueda activar.
- El formulario de "Nuevas credenciales" solo pide nombre, tipo de integración, URI de redirección y "Habilitar para toda la organización". **No se eligen scopes por key.** El MCP usa una credencial de tipo Accounting & Finance habilitada para toda la organización (su nombre va en `REGISTRO_ACCESOS.local.md`).
- En Informes solo están los informes de Cloudbeds, Hubs, Suscripciones y "Explore con IA". **No hay constructor de informes personalizados.** La consulta de la API de Insights arma un informe a medida, y es probable que eso necesite una función que la cuenta no tiene. No hay ningún ajuste en la pantalla para activarlo: hay que pedírselo a Cloudbeds.
- Para cuadrar cifras en la fase 0 sirven dos informes de Cloudbeds: *"Vista general de complementos, artículos y servicios vendidos por categoría"* (extras por rubro) y el informe de pagos.

**Fuente elegida, sujeta a la ronda 3:**

1. **Insights** si Tecnología habilita el permiso. Usa los rubros y medios de pago nativos de Cloudbeds y cuadra con sus reportes.
2. **API contable** si no se habilita. Ya funciona, con el rubro deducido por nombre de ítem y el medio de pago por descripción, y un aviso cuando algo no se pueda clasificar.

## Respuesta corta

Sí se puede. El límite no está en la cantidad de APIs. Está en dos cosas:

1. **Los scopes de la key.** Cloudbeds decide qué datos entrega según los permisos con los que se creó la key. Las keys actuales tienen `read:hotel`, `read:dashboard`, `read:reservation`, `read:room`, `read:housekeeping` y `read:rate`. Ninguno de esos da acceso a extras ni a pagos.
2. **Lo que el MCP sabe pedir.** El cliente solo acepta 14 endpoints de la API v1.3 (lista blanca en `client.py`), solo hace GET y solo maneja una key por hotel.

La categoría que se elige al crear la credencial ("Accounting & Finance", "BI - Inteligencia Empresarial / Reportes", etc.) no aparece en la documentación de Cloudbeds como algo que habilite datos. Parece ser solo una clasificación. Lo que cuenta son los scopes que se marcan.

### Qué hace falta para cada dato

| Dato pedido | Fuente en Cloudbeds | Scope | Estado hoy |
|---|---|---|---|
| 1. Extras cargados (desayunos, minibar, lavandería, estacionamiento…) por día, sede y rubro | Accounting API: `POST /accounting/v1.0/transactions` con `externalRelationKind` = `ITEM`, `ITEM_POS`, `ADDON`. Rubro: `getItems` / `getItemCategories` (v1.3) | `read:payment` + `read:item` | No existe |
| 2. Pagos recibidos por día, sede y medio de pago | La misma búsqueda de transacciones con `externalRelationKind` = `PAYMENT`. Catálogo de medios: `getPaymentMethods` | `read:payment` | No existe |
| 3a. Reservas, tarifas, disponibilidad, canales | v1.3, ya integrado | los actuales | **Ya cubierto** por `buscar_reservas`, `planes_tarifa`, `disponibilidad`, `fuentes_reserva` e `ingresos_periodo` (con desglose por canal) |
| 3b. Reportes financieros | Insights API (`/datainsights/v1.1/`), datasets *Financial* y *Payments*. Si no está disponible, se arman desde las transacciones contables | sin documentar | No existe |

Fuentes (leídas el 22/11/2026): [listTransactions](https://developers.cloudbeds.com/reference/listtransactions-1), [getItems](https://developers.cloudbeds.com/reference/get_getitems-2), [getItemCategories](https://developers.cloudbeds.com/reference/get_getitemcategories-2), [getPaymentMethods](https://developers.cloudbeds.com/reference/get_getpaymentmethods-2), [Insights API](https://developers.cloudbeds.com/docs/introduction-to-cloudbeds-insights-api-1), [cambios en getTransactions](https://developers.cloudbeds.com/docs/gettransations-endpoint-new-cloudbeds-accounting-service).

### Lo que la documentación no confirma (se resuelve en la fase 0)

- **Medio de pago en la Accounting API.** El esquema de la transacción no trae un campo explícito de medio de pago. Puede venir en `description`, en `account`, o haber que cruzarlo con otro endpoint. Es el mayor riesgo del punto 2.
- **`getTransactions` y `getPayments` (v1.2/v1.3).** Cloudbeds dice que `getTransactions` sigue vigente y que se "enriquece" con el sistema contable nuevo, pero su página de referencia no está en el índice v1.3. Es el plan B para extras y pagos.
- **Insights API.** Solo está disponible para propiedades que usan *Cloudbeds Insights*. Acepta el encabezado `X-API-KEY`, pero no dice si sirve una key `cbat_` ni qué scope necesita.
- **Límite de peticiones.** No está documentado si los 5 req/s son por key o por propiedad. Hoy el MCP comparte el límite por key.
- **Paginación** de la búsqueda de transacciones (límite de 1100 por página; falta ver cómo se pide la siguiente).
- **Importes:** la Accounting API los da en la unidad mínima de la moneda (céntimos) y hay que dividir según `currencyScale`.

## Decisión previa: ¿una key con todo o varias keys por hotel?

Los scopes no se agregan a una key existente; hay que crear otra. Como las keys de los tres hoteles igual hay que recrearlas (la actual da 401), hay dos caminos:

| Opción | Cómo | A favor | En contra |
|---|---|---|---|
| **A. Una key por hotel con todos los scopes** | Crear las keys nuevas sumando `read:item` y `read:payment` | Cero cambios en la configuración del MCP; solo fases 0, 3, 4 y 5 | Una sola key ve operación y finanzas. Si se filtra, se filtra todo |
| **B. Varias keys por hotel** (lo que se pidió) | Key operativa (la de siempre) + key financiera aparte, cada una con sus scopes | Mínimo privilegio. Finanzas puede crear, rotar o revocar su key sin tocar la operativa. Permite sumar una tercera credencial (p. ej. Insights) si Cloudbeds la exige aparte | Una fase más de trabajo (fases 1 y 2) y un paso más al dar de alta cada hotel |

El plan cubre la opción B, pero el diseño es compatible con A: un hotel con una sola key que tenga todos los scopes funciona igual, sin configurar nada extra.

## Diseño de la opción B

### Configuración (sin secretos en `hoteles.json`)

```json
{
  "alias": "balta",
  "nombre": "Zentra Balta",
  "property_id": "000001",
  "credenciales": [
    { "nombre": "principal", "scopes": ["read:hotel", "read:dashboard", "read:reservation", "read:room", "read:housekeeping", "read:rate"] },
    { "nombre": "finanzas",  "scopes": ["read:payment", "read:item"] }
  ]
}
```

- `credenciales` es opcional. Si no está, el hotel tiene una sola key llamada `principal` y se comporta como hoy.
- Las keys siguen en el keyring:
  - `principal`: `CLOUDBEDS_API_KEY:balta` (el nombre actual, no cambia).
  - otras: `CLOUDBEDS_API_KEY:balta:finanzas`.
  - variable de entorno equivalente: `CLOUDBEDS_API_KEY_BALTA__FINANZAS`.
- Los scopes no se tipean: `agregar_hotel.py` los **detecta** probando un endpoint representativo de cada uno (`getDashboard` → `read:dashboard`, `getItems` → `read:item`, `getPaymentMethods` → `read:payment`…) y guarda en el JSON los que respondieron.

### Ruteo por scope

- Cada endpoint de la lista blanca ya tiene su scope (`ALLOWED_ENDPOINTS`). Se agregan los nuevos.
- Un objeto nuevo, `HotelClient`, agrupa los `CloudbedsClient` de un hotel y, en cada `get`, usa la credencial que tiene el scope del endpoint. Para `server.py` no cambia nada: las herramientas siguen pidiendo `client.get("getItems", ...)` y el ruteo es interno.
- Si ninguna key del hotel tiene el scope, el error lo dice claro: *"Ninguna key de Zentra Balta tiene el permiso read:payment. Agrégala con `agregar_hotel.py --alias balta --credencial finanzas`."*
- En "la red", un hotel sin la key financiera queda fuera del total y sale en `advertencia`, como ya pasa con los hoteles sin key.
- **Límite de peticiones:** mientras no se confirme si es por key o por propiedad, todas las keys de un mismo hotel comparten un limitador de 4 req/s (la opción conservadora).

### Cliente: nuevas APIs y la regla de solo lectura

- La lista blanca pasa de `endpoint → scope` a `(API, método, ruta) → scope`, con tres bases:
  - `https://api.cloudbeds.com/api/v1.3/` (la actual)
  - `https://api.cloudbeds.com/accounting/v1.0/`
  - `https://api.cloudbeds.com/datainsights/v1.1/` (solo si la fase 0 confirma acceso)
- La búsqueda de transacciones y la consulta de Insights son **POST que solo leen**. Se permiten únicamente esas dos rutas, nombradas una por una. Cualquier otro POST sigue bloqueado y hay un test que lo verifica. La regla "solo lectura" se mantiene; lo que cambia es que ya no equivale a "solo GET".
- Encabezados por API: v1.3 usa `x-api-key`; Accounting e Insights piden `X-Property-ID` y autenticación Bearer (se confirma en la fase 0).
- Los montos de la Accounting API se convierten a unidades de moneda con `currencyScale` antes de agregarlos.

### Herramientas nuevas

| Herramienta | Qué devuelve | "red" |
|---|---|---|
| `extras_periodo` | Extras cargados por día y por rubro (categoría de Cloudbeds), con cantidad e importe. Parámetros: fechas, `hotel`, `agrupar` (día / rubro / ambos) | Sí |
| `pagos_periodo` | Cobros reales por día y medio de pago, con devoluciones aparte y total neto | Sí |
| `reporte_financiero` | Resumen del periodo: ingresos por cuenta (habitación, extras, impuestos), pagos y saldo pendiente. Desde Insights si hay acceso; si no, armado con las transacciones contables | Sí |

- **Rubros:** se usan las categorías de ítems de Cloudbeds tal cual. Si se quieren agrupar distinto (p. ej. juntar varias categorías en "Alimentos y bebidas"), se agrega un mapeo opcional en `hoteles.json` después.
- **Datos personales:** las transacciones traen descripciones y referencias a reservas que pueden incluir nombres. Las herramientas solo devuelven totales agregados, nunca líneas con datos de huéspedes.
- **Caché:** el catálogo de ítems y categorías y los medios de pago se guardan un día, como el inventario.

## Fases

Cada fase deja `pytest` en verde. No se pasa a la siguiente sin aprobación.

### Fase 0: verificación con datos reales (bloqueante)

- Crear en **un** hotel una key de prueba con `read:item` y `read:payment` (cuenta institucional, sin `write:*` ni `delete:*`). En la pantalla de Cloudbeds, elegir la categoría "Accounting & Finance".
- Script nuevo `scripts/sondear_api.py`: llama a los endpoints candidatos para un día y muestra solo nombres de campos, tipos y conteos, nunca valores con datos personales.
- Responder:
  - [ ] ¿La búsqueda de transacciones responde con una key `cbat_`? ¿Con qué encabezado?
  - [ ] ¿Dónde está el medio de pago? Si no está, ¿`getTransactions` o `getPayments` lo traen?
  - [ ] ¿Cómo se pagina? ¿Qué fecha usar para "por día": `serviceDate`, `businessDate` o `transactionDatetime`?
  - [ ] ¿Tenemos Cloudbeds Insights? ¿La key puede consultar `/datainsights/v1.1/datasets`?
  - [ ] Un día de extras y de pagos cuadra con el reporte equivalente en la pantalla de Cloudbeds.
- **Entregable:** una sección "Hallazgos de la fase 0" en este archivo con las respuestas, y la decisión entre opción A y B.

### Fase 1: configuración con varias credenciales (sin cambios visibles)

- `config.py`: `HotelEntry` y `Hotel` ganan `credenciales`; `Settings` pasa a ser por credencial (key, nombre, scopes). Validación: nombres únicos por hotel, scopes con formato `read:<algo>`, rechazo de cualquier `write:*` / `delete:*`.
- Lectura de keys del keyring y del entorno con los nombres nuevos, sin romper los actuales.
- Tests: hoteles sin `credenciales` (compatibilidad), hotel con dos credenciales, credencial sin key en esta PC, scopes inválidos.

### Fase 2: ruteo por scope

- `HotelClient` en `hotels.py`; `HotelRegistry` lo entrega en lugar de un `CloudbedsClient` suelto.
- Limitador compartido por propiedad.
- Mensajes de error por scope faltante; `advertencia` en "la red".
- Tests: el endpoint va a la key correcta, scope ausente, dos hoteles con la misma key, las 14 herramientas actuales siguen pasando sin cambios.

### Fase 3: cliente para Accounting (e Insights si aplica)

- Lista blanca por API, método y ruta; las dos rutas POST de consulta.
- Encabezados por API, conversión de montos, paginación según la fase 0.
- Tests: un POST no listado se rechaza; montos con distintas escalas; errores 401/403 con el scope correcto en el mensaje.

### Fase 4: `extras_periodo` y `pagos_periodo`

- Agregaciones en `aggregations.py` (por día, por rubro, por medio de pago) y `merge_*` para la red (los importes solo se suman si la moneda coincide, como hoy).
- Descripciones de las herramientas que dejen claro qué incluye cada una (p. ej. que `ingresos_periodo` sigue siendo solo habitación).
- Tests con respuestas grabadas (sin datos reales de huéspedes).

### Fase 5: reportes financieros

- `reporte_financiero` desde Insights o desde las transacciones, según la fase 0.
- Revisar con el gerente si al punto 3 le falta algo que hoy no cubren las herramientas existentes (por ejemplo, tarifas día por día para un mes o producción por canal en un periodo).

### Fase 6: scripts, documentación y prueba real

- `agregar_hotel.py --alias balta --credencial finanzas`: pide la key sin eco, detecta scopes, guarda en el keyring y actualiza `hoteles.json`. `--estado` muestra cada credencial con sus scopes (nunca la key).
- `smoke_test.py`: prueba cada credencial de cada hotel.
- Actualizar `README.md`, `GUIA_GERENTE.md` (preguntas de ejemplo: "extras de ayer en Plaza por rubro", "cobros de la semana de la red por medio de pago"), `REGISTRO_ACCESOS.md`, `CHECKLIST_INSTALACION.md` y `PENDIENTES.md`.
- Prueba real en los tres hoteles comparando contra los reportes de Cloudbeds.

## Lo que hace Tecnología en Cloudbeds

Por hotel, además de la key operativa que ya está pendiente:

- Opción A: crear la key operativa sumando `read:item` y `read:payment`.
- Opción B: crear una segunda key "finanzas" con solo `read:item` y `read:payment`.
- En ambos casos: cuenta institucional, sin permisos de escritura, y anotarla en `REGISTRO_ACCESOS.local.md`.
- Si se quiere Insights: confirmar con Cloudbeds que la propiedad tiene *Cloudbeds Insights* y qué credencial pide la API.

## Reglas que siguen vigentes

Solo lectura (lista blanca explícita, ahora con dos POST de consulta nombrados) · las keys nunca se imprimen ni van en el código, en `hoteles.json` ni en el chat · PII enmascarada y solo totales en los datos financieros · logs a stderr sin parámetros · máximo 4 req/s por hotel · no avanzar sin aprobación.
