import ast
import unittest
from pathlib import Path


class NotifyOpsAirflowDagTests(unittest.TestCase):
    def test_airflow_dag_exists_and_orchestrates_notifyops_pipeline(self):
        dag_path = Path("dags/notifyops_etl_dag.py")

        self.assertTrue(dag_path.exists(), "Debe existir el DAG complementario de Airflow")
        source = dag_path.read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("notifyops_etl_dag", source)
        self.assertIn("python -m src.notifyops.pipeline", source)
        self.assertIn("python -m src.notifyops_ai.modeling", source)
        self.assertIn("start_date=datetime(2026, 6, 9)", source)
        self.assertIn("schedule=timedelta(weeks=2)", source)
        self.assertIn("verify_input_dataset", source)
        self.assertIn("verify_etl_outputs", source)
        self.assertIn("run_ai_model", source)
        self.assertIn("verify_ai_outputs", source)
        self.assertIn("model_comparison.csv", source)
        self.assertIn("notifyops_powerbi_dataset.xlsx", source)
        self.assertIn("notifyops_ai_dashboard.html", source)

    def test_airflow_compose_uses_controlled_startup(self):
        compose_path = Path("docker-compose.airflow.yml")
        dockerfile_path = Path("Dockerfile.airflow")

        self.assertTrue(compose_path.exists(), "Debe existir docker-compose.airflow.yml")
        self.assertTrue(dockerfile_path.exists(), "Debe existir una imagen Airflow reproducible")
        source = compose_path.read_text(encoding="utf-8")
        dockerfile_source = dockerfile_path.read_text(encoding="utf-8")
        self.assertNotIn("restart: unless-stopped", source)
        self.assertNotIn("_PIP_ADDITIONAL_REQUIREMENTS", source)
        self.assertNotIn("command: standalone", source)
        self.assertIn("dockerfile: Dockerfile.airflow", source)
        self.assertIn('AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: "true"', source)
        self.assertIn("airflow users create", source)
        self.assertIn("airflow scheduler", source)
        self.assertIn("airflow webserver", source)
        self.assertIn("pip install --no-cache-dir -r /requirements.txt", dockerfile_source)


if __name__ == "__main__":
    unittest.main()
