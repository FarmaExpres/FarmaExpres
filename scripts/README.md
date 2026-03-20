update_kpi.py — Generador de KPI

Este script consulta la API de GitHub para generar un reporte de participación
por commits en varios repositorios y actualiza el bloque KPI en el `README.md`.

Requisitos

- Python 3.8+
- `requests` (ver `requirements.txt`)

Uso

Ejemplo simple (usa GH_TOKEN del entorno si está disponible):

```bash
python scripts/update_kpi.py
```

Opciones útiles:

- `--config` ruta al archivo de configuración (por defecto `kpi-repos.json`)
- `--output` archivo JSON de salida (por defecto `kpi-data.json`)
- `--readme` archivo README a actualizar (por defecto `README.md`)
- `--token` token de GitHub (si no se usa `GH_TOKEN` en entorno)
- `--dry-run` no escribe archivos, solo simula
- `--no-readme` no actualiza el README
- `--verbose` muestra logs DEBUG

Ejemplo con token y sin actualizar README:

```bash
python scripts/update_kpi.py --token $GH_TOKEN --no-readme
```
