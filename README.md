# DataVivo Agent

Agente local de **[DataVivo](https://datavivo.es)** para Windows. Conecta tu programa de gestión (SQL Server, MySQL,
PostgreSQL, ficheros DBF de FoxPro/Clipper/dBase, Excel y CSV) con Power BI, tu CRM y asistentes de IA, **en modo de
solo lectura** y **sin abrir puertos**.

> Este repositorio es público para que el responsable de IT de tu empresa pueda revisar exactamente qué se instala en
> el servidor. *Open-source local agent for DataVivo: read-only, outbound-only connector for legacy business data.*

## Descargar
**[⬇ Última versión para Windows](https://github.com/DataVivo/datavivo-agent/releases/latest/download/datavivo-agent-windows.zip)**
· [Todas las versiones](https://github.com/DataVivo/datavivo-agent/releases)

Cada versión incluye su suma SHA256. Para verificar la descarga en PowerShell:
```powershell
Get-FileHash .\datavivo-agent-windows.zip -Algorithm SHA256
```

## Instalación
1. Crea una cuenta en [datavivo.es](https://datavivo.es/app) (14 días de prueba gratis).
2. En el panel, descarga tu `config.yaml` y crea un token de agente.
3. Descomprime el zip en el servidor donde están tus datos, edita `config.yaml` y ejecuta en PowerShell **como administrador**:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install-agent.ps1 -Token "dva_..." -Config .\config.yaml
   ```
Instrucciones detalladas en `LEEME.txt`, dentro del zip.

## Qué hace y qué NO hace
| | |
|---|---|
| ✅ Abre **una única conexión saliente** cifrada (WSS, puerto 443) hacia DataVivo | ❌ No abre puertos ni requiere VPN |
| ✅ Expone **solo** las tablas y columnas que declaras en `config.yaml` | ❌ No permite escribir, modificar ni borrar datos |
| ✅ Usa siempre consultas parametrizadas sobre una lista blanca | ❌ No ejecuta SQL enviado desde la nube: la nube solo pide "tabla + filtros" |
| ✅ Guarda el token y las credenciales de BD en `C:\ProgramData\DataVivo`, accesible solo para SYSTEM y Administradores | ❌ No envía detalles internos de errores (rutas, SQL, credenciales) fuera de tu red |

Defensa en profundidad del modo solo lectura (`sql_guard.py`, `connectors/`):
1. El protocolo no tiene operaciones de escritura.
2. Cada sentencia SQL se revisa antes de ejecutarse y se bloquean `INSERT`, `UPDATE`, `DELETE`, `DROP`, `EXEC`…
3. Las consultas personalizadas de `config.yaml` se validan al arrancar.
4. La sesión de base de datos se abre en modo `READ ONLY` cuando el motor lo permite.

**Recomendación:** usa además un usuario de base de datos con permisos solo de lectura (p. ej. `db_datareader`).

## Desarrollo
```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m pytest              # tests de conectores y seguridad
.\.venv\Scripts\python agent.py --config config.yaml --check
powershell -ExecutionPolicy Bypass -File packaging\build.ps1   # genera dist\datavivo-agent-windows.zip
```
Las versiones se publican automáticamente al crear un tag `vX.Y.Z` (ver `.github/workflows/release.yml`).

## Seguridad
¿Has encontrado una vulnerabilidad? Consulta [SECURITY.md](SECURITY.md).

## Licencia
[MIT](LICENSE) © DataVivo
