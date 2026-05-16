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
        self.assertIn("verify_input_dataset", source)
        self.assertIn("verify_outputs", source)


if __name__ == "__main__":
    unittest.main()
