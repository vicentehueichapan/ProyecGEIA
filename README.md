# NotifyOps MVP

Carpeta limpia para probar solo el sistema MVP.

## Ejecutar pruebas

```powershell
python -m unittest tests.test_pipeline -v
```

## Ejecutar pipeline

```powershell
python -m src.notifyops.pipeline
```

## Archivos principales

- `src/notifyops/pipeline.py`: pipeline MVP.
- `tests/test_pipeline.py`: pruebas unitarias.
- `data/raw/social_events.csv`: dataset de entrada.
- `data/reports/validation_errors.csv`: errores/anomalias.
- `data/reports/kpi_report.csv`: KPIs.
- `logs/notifyops.log`: trazabilidad.
- `data/notifyops.db`: base SQLite.
