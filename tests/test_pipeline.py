import sqlite3
import unittest
from pathlib import Path

import pandas as pd

from src.notifyops.pipeline import (
    DataQualityRules,
    calculate_kpis,
    clean_transform_events,
    generate_notifications,
    load_to_sqlite,
    validate_events,
)


class NotifyOpsPipelineTests(unittest.TestCase):
    def test_clean_transform_normalizes_and_deduplicates_events(self):
        raw = pd.DataFrame(
            [
                {
                    "event_id": " evt-001 ",
                    "event_type": "LIKE",
                    "source_user_id": " u01 ",
                    "target_user_id": " u02 ",
                    "created_at": "2026-05-14 10:00:00",
                    "content": "",
                },
                {
                    "event_id": "evt-001",
                    "event_type": "like",
                    "source_user_id": "u01",
                    "target_user_id": "u02",
                    "created_at": "2026-05-14 10:00:00",
                    "content": "",
                },
            ]
        )

        cleaned = clean_transform_events(raw)

        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned.iloc[0]["event_id"], "evt-001")
        self.assertEqual(cleaned.iloc[0]["event_type"], "like")
        self.assertEqual(cleaned.iloc[0]["notification_text"], "u01 reacciono a tu publicacion")

    def test_validate_events_returns_valid_and_rejected_with_reasons(self):
        processed = pd.DataFrame(
            [
                {
                    "event_id": "evt-001",
                    "event_type": "comment",
                    "source_user_id": "u01",
                    "target_user_id": "u02",
                    "created_at": pd.Timestamp("2026-05-14 10:00:00"),
                    "content": "hola",
                    "notification_text": "u01 comento tu publicacion",
                },
                {
                    "event_id": "evt-002",
                    "event_type": "share",
                    "source_user_id": "u03",
                    "target_user_id": "u04",
                    "created_at": pd.Timestamp("2026-05-14 10:01:00"),
                    "content": "",
                    "notification_text": "evento no soportado",
                },
                {
                    "event_id": "evt-003",
                    "event_type": "follow",
                    "source_user_id": "u05",
                    "target_user_id": "",
                    "created_at": pd.Timestamp("2026-05-14 10:02:00"),
                    "content": "",
                    "notification_text": "u05 comenzo a seguirte",
                },
            ]
        )

        valid, rejected = validate_events(processed, DataQualityRules())

        self.assertEqual(len(valid), 1)
        self.assertEqual(len(rejected), 2)
        self.assertIn("tipo de evento invalido", " ".join(rejected["error_reason"].tolist()))
        self.assertIn("target_user_id vacio", " ".join(rejected["error_reason"].tolist()))

    def test_load_to_sqlite_persists_events_and_notifications(self):
        test_db = Path("data/reports/test_notifyops.db")
        if test_db.exists():
            test_db.unlink()
        valid = pd.DataFrame(
            [
                {
                    "event_id": "evt-001",
                    "event_type": "like",
                    "source_user_id": "u01",
                    "target_user_id": "u02",
                    "created_at": pd.Timestamp("2026-05-14 10:00:00"),
                    "content": "",
                    "notification_text": "u01 reacciono a tu publicacion",
                }
            ]
        )
        rejected = pd.DataFrame(columns=list(valid.columns) + ["error_reason"])

        notifications = generate_notifications(valid)
        load_to_sqlite(valid, rejected, notifications, test_db)

        with sqlite3.connect(test_db) as connection:
            event_count = connection.execute("SELECT COUNT(*) FROM validated_events").fetchone()[0]
            notification_count = connection.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]

        self.assertEqual(event_count, 1)
        self.assertEqual(notification_count, 1)

    def test_calculate_kpis_quantifies_mvp_execution(self):
        valid = pd.DataFrame([{"event_id": "evt-001"}, {"event_id": "evt-002"}])
        rejected = pd.DataFrame([{"event_id": "evt-003", "error_reason": "fecha invalida"}])
        notifications = pd.DataFrame(
            [
                {"delivery_status": "sent", "latency_seconds": 2.0},
                {"delivery_status": "sent", "latency_seconds": 4.0},
            ]
        )

        kpis = calculate_kpis(valid, rejected, notifications)

        self.assertEqual(kpis["events_processed"], 3)
        self.assertEqual(kpis["valid_events"], 2)
        self.assertEqual(kpis["rejected_events"], 1)
        self.assertEqual(kpis["delivery_success_rate_pct"], 100.0)
        self.assertEqual(kpis["error_rate_pct"], 33.33)
        self.assertEqual(kpis["avg_latency_seconds"], 3.0)


if __name__ == "__main__":
    unittest.main()
