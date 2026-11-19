# DataVivo Agent

[![CI](https://github.com/DataVivo/DataVivo-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/DataVivo/DataVivo-agent/actions/workflows/ci.yml)
[![Release probada](https://github.com/DataVivo/DataVivo-agent/actions/workflows/smoke.yml/badge.svg)](https://github.com/DataVivo/DataVivo-agent/actions/workflows/smoke.yml)
[![Última versión](https://img.shields.io/github/v/release/DataVivo/DataVivo-agent)](https://github.com/DataVivo/DataVivo-agent/releases/latest)
[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-blue)](LICENSE)

Agente local de **[DataVivo](https://datavivo.es/?utm_source=github&utm_medium=readme)** para Windows. Conecta tu programa
de gestión (SQL Server, MySQL, PostgreSQL, ficheros DBF de FoxPro/Clipper/dBase, Excel y CSV) con Power BI, tu CRM y
asistentes de IA, **en modo de solo lectura** y **sin abrir puertos**.

**De un `.DBF` de los 90 a Power BI o a Claude/ChatGPT en 15 minutos, sin migrar nada.**

👉 **[Pruébalo gratis 14 días](https://datavivo.es/?utm_source=github&utm_medium=readme)** · sin tarjeta ·
⭐ si te resulta útil, **dale una estrella** al repositorio: nos ayuda a que más empresas lo encuentren.

> Este repositorio es público para que el responsable de IT de tu empresa pueda revisar exactamente qué se instala en
> el servidor. *Open-source local agent for DataVivo: read-only, outbound-only connector for legacy business data
> (SQL Server, FoxPro/dBase DBF, Excel) → REST API + MCP server for AI assistants.*

## Qué puedes hacer con él
| Caso | Cómo |
|---|---|
| **Power BI / Excel** | El panel genera la consulta Power Query lista para pegar: descarga todas las filas con sus tipos |
| **Asistentes de IA (MCP)** | Claude, ChatGPT o tus agentes consultan tus tablas en lenguaje natural |
| **CRM, web, n8n/Make** | API REST con filtros (`?CIUDAD=Madrid&SALDO__gte=100`), JSON o CSV |

## Descargar
**[⬇ Última versión para Windows](https://github.com/DataVivo/datavivo-agent/releases/latest/download/datavivo-agent-windows.zip)**
· [Todas las versiones](https://github.com/DataVivo/datavivo-agent/releases)

Cada versión incluye su suma SHA256. Para verificar la descarga en PowerShell:
```powershell
Get-FileHash .\datavivo-agent-windows.zip -Algorithm SHA256
```

## Instalación
1. Crea una cuenta en [datavivo.es](https://datavivo.es/?utm_source=github&utm_medium=readme) (14 días de prueba gratis).
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
