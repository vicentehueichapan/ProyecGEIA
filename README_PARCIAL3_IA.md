# NotifyOps AI - Parcial 3

Esta extension adapta el notebook de clasificacion binaria entregado por el profesor al caso NotifyOps.

## Idea central

El ejemplo del profesor clasifica mensajes como `spam` o `no_spam`.

En NotifyOps clasificamos eventos sociales como:

```text
0 = evento valido
1 = evento riesgoso
```

El modelo funciona como un filtro inteligente predictivo. No reemplaza las reglas duras del pipeline; las complementa para anticipar eventos con mayor probabilidad de error antes de generar una notificacion.

## Ubicacion dentro del pipeline

La capa IA se ubica despues de la limpieza y transformacion, porque en ese punto los datos ya estan normalizados y pueden convertirse en variables predictivas.

```text
Ingesta
  -> Limpieza y transformacion
  -> Scoring IA de riesgo
  -> Validacion por reglas duras
  -> Decision final
  -> Carga, notificaciones, metricas y dashboard
```

La decision final combina reglas duras y modelo IA:

```text
Si fallan reglas duras        -> rechazado_por_reglas
Si pasan reglas + riesgo alto -> revision_por_ia
Si pasan reglas + riesgo bajo -> aprobado_para_notificar
```

Esto evita reemplazar controles obligatorios con IA. La IA mejora el pipeline como capa predictiva, pero las reglas estructurales y semanticas siguen siendo obligatorias.

## Orden de ejecucion

Ejecutar desde la raiz del repositorio:

```powershell
cd "C:\ruta\donde\descargaste\ProyecGEIA"
```

### 1. Ejecutar pruebas completas

```powershell
python -m unittest discover -v
```

### 2. Ejecutar pipeline IA

```powershell
python -m src.notifyops_ai.modeling
```

El comando genera:

- `data/ai/notifyops_ai_events.csv`: dataset sintetico de eventos sociales.
- `data/ai/feature_matrix.csv`: variables usadas por el modelo.
- `data/reports/ai/quality_summary.csv`: calidad de datos.
- `data/reports/ai/model_metrics.csv`: accuracy, precision, recall, F1, ROC-AUC y Gini.
- `data/reports/ai/confusion_matrix.csv`: matriz de confusion.
- `data/reports/ai/test_predictions.csv`: predicciones sobre datos de prueba.
- `data/reports/ai/new_event_predictions.csv`: prueba con eventos nuevos.
- `data/reports/ai/final_event_decisions.csv`: decision final combinando reglas duras y scoring IA.
- `data/reports/ai/charts`: graficos para informe y presentacion.
- `models/notifyops_ai_model.json`: modelo guardado.
- `dashboard/notifyops_ai_dashboard.html`: panel BI local.
- `data/bi/notifyops_powerbi_dataset.xlsx`: fuente Excel lista para importar en Power BI.

### 3. Ver metricas del modelo

```powershell
Import-Csv .\data\reports\ai\model_metrics.csv | Format-List
```

### 4. Ver matriz de confusion

```powershell
Import-Csv .\data\reports\ai\confusion_matrix.csv | Format-Table -AutoSize
```

### 5. Ver predicciones nuevas

```powershell
Import-Csv .\data\reports\ai\new_event_predictions.csv | Select-Object event_id,event_type,target_user_id,created_at,risk_probability,prediction,expected_explanation | Format-Table -AutoSize
```

### 6. Ver decision final integrada

```powershell
Import-Csv .\data\reports\ai\final_event_decisions.csv | Select-Object event_id,event_type,rule_error_reason,ai_risk_probability,ai_prediction,final_decision | Format-Table -AutoSize
```

Si PowerShell corta columnas por ancho de pantalla, usar:

```powershell
Import-Csv .\data\reports\ai\final_event_decisions.csv | Select-Object -First 5 | Format-List
```

### 7. Abrir dashboard

Abrir este archivo en el navegador:

```text
dashboard/notifyops_ai_dashboard.html
```

### 8. Abrir fuente Power BI

El Excel de integracion BI queda en:

```text
data/bi/notifyops_powerbi_dataset.xlsx
```

Ese archivo contiene hojas para metricas, matriz de confusion, calidad de datos, decisiones finales, rendimiento local, auditoria de seguridad, roles y guia de graficos. Para Power BI Desktop, usar `Obtener datos > Excel` y cargar las hojas indicadas en:

```text
data/bi/README_POWER_BI.md
```

## Como explicarlo

La Parcial 3 mejora NotifyOps agregando una capa de IA. El modelo aprende patrones de eventos validos y riesgosos usando variables como tipo de evento, usuario destino, fecha valida, duplicado y longitud del contenido.

La clase riesgosa representa eventos que podrian afectar la experiencia del usuario, por ejemplo:

- evento fuera del alcance del caso (`share`, `reaction`, `unknown`);
- usuario destino vacio;
- fecha invalida;
- evento duplicado.

Por eso el modelo se defiende como una capa predictiva de apoyo al pipeline DataOps.

## Riesgos controlados

- Eventos con errores estructurales no dependen del modelo: se rechazan por reglas duras.
- Eventos que pasan reglas pero tienen probabilidad alta de riesgo quedan en `revision_por_ia`.
- Los falsos negativos se identifican con matriz de confusion y se proponen como oportunidad de mejora.
- El dataset sintetico se declara como limitacion del MVP; en produccion se reemplazaria por historicos reales.
- El dashboard y los graficos dejan evidencia para explicar rendimiento, limitaciones y mejoras.

## Metricas

- `Accuracy`: porcentaje total de aciertos.
- `Precision`: cuando el modelo marca un evento como riesgoso, cuantas veces acierta.
- `Recall`: de todos los eventos riesgosos reales, cuantos logra detectar.
- `F1-score`: equilibrio entre precision y recall.
- `ROC-AUC`: capacidad del modelo para separar eventos validos y riesgosos.
- `Gini`: indicador derivado del AUC, calculado como `2 * AUC - 1`.

En este caso, `recall` es especialmente importante porque interesa detectar la mayor cantidad posible de eventos riesgosos antes de que generen notificaciones incorrectas.
