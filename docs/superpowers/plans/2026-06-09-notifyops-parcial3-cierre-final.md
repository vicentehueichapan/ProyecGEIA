# NotifyOps Parcial 3 Final Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cerrar las brechas verificadas de la rubrica de Parcial 3 y dejar NotifyOps reproducible, trazable, demostrable y documentado sin ampliar innecesariamente su arquitectura.

**Architecture:** El pipeline ETL existente permanece como fase operativa. La extension IA genera un dataset determinista con señales historicas independientes de las reglas, compara modelos sencillos, selecciona uno mediante metricas comunes y produce decisiones combinadas. Airflow orquesta ambas fases; las salidas alimentan un dashboard BI interactivo local y un Excel compatible con Power BI.

**Tech Stack:** Python 3.12, pandas, NumPy, matplotlib, scikit-learn, Pillow, unittest, Apache Airflow 2.9.3, Docker Compose, HTML/CSS/JavaScript, Excel/Power BI.

---

### Task 1: Establecer baseline aislado

**Files:**
- Verify: repository root

- [ ] **Step 1: Crear worktree y rama**

```powershell
git worktree add ..\.worktrees\notifyops-parcial3-final -b feature/notifyops-parcial3-final
```

Expected: worktree on `feature/notifyops-parcial3-final`.

- [ ] **Step 2: Instalar dependencias**

```powershell
python -m pip install -r requirements.txt
```

Expected: exit code `0`.

- [ ] **Step 3: Ejecutar baseline**

```powershell
python -m unittest discover -v
```

Expected: 15 tests pass.

### Task 2: Calidad de datos y etiqueta defendible

**Files:**
- Modify: `tests/test_notifyops_ai.py`
- Modify: `src/notifyops_ai/modeling.py`

- [ ] **Step 1: Escribir pruebas RED**

Agregar pruebas que exijan:

```python
def test_dataset_contains_predictive_feedback_risk_independent_of_hard_rules(self):
    events = modeling.generate_synthetic_events(rows=500, seed=42)
    clean = events[events.apply(modeling.rule_error_reason, axis=1).eq("")]
    self.assertGreater(clean["label_risky_event"].sum(), 0)
    self.assertTrue({"interaction_velocity_5m", "account_age_days", "historical_report_rate"}.issubset(events.columns))
```

```python
def test_quality_analysis_contains_statistics_and_imputation_strategy(self):
    events = modeling.generate_synthetic_events(rows=200, seed=42)
    quality = modeling.quality_summary(events)
    indicators = set(quality["indicator"])
    self.assertIn("content_length_mean", indicators)
    self.assertIn("content_length_median", indicators)
    self.assertIn("content_length_mode", indicators)
    self.assertIn("content_length_p25", indicators)
    self.assertIn("content_length_p75", indicators)
    self.assertIn("imputation_strategy", indicators)
```

- [ ] **Step 2: Verificar RED**

```powershell
python -m unittest tests.test_notifyops_ai.NotifyOpsAITests.test_dataset_contains_predictive_feedback_risk_independent_of_hard_rules tests.test_notifyops_ai.NotifyOpsAITests.test_quality_analysis_contains_statistics_and_imputation_strategy -v
```

Expected: failures caused by missing fields/statistics.

- [ ] **Step 3: Implementar generacion y calidad**

Agregar señales deterministas:

```python
"interaction_velocity_5m": int(rng.integers(1, 45)),
"account_age_days": int(rng.integers(1, 1500)),
"historical_report_rate": round(float(rng.beta(1.5, 12.0)), 4),
```

Definir riesgo historico mediante esas señales y no mediante azar sin explicación:

```python
behavioral_risk = (
    interaction_velocity_5m >= 32
    or account_age_days <= 7
    or historical_report_rate >= 0.24
)
is_risky = bool(rule_based_risk or behavioral_risk)
```

Extender `FEATURE_COLUMNS` y `quality_summary()` con estadísticas e imputación documentada.

- [ ] **Step 4: Verificar GREEN**

```powershell
python -m unittest tests.test_notifyops_ai -v
```

Expected: all AI tests pass.

### Task 3: Comparacion de modelos y rendimiento

**Files:**
- Modify: `requirements.txt`
- Modify: `tests/test_notifyops_ai.py`
- Modify: `src/notifyops_ai/modeling.py`

- [ ] **Step 1: Escribir pruebas RED**

```python
def test_ai_pipeline_compares_models_and_records_runtime(self):
    result = modeling.run_ai_pipeline(rows=240, seed=42, save_plots=False, write_outputs=False)
    self.assertGreaterEqual(len(result.model_comparison), 3)
    self.assertIn("selected", result.model_comparison.columns)
    self.assertGreater(result.performance["training_seconds"], 0)
    self.assertGreater(result.performance["inference_rows_per_second"], 0)
```

```python
def test_final_decisions_include_all_three_operational_states(self):
    modeling.run_ai_pipeline(rows=500, seed=42, save_plots=False, write_outputs=True)
    decisions = pd.read_csv("data/reports/ai/final_event_decisions.csv")
    self.assertEqual(
        set(decisions["final_decision"]),
        {"rechazado_por_reglas", "revision_por_ia", "aprobado_para_notificar"},
    )
```

- [ ] **Step 2: Verificar RED**

```powershell
python -m unittest tests.test_notifyops_ai -v
```

Expected: failures for missing comparison/performance and missing `revision_por_ia`.

- [ ] **Step 3: Implementar comparacion**

Agregar `scikit-learn` y evaluar:

```python
DummyClassifier(strategy="most_frequent")
LogisticRegression(max_iter=2000, random_state=seed)
RandomForestClassifier(n_estimators=200, max_depth=8, random_state=seed)
```

Usar una misma particion estratificada. Guardar:

```text
data/reports/ai/model_comparison.csv
data/reports/ai/performance_summary.csv
data/reports/ai/roc_curve_points.csv
data/reports/ai/confusion_matrix_<model>.csv
```

Seleccionar el modelo final por F1 y desempatar por ROC-AUC. Registrar tiempos con `perf_counter()`.

- [ ] **Step 4: Verificar GREEN**

```powershell
python -m unittest tests.test_notifyops_ai -v
```

Expected: all AI tests pass.

### Task 4: Evidencias, seguridad y dataset BI

**Files:**
- Create: `src/notifyops_ai/bi_dataset.py`
- Modify: `tests/test_notifyops_ai.py`
- Modify: `src/notifyops_ai/modeling.py`
- Update: `data/bi/notifyops_powerbi_dataset.xlsx`

- [ ] **Step 1: Escribir pruebas RED**

Exigir que el Excel sea coherente con los CSV actuales y contenga:

```python
required = {
    "resumen_bi", "metricas_modelo", "comparacion_modelos",
    "matriz_confusion", "curva_roc", "calidad_datos",
    "estadisticas_calidad", "decisiones_finales",
    "rendimiento_local", "rendimiento_ia",
    "auditoria_seguridad", "roles_acceso", "guia_powerbi",
}
```

Verificar que las métricas del Excel coincidan con `model_metrics.csv`.

- [ ] **Step 2: Verificar RED**

```powershell
python -m unittest tests.test_notifyops_ai -v
```

Expected: missing sheets and consistency function.

- [ ] **Step 3: Implementar exportacion unica**

`bi_dataset.py` debe leer artefactos ya producidos y construir el Excel; no entrenar modelos ni duplicar reglas. Debe eliminar identificadores y contenido de las hojas destinadas a visualización agregada.

- [ ] **Step 4: Verificar GREEN**

```powershell
python -m unittest tests.test_notifyops_ai -v
```

Expected: workbook and consistency tests pass.

### Task 5: Dashboard BI interactivo local

**Files:**
- Modify: `tests/test_notifyops_ai.py`
- Replace: `dashboard/notifyops_ai_dashboard.html`
- Create: `dashboard/data/dashboard_data.json`

- [ ] **Step 1: Escribir prueba RED**

```python
def test_dashboard_is_interactive_and_uses_generated_data(self):
    html = Path("dashboard/notifyops_ai_dashboard.html").read_text(encoding="utf-8")
    self.assertIn('id="eventTypeFilter"', html)
    self.assertIn('id="decisionFilter"', html)
    self.assertIn("dashboard_data.json", html)
    self.assertIn("<canvas", html)
    self.assertIn("<script", html)
```

- [ ] **Step 2: Verificar RED**

```powershell
python -m unittest tests.test_notifyops_ai.NotifyOpsAITests.test_dashboard_is_interactive_and_uses_generated_data -v
```

Expected: failure because current dashboard is static.

- [ ] **Step 3: Implementar dashboard**

Crear una interfaz sin dependencias remotas con:

- tarjetas KPI;
- filtros por evento y decision;
- tabla filtrable;
- visualizaciones Canvas de decisiones, modelos y calidad;
- vistas `Resumen`, `Modelo y calidad`, `Seguridad y operacion`;
- carga de `dashboard/data/dashboard_data.json`;
- estado de error legible si el archivo no puede cargarse directamente.

- [ ] **Step 4: Verificar GREEN y navegador**

```powershell
python -m unittest tests.test_notifyops_ai -v
python -m http.server 8000
```

Open: `http://localhost:8000/dashboard/notifyops_ai_dashboard.html`.

Expected: dashboard renders, filters update values and no elements overlap.

### Task 6: Orquestacion Airflow completa

**Files:**
- Modify: `tests/test_airflow_dag.py`
- Modify: `dags/notifyops_etl_dag.py`
- Modify: `docker-compose.airflow.yml`

- [ ] **Step 1: Escribir prueba RED**

```python
self.assertIn("python -m src.notifyops_ai.modeling", source)
self.assertIn("run_ai_model", source)
self.assertIn("verify_ai_outputs", source)
self.assertIn("model_comparison.csv", source)
self.assertIn("notifyops_powerbi_dataset.xlsx", source)
```

- [ ] **Step 2: Verificar RED**

```powershell
python -m unittest tests.test_airflow_dag -v
```

Expected: DAG does not yet contain IA tasks.

- [ ] **Step 3: Implementar DAG**

Flujo:

```text
start -> verify_input -> run_etl -> verify_etl
      -> run_ai_model -> verify_ai_outputs -> summarize -> finish
```

Mantener `schedule=timedelta(weeks=2)` y `catchup=False`.

- [ ] **Step 4: Verificar GREEN**

```powershell
python -m unittest tests.test_airflow_dag -v
docker compose -f docker-compose.airflow.yml config --quiet
```

Expected: tests and compose validation pass.

### Task 7: Notebook ejecutado y evidencias finales

**Files:**
- Modify: `notebooks/modelo_validacion_eventos_notifyops.ipynb`
- Create: `docs/evidencias/parcial3/`

- [ ] **Step 1: Actualizar notebook**

El notebook debe leer las salidas finales y explicar:

- calidad e imputación;
- particion;
- análisis uni/bivariado;
- comparación;
- selección;
- métricas;
- seguridad;
- limitaciones.

- [ ] **Step 2: Ejecutar notebook**

```powershell
jupyter nbconvert --to notebook --execute notebooks/modelo_validacion_eventos_notifyops.ipynb --output modelo_validacion_eventos_notifyops.ipynb --ExecutePreprocessor.timeout=180
```

Expected: every code cell has execution count and outputs.

- [ ] **Step 3: Generar evidencias**

Copiar o generar capturas verificables de gráficos, ejecución y dashboard bajo `docs/evidencias/parcial3/`, sin fabricar salidas.

### Task 8: Evolucionar README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Conservar contenido valido**

Mantener contexto, evolución, diagramas, ejecución y defensa, eliminando duplicación.

- [ ] **Step 2: Agregar indice y matriz de evidencia**

Cada criterio debe apuntar a un archivo real y usar estados honestos.

- [ ] **Step 3: Verificar comandos**

Ejecutar en el orden documentado:

```powershell
python -m unittest discover -v
python -m src.notifyops.pipeline
python -m src.notifyops_ai.modeling
docker compose -f docker-compose.airflow.yml config --quiet
```

- [ ] **Step 4: Revisar afirmaciones**

```powershell
rg -n "100%|completo|Power BI|nube|interactivo|accuracy|recall|Gini|dashboard" README.md
```

Cada coincidencia debe tener evidencia.

### Task 9: Validacion integral

**Files:**
- Verify: all project artifacts

- [ ] **Step 1: Suite completa**

```powershell
python -m unittest discover -v
```

- [ ] **Step 2: Ejecucion limpia**

```powershell
python -m src.notifyops.pipeline
python -m src.notifyops_ai.modeling
```

- [ ] **Step 3: Validaciones estructurales**

```powershell
docker compose -f docker-compose.airflow.yml config --quiet
python -m compileall src dags tests
git diff --check
git status --short
```

- [ ] **Step 4: Validacion visual**

Abrir dashboard en desktop y mobile, verificar interacción, ausencia de solapamientos y datos coincidentes.

- [ ] **Step 5: Auditoria de rubrica**

Releer la rúbrica y mapear cada indicador a evidencia real. Cualquier elemento externo no generado, como un `.pbix` sin Power BI Desktop, debe quedar marcado como pendiente externo.
