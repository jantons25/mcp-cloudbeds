# Guía: desglose de Booking a Cloudbeds en otra PC (tarea diaria 1:00 a. m.)

**Objetivo:** que toda reserva de Booking registrada en Cloudbeds, en casa o futura, tenga los 8 datos: 7 campos personalizados y una nota.

**Qué pasa cada día a la 1:00 a. m.:**
1. **`pendientes`:** el script busca en Cloudbeds las reservas de Booking.com que pernoctan desde anoche o llegan después. Lista las que faltan leer o cambiaron.
2. **Lectura:** Claude lee solo esas reservas en el extranet de Booking, con el navegador.
3. **`agregar`:** el script guarda la lectura en el CSV y en el Excel del mes de llegada.
4. **`cargar`:** el script escribe los 8 datos en Cloudbeds. Solo escribe lo que cambió.
   - A una reserva cancelada que ya tenía el desglose le deja una nota de anulación: sus montos no son ingreso.
   - Si un día no corrió, la corrida siguiente recupera las noches que faltaron.

Formato de los archivos: [skills/zentra-desglose-booking/FORMATO.md](skills/zentra-desglose-booking/FORMATO.md).

## 1. Instalar el proyecto
1. Sigue [CHECKLIST_INSTALACION.md](CHECKLIST_INSTALACION.md), secciones A a D:
   - Python;
   - `git clone`;
   - `.venv` y `pip install -r requirements.txt`;
   - `scripts\agregar_hotel.py` para los 3 hoteles;
   - `scripts\configurar_claude.py --aplicar`.
2. **Permisos de las keys:** Reserva y Campos personalizados, de Leer y Escribir. Nada de Ajuste, Pago, Tasa ni Eliminar.
3. **Copia `reportes\booking\` completa desde la PC anterior.** Trae los CSV, los Excel y `estado.json`. Sin esa carpeta, la primera corrida vuelve a leer en Booking todas las reservas en casa y futuras.

## 2. Probar (en PowerShell, en la carpeta del proyecto)
```powershell
.\.venv\Scripts\python.exe scripts\smoke_test.py
```
```powershell
.\.venv\Scripts\python.exe scripts\desglose_booking.py pendientes
```
Debe listar las reservas de Booking por hotel y crear `reportes\booking\pendientes_AAAA-MM-DD.csv`.
```powershell
.\.venv\Scripts\python.exe scripts\desglose_booking.py cargar
```
Es la vista previa: no escribe nada y debe terminar sin «error».

## 3. Instalar el skill y preparar Booking
```powershell
Copy-Item -Recurse -Force skills\zentra-desglose-booking "$env:USERPROFILE\.claude\skills\"
```
- Si el proyecto no está en `D:\Juanjo\PROYECTOS\mcp-cloudbeds`, edita `PROYECTO` en `SKILL.md`, en la copia de `%USERPROFILE%\.claude\skills\`.
- **Booking:**
  - En Chrome, instala Claude in Chrome.
  - Entra a admin.booking.com con «Mantener sesión iniciada».
- **Permisos de la tarea:** crea `.claude\settings.local.json` en el proyecto:
```json
{
  "permissions": {
    "allow": [
      "Bash(.venv/Scripts/python.exe scripts/desglose_booking.py:*)",
      "PowerShell(.\\.venv\\Scripts\\python.exe scripts\\desglose_booking.py:*)",
      "Write(reportes/booking/**)",
      "mcp__cloudbeds__planes_tarifa",
      "mcp__cloudbeds__disponibilidad",
      "mcp__cloudbeds__tipos_habitacion"
    ]
  }
}
```
- **Prueba a mano:** en Claude (pestaña Code, carpeta del proyecto) escribe «Ejecuta el skill zentra-desglose-booking».

## 4. Programar la tarea
En Claude Desktop, pestaña Code, con la carpeta del proyecto abierta, escribe:

> Crea una tarea programada local, diaria a la 1:00 a. m. (cron `0 1 * * *`), en esta carpeta, con este prompt: «Ejecuta el skill zentra-desglose-booking: pendientes, lee en Booking las reservas listadas, agrega la lectura, haz la vista previa y, si no hay errores, carga con --confirmar. Termina con el informe corto del skill.»

**Requisitos de la PC:**
- Encendida a la 1:00 a. m., sin suspensión.
- Hora de Lima.
- Claude Desktop abierto.
- Chrome con la sesión de Booking.

## 5. Revisión cada mañana
- El informe de la tarea en Claude.
- El detalle está en `logs\desglose_booking_*_carga.csv`.
- Los Excel están en `reportes\booking\reporte_booking_AAAA-MM.xlsx`.

**Códigos de salida:**
- `0`: bien. Las «no encontrada», «a releer» y «a revisar» se informan y se reintentan solas.
- `1`: alguna reserva con error.
- `2`: archivo inválido o sin acceso.

## 6. Problemas comunes

| Mensaje | Qué hacer |
|---|---|
| «Booking pidió iniciar sesión; no se cargó nada» | Inicia sesión en Chrome. La corrida siguiente recupera los días que faltan. |
| `ARCHIVO INVÁLIDO: Fila N: …` en `agregar` | Corrige esa fila de `lectura_*.csv` y repite `agregar`. |
| `a releer` | La reserva cambió en Cloudbeds. Mañana sale en `pendientes` como `modificada`. |
| `a revisar` | Hay 2 reservas activas en Cloudbeds con el mismo N° de Booking. Revísalas a mano. |
| `No hay K para AAAA-MM` | Repite `agregar` con `--k 3.43` (o el valor vigente). |
| `ciérralo en Excel y repite` | Cierra el Excel del reporte y vuelve a correr. |
| Falta de scope `write:…` | Crea una key con Reserva y Campos personalizados de Leer y Escribir, y guárdala con `scripts\agregar_hotel.py`. |
