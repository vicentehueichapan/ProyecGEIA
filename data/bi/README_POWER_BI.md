# Guia Power BI - NotifyOps Parcial 3

Archivo principal:

```text
data/bi/notifyops_powerbi_dataset.xlsx
```

Este Excel se genera al ejecutar:

```powershell
python -m src.notifyops_ai.modeling
```

## Como importarlo en Power BI

1. Abrir Power BI Desktop.
2. Seleccionar `Obtener datos`.
3. Elegir `Excel`.
4. Seleccionar `data/bi/notifyops_powerbi_dataset.xlsx`.
5. Cargar estas hojas:
   - `metricas_modelo`
   - `matriz_confusion`
   - `decisiones_finales`
   - `resumen_decisiones`
   - `calidad_datos`
   - `pesos_variables`
   - `rendimiento_local`
   - `auditoria_seguridad`
   - `roles_acceso`
   - `guia_powerbi`

## Graficos recomendados

- Tarjetas KPI: `accuracy`, `precision`, `recall`, `f1_score`, `roc_auc`, `gini`.
- Matriz o tabla: `matriz_confusion`.
- Barras: cantidad por `final_decision`.
- Barras horizontales: `feature` por `abs_weight`.
- Tabla de auditoria: `asset`, `sensitivity`, `risk`, `control`, `roles`.

## Defensa

La integracion BI demuestra que el pipeline mejorado no solo entrena un modelo, sino que tambien entrega resultados interpretables para una plataforma organizacional. Power BI consume el Excel como fuente de datos y permite presentar rendimiento, decisiones, riesgos, seguridad y oportunidades de mejora.
