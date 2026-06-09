import sqlite3
import unittest
from pathlib import Path

import pandas as pd

import src.notifyops.pipeline as pipeline
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

        connection = sqlite3.connect(test_db)
        try:
            event_count = connection.execute("SELECT COUNT(*) FROM validated_events").fetchone()[0]
            notification_count = connection.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
        finally:
            connection.close()

        self.assertEqual(event_count, 1)
        self.assertEqual(notification_count, 1)

    def test_generate_notifications_orders_recent_first_and_uses_readable_dates_with_milliseconds(self):
        valid = pd.DataFrame(
            [
                {
                    "event_id": "evt-old",
                    "event_type": "like",
                    "source_user_id": "u01",
                    "target_user_id": "u02",
                    "created_at": pd.Timestamp("2026-05-14 09:00:01"),
                    "content": "",
                    "notification_text": "u01 reacciono a tu publicacion",
                },
                {
                    "event_id": "evt-new",
                    "event_type": "comment",
                    "source_user_id": "u03",
                    "target_user_id": "u04",
                    "created_at": pd.Timestamp("2026-05-14 09:01:03"),
                    "content": "hola",
                    "notification_text": "u03 comento tu publicacion",
                },
            ]
        )

        notifications = generate_notifications(valid)

        self.assertEqual(notifications["event_id"].tolist(), ["evt-new", "evt-old"])
        self.assertEqual(notifications.iloc[0]["event_type"], "comment")
        self.assertEqual(notifications.iloc[0]["created_at"], "2026-05-14 09:01:03.000")
        self.assertEqual(notifications.iloc[0]["delivered_at"], "2026-05-14 09:01:05.000")
        self.assertEqual(notifications.iloc[0]["latency_seconds"], 2)

    def test_datetime_formatting_handles_invalid_dates_for_rejected_rows(self):
        self.assertEqual(pipeline.format_datetime_milliseconds(pd.NaT), "")
        self.assertEqual(pipeline.format_datetime_milliseconds(""), "")

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

    def test_serialize_for_reports_formats_mixed_created_at_values(self):
        frame = pd.DataFrame(
            [
                {"event_id": "evt-001", "created_at": pd.Timestamp("2026-05-14 09:00:31")},
                {"event_id": "evt-002", "created_at": pd.NaT},
            ]
        )

        serialized = pipeline._serialize_for_sql(frame)

        self.assertEqual(serialized.iloc[0]["created_at"], "2026-05-14 09:00:31.000")
        self.assertEqual(serialized.iloc[1]["created_at"], "")

    def test_generate_recent_event_views_orders_all_and_groups_by_type(self):
        valid = pd.DataFrame(
            [
                {
                    "event_id": "evt-001",
                    "event_type": "like",
                    "source_user_id": "u01",
                    "target_user_id": "u02",
                    "created_at": pd.Timestamp("2026-05-14 09:00:00"),
                    "content": "",
                    "notification_text": "u01 reacciono a tu publicacion",
                },
                {
                    "event_id": "evt-002",
                    "event_type": "comment",
                    "source_user_id": "u03",
                    "target_user_id": "u04",
                    "created_at": pd.Timestamp("2026-05-14 09:05:00"),
                    "content": "hola",
                    "notification_text": "u03 comento tu publicacion",
                },
                {
                    "event_id": "evt-003",
                    "event_type": "follow",
                    "source_user_id": "u05",
                    "target_user_id": "u06",
                    "created_at": pd.Timestamp("2026-05-14 09:02:00"),
                    "content": "",
                    "notification_text": "u05 comenzo a seguirte",
                },
                {
                    "event_id": "evt-004",
                    "event_type": "like",
                    "source_user_id": "u07",
                    "target_user_id": "u08",
                    "created_at": pd.Timestamp("2026-05-14 09:10:00"),
                    "content": "",
                    "notification_text": "u07 reacciono a tu publicacion",
                },
            ]
        )

        views = pipeline.generate_recent_event_views(valid)

        self.assertEqual(views["all"]["event_id"].tolist(), ["evt-004", "evt-002", "evt-003", "evt-001"])
        self.assertEqual(views["all"].iloc[0]["created_at"], "2026-05-14 09:10:00.000")
        self.assertEqual(views["like"]["event_id"].tolist(), ["evt-004", "evt-001"])
        self.assertEqual(views["comment"]["event_id"].tolist(), ["evt-002"])
        self.assertEqual(views["follow"]["event_id"].tolist(), ["evt-003"])

    def test_run_pipeline_records_measured_execution_performance(self):
        metrics = pipeline.run_pipeline()

        self.assertGreater(metrics["pipeline_execution_seconds"], 0)
        self.assertGreater(metrics["processing_rows_per_second"], 0)
        self.assertEqual(metrics["latency_measurement_type"], "simulada_para_demo")


if __name__ == "__main__":
    unittest.main()
