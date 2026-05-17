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
        self.assertIn("schedule=timedelta(weeks=2)", source)
        self.assertIn("verify_input_dataset", source)
        self.assertIn("verify_outputs", source)

    def test_airflow_compose_uses_controlled_startup(self):
        compose_path = Path("docker-compose.airflow.yml")

        self.assertTrue(compose_path.exists(), "Debe existir docker-compose.airflow.yml")
        source = compose_path.read_text(encoding="utf-8")
        self.assertNotIn("restart: unless-stopped", source)
        self.assertNotIn("_PIP_ADDITIONAL_REQUIREMENTS", source)
        self.assertNotIn("command: standalone", source)
        self.assertIn("airflow users create", source)
        self.assertIn("airflow scheduler", source)
        self.assertIn("airflow webserver", source)


if __name__ == "__main__":
    unittest.main()
