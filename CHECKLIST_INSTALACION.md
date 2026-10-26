# Checklist de instalación: PC del gerente

La hace Tecnología junto con el gerente. Tiempo estimado: 30 minutos. Marca cada casilla.

**PC:** ______________________ · **Sistema:** ☐ Windows ☐ macOS · **Fecha:** ____/____/______ · **Técnico:** ______________________

## A. Antes de empezar

- [ ] Claude Desktop está instalado y con sesión iniciada **con la cuenta del gerente**.
- [ ] Python 3.10 o superior: `python --version` (en macOS, `python3 --version`).
  En Windows, al instalarlo, marca **"Add python.exe to PATH"**.
- [ ] Git instalado: `git --version`. En Windows, desde https://git-scm.com, con las opciones por defecto.
- [ ] **Decididas las API keys.** Se recomienda **una key por hotel (Zentra Balta, Zentra Plaza y Zentra San José) para esta PC**, creada en Cloudbeds con una **cuenta institucional** y solo los scopes mínimos de [REGISTRO_ACCESOS.md](REGISTRO_ACCESOS.md). Así se puede revocar sin afectar a otras instalaciones. Anótalas en `REGISTRO_ACCESOS.local.md` en la PC de Tecnología. Ese archivo no se sube al repositorio.

## B. Descargar el proyecto con git (sin secretos)

- [ ] Clona el repositorio en una ruta **sin espacios ni acentos**, por ejemplo `C:\Zentra\mcp-cloudbeds`. En adelante la llamamos `<RUTA>`:
  ```powershell
  git clone https://github.com/jantons25/mcp-cloudbeds.git C:\Zentra\mcp-cloudbeds
  ```
  El repositorio no contiene `.env`, `hoteles.json` ni keys: esos se crean en esta PC y git nunca los sube ni los pisa.
- [ ] **Si el repositorio es privado:** la primera vez Git pedirá credenciales. Usa un **token de GitHub de solo lectura** para este repositorio (*fine-grained token* con permiso `Contents: Read-only`). Git lo guarda en el Administrador de credenciales de Windows, así que después `git pull` funciona sin pedirlo. No uses la contraseña ni un token con permisos de escritura.
- [ ] Instalaciones anteriores copiadas con `robocopy` no son un clon de git y no se pueden actualizar. Bórralas después de configurar esta (el keyring se conserva).

## C. Entorno y configuración (en `<RUTA>`)

| Paso | Windows (PowerShell) | macOS (Terminal) |
|---|---|---|
| Entorno virtual | `python -m venv .venv` | `python3 -m venv .venv` |
| Dependencias | `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` | `./.venv/bin/python -m pip install -r requirements.txt` |
| Archivo de configuración | `Copy-Item .env.example .env` | `cp .env.example .env` |

- [ ] Entorno virtual creado y dependencias instaladas sin errores.
- [ ] En `.env`: `CLOUDBEDS_SHOW_PII=false`, **`CLOUDBEDS_API_KEY` vacío** y `CLOUDBEDS_PROPERTY_ID` vacío (cada hotel tiene el suyo en `hoteles.json`).
- [ ] **Alta de los 3 hoteles.** Repite una vez por hotel. El técnico pega la key, que no se ve en pantalla. El script la verifica, toma de Cloudbeds el nombre, propertyID, zona horaria y moneda, y guarda la key en el keyring. El gerente no necesita conocer las keys.
  ```powershell
  .\.venv\Scripts\python.exe scripts\agregar_hotel.py --alias balta
  .\.venv\Scripts\python.exe scripts\agregar_hotel.py --alias plaza
  .\.venv\Scripts\python.exe scripts\agregar_hotel.py --alias san_jose
  ```
- [ ] `scripts\agregar_hotel.py --estado` lista los 3 hoteles, cada uno con **"key: keyring (...)"**.
- [ ] `scripts\smoke_test.py` termina con **"Prueba de humo OK en todos los hoteles"**.

## D. Claude Desktop

- [ ] `scripts\configurar_claude.py` muestra la ruta del config detectada. Revísala y luego ejecuta `scripts\configurar_claude.py --aplicar`.
- [ ] Cierra Claude por completo: **clic derecho en el ícono de la bandeja → Salir** (en macOS, Cmd+Q). Vuelve a abrirlo.
- [ ] En un chat nuevo aparecen las herramientas de **cloudbeds** (14 en total, incluida `hoteles`).
- [ ] "¿Qué hoteles tienes?" lista Zentra Balta, Zentra Plaza y Zentra San José.
- [ ] "¿Cómo va el día de hoy?" **pregunta de qué hotel**.
- [ ] "¿Cómo va hoy Balta?" y "¿Cuántas llegadas tiene San José hoy?" devuelven datos que coinciden con el dashboard de cada hotel.

## E. Aceptación: 5 consultas del gerente **sin asistencia**

Entrega la [GUIA_GERENTE.md](GUIA_GERENTE.md) (impresa o en PDF). El gerente formula las preguntas con sus propias palabras.

| # | Pregunta del gerente | ¿Respondió bien? | Observaciones |
|---|---|---|---|
| 1 | | ☐ Sí ☐ No | |
| 2 | | ☐ Sí ☐ No | |
| 3 | | ☐ Sí ☐ No | |
| 4 | | ☐ Sí ☐ No | |
| 5 | | ☐ Sí ☐ No | |

- [ ] Las 5 consultas se respondieron correctamente **sin ayuda**.
- [ ] El gerente sabe qué hacer si falla (última sección de la guía) y a quién avisar.

**Firma del técnico:** ______________________ · **Firma del gerente:** ______________________

## F. Actualizaciones (cada vez que Tecnología avise)

- [ ] Doble clic en **`actualizar.bat`**, en la carpeta `<RUTA>`. Equivale a `.\.venv\Scripts\python.exe scripts\actualizar.py`.
  - Descarga la última versión (`git pull`) y reinstala dependencias si cambiaron.
  - Comprueba que el servidor arranque. **No toca** `.env`, `hoteles.json` ni las keys.
  - Si dice "[ALTO] Hay archivos del proyecto modificados", no hace nada: avisa a Tecnología.
- [ ] Cierra Claude **desde la bandeja** (clic derecho → Salir) y vuelve a abrirlo.
- [ ] Opcional: `scripts\actualizar.py --probar` también ejecuta la prueba de conexión.
- [ ] **Hotel nuevo en el grupo:** Tecnología crea la key y ejecuta `scripts\agregar_hotel.py` en esta PC. No hace falta actualizar el código.
