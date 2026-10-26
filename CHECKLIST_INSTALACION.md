# Checklist de instalación: PC del gerente

La hace Tecnología junto con el gerente. Tiempo estimado: 30 minutos. Marca cada casilla.

**PC:** ______________________ · **Sistema:** ☐ Windows ☐ macOS · **Fecha:** ____/____/______ · **Técnico:** ______________________

## A. Antes de empezar

- [ ] Claude Desktop está instalado y con sesión iniciada **con la cuenta del gerente**.
- [ ] Python 3.10 o superior: `python --version` (en macOS, `python3 --version`).
  En Windows, al instalarlo, marca **"Add python.exe to PATH"**.
- [ ] **Decidido qué API key usar.** Se recomienda **una key propia para esta PC**, creada en Cloudbeds con una **cuenta institucional** y solo los scopes de lectura de la sección D del registro. Así se puede revocar sin afectar a otras instalaciones. Anótala en [REGISTRO_ACCESOS.md](REGISTRO_ACCESOS.md).

## B. Copiar el proyecto (sin secretos)

- [ ] Copia la carpeta del proyecto **sin** `.env`, `.venv`, `__pycache__`, `.pytest_cache` ni `.coverage`. En Windows, desde la carpeta de origen:
  ```powershell
  robocopy . "C:\Zentra\mcp-cloudbeds" /E /XD .venv __pycache__ .pytest_cache /XF .env .coverage
  ```
  Usa una ruta **sin espacios ni acentos**, por ejemplo `C:\Zentra\mcp-cloudbeds`. En adelante la llamamos `<RUTA>`.

## C. Entorno y configuración (en `<RUTA>`)

| Paso | Windows (PowerShell) | macOS (Terminal) |
|---|---|---|
| Entorno virtual | `python -m venv .venv` | `python3 -m venv .venv` |
| Dependencias | `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` | `./.venv/bin/python -m pip install -r requirements.txt` |
| Archivo de configuración | `Copy-Item .env.example .env` | `cp .env.example .env` |

- [ ] Entorno virtual creado y dependencias instaladas sin errores.
- [ ] En `.env`: `CLOUDBEDS_PROPERTY_ID=318358`, `CLOUDBEDS_SHOW_PII=false` y **`CLOUDBEDS_API_KEY` vacío**.
- [ ] **Key en el keyring:** el técnico ejecuta `scripts\guardar_key.py` y escribe la key él mismo. El gerente no necesita conocerla ni guardarla.
- [ ] `scripts\guardar_key.py --estado` responde **"El servidor usará la key de: keyring"**.
- [ ] `scripts\smoke_test.py` muestra **Zentra Balta · 318358 · PEN · America/Lima**.

## D. Claude Desktop

- [ ] `scripts\configurar_claude.py` muestra la ruta del config detectada. Revísala y luego ejecuta `scripts\configurar_claude.py --aplicar`.
- [ ] Cierra Claude por completo: **clic derecho en el ícono de la bandeja → Salir** (en macOS, Cmd+Q). Vuelve a abrirlo.
- [ ] En un chat nuevo aparecen las herramientas de **cloudbeds** (13 en total).
- [ ] "¿Cómo va el día de hoy?" devuelve datos que coinciden con el dashboard de Cloudbeds.

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
