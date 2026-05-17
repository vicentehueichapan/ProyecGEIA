from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator


PROJECT_DIR = "/opt/airflow/notifyops"


with DAG(
    dag_id="notifyops_etl_dag",
    description="Orquesta la ETL de eventos sociales NotifyOps para likes, comentarios y seguidores.",
    start_date=datetime(2026, 5, 14),
    schedule=timedelta(weeks=2),
    catchup=False,
    tags=["notifyops", "etl", "dataops", "social-network"],
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

    verify_outputs = BashOperator(
        task_id="verify_outputs",
        bash_command=(
            f"test -f {PROJECT_DIR}/data/reports/events_recent_all.csv && "
            f"test -f {PROJECT_DIR}/data/reports/likes_recent.csv && "
            f"test -f {PROJECT_DIR}/data/reports/comments_recent.csv && "
            f"test -f {PROJECT_DIR}/data/reports/follows_recent.csv && "
            f"test -f {PROJECT_DIR}/data/reports/kpi_report.csv && "
            f"test -f {PROJECT_DIR}/logs/notifyops.log"
        ),
    )

    summarize_kpis = BashOperator(
        task_id="summarize_kpis",
        bash_command=f"cat {PROJECT_DIR}/data/reports/demo_summary.txt",
    )

    finish = EmptyOperator(task_id="finish")

    start >> verify_input_dataset >> run_notifyops_pipeline >> verify_outputs >> summarize_kpis >> finish
