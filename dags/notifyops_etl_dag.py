from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator


PROJECT_DIR = "/opt/airflow/notifyops"


with DAG(
    dag_id="notifyops_etl_dag",
    description="Orquesta ETL, entrenamiento IA y evidencias BI de NotifyOps.",
    start_date=datetime(2026, 6, 9),
    schedule=timedelta(weeks=2),
    catchup=False,
    tags=["notifyops", "etl", "dataops", "ai", "bi", "social-network"],
) as dag:
    start = EmptyOperator(task_id="start")

    verify_input_dataset = BashOperator(
        task_id="verify_input_dataset",
        bash_command=f"test -f {PROJECT_DIR}/data/raw/social_events.csv",
    )

    run_notifyops_pipeline = BashOperator(
        task_id="run_notifyops_pipeline",
        bash_command=f"cd {PROJECT_DIR} && python -m src.notifyops.pipeline",
    )

    verify_etl_outputs = BashOperator(
        task_id="verify_etl_outputs",
        bash_command=(
            f"test -f {PROJECT_DIR}/data/reports/events_recent_all.csv && "
            f"test -f {PROJECT_DIR}/data/reports/likes_recent.csv && "
            f"test -f {PROJECT_DIR}/data/reports/comments_recent.csv && "
            f"test -f {PROJECT_DIR}/data/reports/follows_recent.csv && "
            f"test -f {PROJECT_DIR}/data/reports/kpi_report.csv && "
            f"test -f {PROJECT_DIR}/logs/notifyops.log"
        ),
    )

    run_ai_model = BashOperator(
        task_id="run_ai_model",
        bash_command=f"cd {PROJECT_DIR} && python -m src.notifyops_ai.modeling",
    )

    verify_ai_outputs = BashOperator(
        task_id="verify_ai_outputs",
        bash_command=(
            f"test -f {PROJECT_DIR}/data/reports/ai/model_metrics.csv && "
            f"test -f {PROJECT_DIR}/data/reports/ai/model_comparison.csv && "
            f"test -f {PROJECT_DIR}/data/reports/ai/performance_summary.csv && "
            f"test -f {PROJECT_DIR}/data/reports/ai/final_event_decisions.csv && "
            f"test -f {PROJECT_DIR}/data/bi/notifyops_powerbi_dataset.xlsx && "
            f"test -f {PROJECT_DIR}/dashboard/notifyops_ai_dashboard.html && "
            f"test -f {PROJECT_DIR}/dashboard/data/dashboard_data.json"
        ),
    )

    summarize_results = BashOperator(
        task_id="summarize_results",
        bash_command=(
            f"cat {PROJECT_DIR}/data/reports/demo_summary.txt && "
            f"printf '\\n--- Modelos comparados ---\\n' && "
            f"cat {PROJECT_DIR}/data/reports/ai/model_comparison.csv"
        ),
    )

    finish = EmptyOperator(task_id="finish")

    (
        start
        >> verify_input_dataset
        >> run_notifyops_pipeline
        >> verify_etl_outputs
        >> run_ai_model
        >> verify_ai_outputs
        >> summarize_results
        >> finish
    )
