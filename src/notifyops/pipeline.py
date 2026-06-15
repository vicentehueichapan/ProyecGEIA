from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Dict, Iterable, Tuple

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
VALIDATED = DATA / "validated"
REPORTS = DATA / "reports"
LOGS = ROOT / "logs"
EVIDENCE = ROOT / "docs" / "evidencias"
DB_PATH = DATA / "notifyops.db"
RAW_INPUT = RAW / "social_events_200.xlsx"
RAW_SHEET = "eventos"
MINIMUM_INPUT_ROWS = 200
DISPLAY_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


@dataclass(frozen=True)
class DataQualityRules:
    allowed_event_types: Tuple[str, ...] = ("like", "comment", "follow")
    required_columns: Tuple[str, ...] = (
        "event_id",
        "event_type",
        "source_user_id",
        "target_user_id",
        "created_at",
        "content",
    )


def ensure_directories() -> None:
    for directory in [RAW, PROCESSED, VALIDATED, REPORTS, LOGS, EVIDENCE]:
        directory.mkdir(parents=True, exist_ok=True)


def configure_logging() -> None:
    ensure_directories()
    logging.basicConfig(
        filename=LOGS / "notifyops.log",
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        force=True,
    )


def ingest_events(path: Path) -> pd.DataFrame:
    logging.info("INICIO etapa 1: ingesta")
    if not path.exists():
        raise FileNotFoundError(f"No existe el dataset oficial: {path}")
    if path.suffix.lower() == ".xlsx":
        frame = pd.read_excel(path, sheet_name=RAW_SHEET, dtype=str).fillna("")
    elif path.suffix.lower() == ".csv":
        frame = pd.read_csv(path, dtype=str).fillna("")
    else:
        raise ValueError(f"Formato de entrada no soportado: {path.suffix}")
    logging.info("FIN ingesta: %s registros leidos desde %s", len(frame), path)
    return frame


def notification_text(event_type: str, source_user_id: str) -> str:
    templates = {
        "like": f"{source_user_id} reacciono a tu publicacion",
        "comment": f"{source_user_id} comento tu publicacion",
        "follow": f"{source_user_id} comenzo a seguirte",
    }
    return templates.get(event_type, "evento no soportado")


def format_datetime_milliseconds(value: pd.Timestamp) -> str:
    if pd.isna(value) or str(value).strip() == "":
        return ""
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return str(value)
    if pd.isna(timestamp):
        return ""
    return timestamp.strftime(DISPLAY_DATETIME_FORMAT)[:-3]


def clean_transform_events(raw: pd.DataFrame, rules: DataQualityRules | None = None) -> pd.DataFrame:
    logging.info("INICIO etapa 2: limpieza y transformacion")
    rules = rules or DataQualityRules()
    frame = raw.copy()
    for column in rules.required_columns:
        if column not in frame.columns:
            frame[column] = ""
        frame[column] = frame[column].astype(str).str.strip()
    frame["event_type"] = frame["event_type"].str.lower()
    frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce")
    before = len(frame)
    frame = frame.drop_duplicates(subset=["event_id"], keep="first").reset_index(drop=True)
    frame["notification_text"] = frame.apply(
        lambda row: notification_text(row["event_type"], row["source_user_id"]), axis=1
    )
    logging.info("FIN limpieza: %s registros iniciales, %s despues de deduplicar", before, len(frame))
    return frame


def _row_errors(row: pd.Series, rules: DataQualityRules) -> list[str]:
    errors: list[str] = []
    if not str(row.get("event_id", "")).strip():
        errors.append("event_id vacio")
    if row.get("event_type") not in rules.allowed_event_types:
        errors.append("tipo de evento invalido")
    if not str(row.get("source_user_id", "")).strip():
        errors.append("source_user_id vacio")
    if not str(row.get("target_user_id", "")).strip():
        errors.append("target_user_id vacio")
    if pd.isna(row.get("created_at")):
        errors.append("fecha invalida")
    return errors


def validate_events(processed: pd.DataFrame, rules: DataQualityRules | None = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    logging.info("INICIO etapa 3: validacion estructural y semantica")
    rules = rules or DataQualityRules()
    missing_columns = [column for column in rules.required_columns if column not in processed.columns]
    if missing_columns:
        raise ValueError(f"Columnas obligatorias ausentes: {', '.join(missing_columns)}")

    valid_rows = []
    rejected_rows = []
    for _, row in processed.iterrows():
        errors = _row_errors(row, rules)
        payload = row.to_dict()
        if errors:
            payload["error_reason"] = "; ".join(errors)
            rejected_rows.append(payload)
        else:
            valid_rows.append(payload)

    valid = pd.DataFrame(valid_rows)
    rejected = pd.DataFrame(rejected_rows)
    logging.info("FIN validacion: %s validos, %s rechazados", len(valid), len(rejected))
    return valid, rejected


def generate_notifications(valid: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ordered_valid = valid.sort_values("created_at", ascending=False).reset_index(drop=True)
    for index, row in ordered_valid.iterrows():
        created_at = pd.Timestamp(row["created_at"])
        delivered_at = created_at + pd.Timedelta(seconds=2 + (index % 4))
        latency_seconds = int((delivered_at - created_at).total_seconds())
        rows.append(
            {
                "notification_id": f"ntf-{row['event_id']}",
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "target_user_id": row["target_user_id"],
                "message": row["notification_text"],
                "delivery_status": "sent",
                "created_at": format_datetime_milliseconds(created_at),
                "delivered_at": format_datetime_milliseconds(delivered_at),
                "latency_seconds": latency_seconds,
            }
        )
    return pd.DataFrame(rows)


def _serialize_for_sql(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in output.columns:
        if pd.api.types.is_datetime64_any_dtype(output[column]) or column in {"created_at", "delivered_at"}:
            output[column] = output[column].apply(format_datetime_milliseconds)
    return output


def load_to_sqlite(valid: pd.DataFrame, rejected: pd.DataFrame, notifications: pd.DataFrame, db_path: Path = DB_PATH) -> None:
    logging.info("INICIO etapa 4: carga a base de datos")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    connection = sqlite3.connect(db_path)
    try:
        _serialize_for_sql(valid).to_sql("validated_events", connection, index=False, if_exists="replace")
        _serialize_for_sql(rejected).to_sql("rejected_events", connection, index=False, if_exists="replace")
        notifications.to_sql("notifications", connection, index=False, if_exists="replace")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_notifications_event ON notifications(event_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_notifications_target ON notifications(target_user_id)")
        connection.commit()
    finally:
        connection.close()
    logging.info("FIN carga: base creada en %s", db_path)


def calculate_kpis(valid: pd.DataFrame, rejected: pd.DataFrame, notifications: pd.DataFrame) -> Dict[str, object]:
    processed = len(valid) + len(rejected)
    sent = int((notifications.get("delivery_status", pd.Series(dtype=str)) == "sent").sum())
    return {
        "events_processed": int(processed),
        "valid_events": int(len(valid)),
        "rejected_events": int(len(rejected)),
        "notifications_generated": int(len(notifications)),
        "delivery_success_rate_pct": round((sent / len(notifications) * 100) if len(notifications) else 0.0, 2),
        "error_rate_pct": round((len(rejected) / processed * 100) if processed else 0.0, 2),
        "avg_latency_seconds": round(float(notifications["latency_seconds"].mean()) if len(notifications) else 0.0, 2),
        "completeness_rate_pct": round((len(valid) / processed * 100) if processed else 0.0, 2),
    }


def generate_recent_event_views(valid: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    sorted_events = valid.sort_values("created_at", ascending=False).reset_index(drop=True)
    sorted_events = _serialize_for_sql(sorted_events)
    views = {"all": sorted_events}
    for event_type in DataQualityRules().allowed_event_types:
        views[event_type] = sorted_events[sorted_events["event_type"] == event_type].reset_index(drop=True)
    return views


def write_report_artifacts(
    processed: pd.DataFrame,
    valid: pd.DataFrame,
    rejected: pd.DataFrame,
    notifications: pd.DataFrame,
    kpis: Dict[str, object],
) -> None:
    logging.info("INICIO escritura de artefactos")
    _serialize_for_sql(processed).to_csv(PROCESSED / "events_processed.csv", index=False)
    _serialize_for_sql(valid).to_csv(VALIDATED / "events_validated.csv", index=False)
    _serialize_for_sql(rejected).to_csv(REPORTS / "validation_errors.csv", index=False)
    notifications.to_csv(REPORTS / "notifications.csv", index=False)
    recent_views = generate_recent_event_views(valid)
    recent_views["all"].to_csv(REPORTS / "events_recent_all.csv", index=False)
    recent_views["like"].to_csv(REPORTS / "likes_recent.csv", index=False)
    recent_views["comment"].to_csv(REPORTS / "comments_recent.csv", index=False)
    recent_views["follow"].to_csv(REPORTS / "follows_recent.csv", index=False)
    pd.DataFrame([kpis]).to_csv(REPORTS / "kpi_report.csv", index=False)
    (REPORTS / "kpi_report.json").write_text(json.dumps(kpis, indent=2, ensure_ascii=True), encoding="utf-8")
    summary = [
        "NotifyOps - Resumen empirico de ejecucion MVP",
        f"Eventos procesados: {kpis['events_processed']}",
        f"Eventos validos: {kpis['valid_events']}",
        f"Eventos rechazados: {kpis['rejected_events']}",
        f"Notificaciones generadas: {kpis['notifications_generated']}",
        f"Tasa de entrega: {kpis['delivery_success_rate_pct']}%",
        f"Tasa de error: {kpis['error_rate_pct']}%",
        f"Completitud: {kpis['completeness_rate_pct']}%",
        f"Latencia promedio simulada: {kpis['avg_latency_seconds']} segundos",
        f"Tiempo real del pipeline: {kpis['pipeline_execution_seconds']} segundos",
        f"Rendimiento medido: {kpis['processing_rows_per_second']} filas/segundo",
    ]
    (REPORTS / "demo_summary.txt").write_text("\n".join(summary), encoding="utf-8")
    logging.info("FIN escritura de artefactos")


def _load_font(size: int):
    from PIL import ImageFont

    for font_name in ("arial.ttf", "calibri.ttf"):
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_evidence_card(filename: str, title: str, subtitle: str, lines: Iterable[str]) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1400, 850), "#f5f7fb")
    draw = ImageDraw.Draw(image)
    title_font = _load_font(56)
    subtitle_font = _load_font(34)
    body_font = _load_font(28)
    small_font = _load_font(22)
    draw.rectangle((0, 0, 1400, 130), fill="#13293d")
    draw.text((70, 38), "NotifyOps MVP", fill="white", font=subtitle_font)
    draw.rounded_rectangle((80, 190, 1320, 730), radius=22, fill="white", outline="#d8dee9", width=3)
    draw.text((130, 245), title, fill="#13293d", font=title_font)
    draw.text((130, 330), subtitle, fill="#0f766e", font=subtitle_font)
    y = 420
    for line in lines:
        draw.text((155, y), f"- {line}", fill="#243142", font=body_font)
        y += 48
    draw.text((130, 675), "Evidencia generada automaticamente desde la ejecucion del MVP", fill="#64748b", font=small_font)
    image.save(EVIDENCE / filename)


def create_evidence_images(kpis: Dict[str, object]) -> None:
    try:
        draw_evidence_card(
            "01_ejecucion_pipeline.png",
            "Pipeline ejecutado",
            f"{kpis['events_processed']} eventos procesados",
            [
                "Ingesta, limpieza, validacion y carga completadas.",
                f"{kpis['valid_events']} eventos validos.",
                f"{kpis['rejected_events']} eventos rechazados con motivo.",
            ],
        )
        draw_evidence_card(
            "02_kpis_monitoreo.png",
            "KPIs de monitoreo",
            f"{kpis['delivery_success_rate_pct']}% entrega | {kpis['avg_latency_seconds']}s latencia",
            [
                f"Tasa de error: {kpis['error_rate_pct']}%.",
                f"Completitud: {kpis['completeness_rate_pct']}%.",
                f"Notificaciones generadas: {kpis['notifications_generated']}.",
            ],
        )
        draw_evidence_card(
            "03_validacion_anomalias.png",
            "Validacion de anomalias",
            f"{kpis['rejected_events']} registros rechazados",
            [
                "Tipos de evento invalidos.",
                "Usuarios destino vacios.",
                "Fechas invalidas.",
            ],
        )
    except ImportError:
        logging.warning("Pillow no esta disponible; se omite la generacion de evidencias PNG.")


def run_pipeline(input_path: Path = RAW_INPUT) -> Dict[str, object]:
    ensure_directories()
    configure_logging()
    execution_started = perf_counter()
    logging.info("===== INICIO MVP NotifyOps =====")
    raw = ingest_events(input_path)
    if len(raw) < MINIMUM_INPUT_ROWS:
        raise ValueError(
            f"El MVP exige al menos {MINIMUM_INPUT_ROWS} registros de entrada; "
            f"se encontraron {len(raw)} en {input_path.name}."
        )
    processed = clean_transform_events(raw)
    valid, rejected = validate_events(processed)
    notifications = generate_notifications(valid)
    load_to_sqlite(valid, rejected, notifications)
    kpis = calculate_kpis(valid, rejected, notifications)
    kpis["input_rows"] = int(len(raw))
    kpis["input_file"] = input_path.name
    execution_seconds = max(perf_counter() - execution_started, 1e-9)
    kpis["pipeline_execution_seconds"] = round(execution_seconds, 6)
    kpis["processing_rows_per_second"] = round(float(kpis["events_processed"]) / execution_seconds, 2)
    kpis["latency_measurement_type"] = "simulada_para_demo"
    write_report_artifacts(processed, valid, rejected, notifications, kpis)
    create_evidence_images(kpis)
    logging.info("KPIs finales: %s", kpis)
    logging.info("===== FIN MVP NotifyOps =====")
    return kpis


def main() -> None:
    metrics = run_pipeline()
    for key, value in metrics.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
