# NotifyOps MVP

Sistema MVP para automatizar una ETL de notificaciones de una red social. Procesa eventos mezclados de likes, comentarios y seguidores, valida anomalias, genera notificaciones, calcula KPIs y produce vistas recientes ordenadas desde el evento mas nuevo al mas antiguo.

Las fechas de los reportes se muestran en formato legible con hora, minuto, segundo y milisegundos:

```text
YYYY-MM-DD HH:MM:SS.mmm
```

Ejemplo:

```text
2026-05-14 09:01:03.000
```

## Ejecutar pruebas

```powershell
python -m unittest tests.test_pipeline -v
python -m unittest tests.test_airflow_dag -v
python -m unittest discover -v
```

## Ejecutar pipeline

```powershell
python -m src.notifyops.pipeline
```

## Ejecutar con Docker

```powershell
docker build -t notifyops-mvp .
docker run --rm notifyops-mvp
```

Para regenerar resultados directamente en la carpeta local:

```powershell
docker run --rm -v "${PWD}\data:/app/data" -v "${PWD}\logs:/app/logs" notifyops-mvp
```

## Ejecutar con Airflow

Airflow se incluye como complemento de automatizacion ETL. El DAG no reemplaza el pipeline Python: lo orquesta.

Importante: el compose no tiene reinicio automatico. Si cierras Docker Desktop, Airflow no se volvera a prender solo.

```powershell
docker compose -f docker-compose.airflow.yml up
```

Luego abrir:

```text
http://localhost:8080
```

Credenciales de demo:

```text
usuario: admin
clave: admin
```

En Airflow, activar y ejecutar manualmente el DAG:

```text
notifyops_etl_dag
```

El DAG tambien queda configurado con frecuencia quincenal para representar el ciclo de mejora del caso:

```text
schedule=timedelta(weeks=2)
```

Esto equivale a automatizar la ETL cada dos semanas, alineado con el caso de estudio donde el equipo experimenta y ajusta funcionalidades en ciclos quincenales. Se usa `timedelta(weeks=2)` en vez de un cron ambiguo para expresar exactamente el intervalo de dos semanas.

El DAG ejecuta estas tareas:

```text
start -> verify_input_dataset -> run_notifyops_pipeline -> verify_outputs -> summarize_kpis -> finish
```

## Archivos principales

- `src/notifyops/pipeline.py`: pipeline MVP.
- `dags/notifyops_etl_dag.py`: DAG complementario de Airflow para automatizar la ETL.
- `tests/test_pipeline.py`: pruebas unitarias del pipeline.
- `tests/test_airflow_dag.py`: prueba de existencia y estructura del DAG.
- `data/raw/social_events.csv`: dataset de entrada con eventos mezclados.
- `data/reports/events_recent_all.csv`: todos los eventos validos ordenados de reciente a antiguo.
- `data/reports/likes_recent.csv`: likes ordenados de reciente a antiguo.
- `data/reports/comments_recent.csv`: comentarios ordenados de reciente a antiguo.
- `data/reports/follows_recent.csv`: seguidores ordenados de reciente a antiguo.
- `data/reports/notifications.csv`: notificaciones generadas, tambien ordenadas de reciente a antiguo.
- `data/reports/validation_errors.csv`: errores/anomalias.
- `data/reports/kpi_report.csv`: KPIs.
- `logs/notifyops.log`: trazabilidad.
- `data/notifyops.db`: base SQLite.

## Defensa breve

El dataset de entrada contiene eventos sociales mezclados y desordenados. La ETL limpia, transforma, valida y carga la informacion. Luego genera una vista general reciente y tres vistas separadas por tipo de interaccion. Airflow permite automatizar ese flujo como proceso DataOps, mientras Docker permite ejecutarlo en un entorno reproducible.
