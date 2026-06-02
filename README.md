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

## Orden recomendado de ejecucion para revisar el MVP

Ejecutar todos los comandos desde la carpeta raiz del repositorio:

```powershell
cd "C:\ruta\donde\descargaste\ProyecGEIA"
```

### 1. Instalar dependencias

```powershell
pip install -r requirements.txt
```

Este paso prepara las librerias necesarias para ejecutar el pipeline, las pruebas y la generacion de evidencias.

### 2. Ver datos originales antes de la ETL

```powershell
Import-Csv .\data\raw\social_events.csv | Format-Table -AutoSize
```

Los datos de entrada vienen mezclados, desordenados y con anomalias intencionales para demostrar limpieza y validacion.

### 3. Ejecutar pruebas automatizadas

```powershell
python -m unittest discover -v
```

Resultado esperado:

```text
OK
```

### 4. Ejecutar pipeline DataOps

```powershell
python -m src.notifyops.pipeline
```

El pipeline ejecuta ingesta, limpieza, transformacion, validacion, carga, generacion de notificaciones, reportes, KPIs y logs.

### 5. Ver datos despues de la transformacion

```powershell
Import-Csv .\data\processed\events_processed.csv | Select-Object event_id,event_type,source_user_id,target_user_id,created_at,notification_text | Format-Table -AutoSize
```

Aqui se observa la normalizacion de tipos de evento, eliminacion de duplicados y creacion del texto de notificacion.

### 6. Ver datos validos y datos rechazados

```powershell
Import-Csv .\data\validated\events_validated.csv | Select-Object event_id,event_type,source_user_id,target_user_id,created_at,notification_text | Format-Table -AutoSize
```

```powershell
Import-Csv .\data\reports\validation_errors.csv | Select-Object event_id,event_type,created_at,error_reason | Format-Table -AutoSize
```

Los registros rechazados quedan con el motivo tecnico del error.

### 7. Ver salidas finales ordenadas del mas reciente al mas antiguo

```powershell
Import-Csv .\data\reports\events_recent_all.csv | Select-Object event_id,event_type,created_at,notification_text | Format-Table -AutoSize
```

```powershell
Import-Csv .\data\reports\likes_recent.csv | Select-Object event_id,event_type,created_at,notification_text | Format-Table -AutoSize
Import-Csv .\data\reports\comments_recent.csv | Select-Object event_id,event_type,created_at,notification_text | Format-Table -AutoSize
Import-Csv .\data\reports\follows_recent.csv | Select-Object event_id,event_type,created_at,notification_text | Format-Table -AutoSize
```

### 8. Ver KPIs

```powershell
Import-Csv .\data\reports\kpi_report.csv | Format-List
```

```powershell
Get-Content .\data\reports\demo_summary.txt
```

### 9. Ver notificaciones generadas

```powershell
Import-Csv .\data\reports\notifications.csv | Select-Object notification_id,event_id,event_type,target_user_id,created_at,delivered_at,latency_seconds | Format-Table -AutoSize
```

### 10. Ver logs de ejecucion

```powershell
Get-Content .\logs\notifyops.log -Tail 30
```

### 11. Revisar automatizacion con Airflow

```powershell
docker compose -f docker-compose.airflow.yml up
```

Abrir `http://localhost:8080`, ingresar con usuario `admin` y clave `admin`, activar `notifyops_etl_dag` y ejecutar el DAG manualmente. Al terminar, apagar Airflow:

```powershell
docker compose -f docker-compose.airflow.yml down -v --remove-orphans
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

## Ejecutar extension IA Parcial 3

La extension de Parcial 3 adapta el notebook de clasificacion binaria del profesor al caso NotifyOps. En vez de clasificar mensajes como `spam/no_spam`, clasifica eventos sociales como `valido/riesgoso`.

Guia detallada:

```text
README_PARCIAL3_IA.md
```

Ejecutar modelo IA:

```powershell
python -m src.notifyops_ai.modeling
```

Abrir notebook adaptado:

```text
notebooks/modelo_validacion_eventos_notifyops.ipynb
```

Abrir dashboard local:

```text
dashboard/notifyops_ai_dashboard.html
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

Para apagar Airflow correctamente al finalizar la revision, abrir otra PowerShell en la misma carpeta del repositorio y ejecutar:

```powershell
docker compose -f docker-compose.airflow.yml down -v --remove-orphans
```

Esto detiene el contenedor y elimina los volumenes temporales de Airflow usados solo para la demo. El proyecto no queda configurado para reiniciarse automaticamente.

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
