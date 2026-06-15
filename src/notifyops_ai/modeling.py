from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Dict, Iterable, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
AI_DATA = DATA / "ai"
REPORTS = DATA / "reports"
AI_REPORTS = REPORTS / "ai"
BI_DATA = DATA / "bi"
CHARTS = AI_REPORTS / "charts"
DASHBOARD = ROOT / "dashboard"
MODELS = ROOT / "models"
OFFICIAL_DATASET = RAW / "social_events_200.xlsx"
OFFICIAL_SHEET = "eventos"

ALLOWED_EVENT_TYPES = ("like", "comment", "follow")
ALL_EVENT_TYPES = ("like", "comment", "follow", "share", "reaction", "unknown", "")
FEATURE_COLUMNS = [
    "content_length",
    "hour",
    "day_of_week",
    "interaction_velocity_5m",
    "account_age_days",
    "historical_report_rate",
    "is_duplicate",
    "has_source_user",
    "has_target_user",
    "has_valid_date",
    "is_allowed_event_type",
    "event_type_like",
    "event_type_comment",
    "event_type_follow",
    "event_type_invalid",
]


@dataclass(frozen=True)
class TrainResult:
    metrics: Dict[str, float]
    confusion_matrix: np.ndarray
    feature_weights: pd.DataFrame
    test_predictions: pd.DataFrame
    model_comparison: pd.DataFrame
    performance: Dict[str, float]
    selected_model: str


def ensure_directories() -> None:
    for directory in (AI_DATA, AI_REPORTS, CHARTS, DASHBOARD, MODELS):
        directory.mkdir(parents=True, exist_ok=True)


def sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -500, 500)
    return 1.0 / (1.0 + np.exp(-values))


def generate_synthetic_events(rows: int = 320, seed: int = 42) -> pd.DataFrame:
    """Create a deterministic NotifyOps dataset for binary classification.

    label_risky_event:
    - 1 means risky/rejected event.
    - 0 means valid event.
    """
    rng = np.random.default_rng(seed)
    base_time = pd.Timestamp("2026-05-14 08:00:00")
    records: list[dict[str, object]] = []
    used_event_ids: list[str] = []

    for index in range(rows):
        event_type = str(rng.choice(ALL_EVENT_TYPES, p=[0.28, 0.25, 0.22, 0.10, 0.06, 0.05, 0.04]))
        source_user_id = f"u{100 + int(rng.integers(0, 90))}"
        target_user_id = f"u{200 + int(rng.integers(0, 90))}"
        content = ""
        if event_type == "comment":
            content = str(
                rng.choice(
                    [
                        "Gran publicacion",
                        "Buen dato",
                        "Me interesa",
                        "Gracias por compartir",
                        "Hola",
                    ]
                )
            )
        elif event_type not in ALLOWED_EVENT_TYPES and rng.random() < 0.45:
            content = str(rng.choice(["evento externo", "contenido no soportado", ""]))

        interaction_velocity_5m = int(rng.integers(1, 46))
        account_age_days = int(rng.integers(1, 1501))
        historical_report_rate = round(float(rng.beta(1.5, 12.0)), 4)
        missing_source = rng.random() < 0.025
        missing_target = rng.random() < 0.12
        invalid_date = rng.random() < 0.10
        duplicate = rng.random() < 0.08 and bool(used_event_ids)

        if missing_source:
            source_user_id = ""
        if missing_target:
            target_user_id = ""

        if duplicate:
            event_id = str(rng.choice(used_event_ids))
        else:
            event_id = f"evt-ai-{index + 1:04d}"
            used_event_ids.append(event_id)

        created_at = base_time + pd.Timedelta(seconds=int(rng.integers(0, 120000)))
        created_at_value = "fecha-invalida" if invalid_date else created_at.strftime("%Y-%m-%d %H:%M:%S")
        is_allowed = event_type in ALLOWED_EVENT_TYPES
        rule_based_risk = bool((not is_allowed) or missing_source or missing_target or invalid_date or duplicate)
        historical_feedback_risk = bool(
            (not rule_based_risk)
            and (
                interaction_velocity_5m >= 34
                or historical_report_rate >= 0.22
                or (account_age_days <= 21 and historical_report_rate >= 0.10)
            )
        )
        is_risky = bool(rule_based_risk or historical_feedback_risk)

        records.append(
            {
                "event_id": event_id,
                "event_type": event_type,
                "source_user_id": source_user_id,
                "target_user_id": target_user_id,
                "created_at": created_at_value,
                "content": content,
                "interaction_velocity_5m": interaction_velocity_5m,
                "account_age_days": account_age_days,
                "historical_report_rate": historical_report_rate,
                "is_duplicate": int(duplicate),
                "historical_feedback_risk": int(historical_feedback_risk),
                "label_risky_event": int(is_risky),
            }
        )

    return pd.DataFrame(records)


def load_official_events(path: Path = OFFICIAL_DATASET) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"No existe el dataset oficial del MVP: {path}")
    events = pd.read_excel(path, sheet_name=OFFICIAL_SHEET, dtype=str).fillna("")
    required = {
        "event_id",
        "event_type",
        "source_user_id",
        "target_user_id",
        "created_at",
        "content",
        "interaction_velocity_5m",
        "account_age_days",
        "historical_report_rate",
        "is_duplicate",
        "historical_feedback_risk",
        "label_risky_event",
    }
    missing = sorted(required.difference(events.columns))
    if missing:
        raise ValueError(f"Columnas ausentes en el dataset oficial: {', '.join(missing)}")
    if len(events) < 200:
        raise ValueError(f"El dataset oficial debe contener al menos 200 filas; contiene {len(events)}.")
    return events


def engineer_features(events: pd.DataFrame) -> pd.DataFrame:
    frame = events.copy().fillna("")
    frame["event_type"] = frame["event_type"].astype(str).str.strip().str.lower()
    parsed_dates = pd.to_datetime(frame["created_at"], errors="coerce")
    frame["content_length"] = frame["content"].astype(str).str.len()
    frame["hour"] = parsed_dates.dt.hour.fillna(-1).astype(int)
    frame["day_of_week"] = parsed_dates.dt.dayofweek.fillna(-1).astype(int)
    numeric_defaults = {
        "interaction_velocity_5m": 0.0,
        "account_age_days": 0.0,
        "historical_report_rate": 0.0,
    }
    for column, default in numeric_defaults.items():
        if column not in frame.columns:
            frame[column] = default
        numeric = pd.to_numeric(frame[column], errors="coerce")
        median = float(numeric.median()) if numeric.notna().any() else default
        frame[column] = numeric.fillna(median)
    for column in ("is_duplicate", "historical_feedback_risk", "label_risky_event"):
        if column not in frame.columns:
            frame[column] = 0
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0).astype(int)
    frame["has_source_user"] = frame["source_user_id"].astype(str).str.strip().ne("").astype(int)
    frame["has_target_user"] = frame["target_user_id"].astype(str).str.strip().ne("").astype(int)
    frame["has_valid_date"] = parsed_dates.notna().astype(int)
    frame["is_allowed_event_type"] = frame["event_type"].isin(ALLOWED_EVENT_TYPES).astype(int)
    frame["event_type_like"] = frame["event_type"].eq("like").astype(int)
    frame["event_type_comment"] = frame["event_type"].eq("comment").astype(int)
    frame["event_type_follow"] = frame["event_type"].eq("follow").astype(int)
    frame["event_type_invalid"] = (~frame["event_type"].isin(ALLOWED_EVENT_TYPES)).astype(int)
    return frame


def stratified_train_test_split(
    features: pd.DataFrame,
    target: pd.Series,
    test_size: float = 0.30,
    seed: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    rng = np.random.default_rng(seed)
    train_indices: list[int] = []
    test_indices: list[int] = []
    for class_value in sorted(target.unique()):
        class_indices = target[target == class_value].index.to_numpy().copy()
        rng.shuffle(class_indices)
        test_count = max(1, int(round(len(class_indices) * test_size)))
        test_indices.extend(class_indices[:test_count].tolist())
        train_indices.extend(class_indices[test_count:].tolist())

    rng.shuffle(train_indices)
    rng.shuffle(test_indices)
    return (
        features.loc[train_indices].reset_index(drop=True),
        features.loc[test_indices].reset_index(drop=True),
        target.loc[train_indices].reset_index(drop=True),
        target.loc[test_indices].reset_index(drop=True),
    )


def standardize_train_test(x_train: pd.DataFrame, x_test: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    train = x_train.to_numpy(dtype=float)
    test = x_test.to_numpy(dtype=float)
    mean = train.mean(axis=0)
    std = train.std(axis=0)
    std[std == 0] = 1.0
    return (train - mean) / std, (test - mean) / std, mean, std


def train_logistic_regression(
    x_train: np.ndarray,
    y_train: np.ndarray,
    learning_rate: float = 0.08,
    epochs: int = 3500,
    l2: float = 0.01,
) -> np.ndarray:
    x_bias = np.column_stack([np.ones(len(x_train)), x_train])
    weights = np.zeros(x_bias.shape[1], dtype=float)
    y_values = y_train.astype(float)
    for _ in range(epochs):
        probabilities = sigmoid(x_bias @ weights)
        gradient = (x_bias.T @ (probabilities - y_values)) / len(y_values)
        gradient[1:] += l2 * weights[1:] / len(y_values)
        weights -= learning_rate * gradient
    return weights


def predict_probabilities(x_values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    x_bias = np.column_stack([np.ones(len(x_values)), x_values])
    return sigmoid(x_bias @ weights)


def confusion_counts(y_true: Iterable[int], y_pred: Iterable[int]) -> Tuple[int, int, int, int]:
    true = np.asarray(list(y_true), dtype=int)
    pred = np.asarray(list(y_pred), dtype=int)
    tn = int(((true == 0) & (pred == 0)).sum())
    fp = int(((true == 0) & (pred == 1)).sum())
    fn = int(((true == 1) & (pred == 0)).sum())
    tp = int(((true == 1) & (pred == 1)).sum())
    return tn, fp, fn, tp


def roc_curve_values(y_true: Iterable[int], probabilities: Iterable[float]) -> Tuple[np.ndarray, np.ndarray, float]:
    true = np.asarray(list(y_true), dtype=int)
    scores = np.asarray(list(probabilities), dtype=float)
    thresholds = np.r_[np.inf, np.sort(np.unique(scores))[::-1], -np.inf]
    tpr_values: list[float] = []
    fpr_values: list[float] = []
    positives = max(1, int((true == 1).sum()))
    negatives = max(1, int((true == 0).sum()))
    for threshold in thresholds:
        pred = (scores >= threshold).astype(int)
        tn, fp, fn, tp = confusion_counts(true, pred)
        tpr_values.append(tp / positives)
        fpr_values.append(fp / negatives)
    fpr = np.asarray(fpr_values)
    tpr = np.asarray(tpr_values)
    order = np.argsort(fpr)
    integrate = getattr(np, "trapezoid", None)
    if integrate is None:
        integrate = np.trapz
    auc = float(integrate(tpr[order], fpr[order]))
    return fpr[order], tpr[order], auc


def classification_metrics(y_true: pd.Series, probabilities: np.ndarray, threshold: float = 0.50) -> Tuple[Dict[str, float], np.ndarray]:
    y_pred = (probabilities >= threshold).astype(int)
    tn, fp, fn, tp = confusion_counts(y_true, y_pred)
    total = max(1, tn + fp + fn + tp)
    accuracy = (tn + tp) / total
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    _, _, auc = roc_curve_values(y_true, probabilities)
    gini = 2 * auc - 1
    metrics = {
        "accuracy": round(float(accuracy), 4),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1_score": round(float(f1), 4),
        "roc_auc": round(float(auc), 4),
        "gini": round(float(gini), 4),
        "threshold": threshold,
        "true_negatives_valid_detected": tn,
        "false_positives_valid_marked_risky": fp,
        "false_negatives_risky_marked_valid": fn,
        "true_positives_risky_detected": tp,
    }
    return metrics, np.asarray([[tn, fp], [fn, tp]], dtype=int)


def model_evaluation_row(
    model_name: str,
    y_true: pd.Series,
    probabilities: np.ndarray,
    training_seconds: float,
    inference_seconds: float,
) -> Tuple[dict[str, float | str], np.ndarray]:
    metrics, matrix = classification_metrics(y_true, probabilities)
    row: dict[str, float | str] = {
        "model": model_name,
        **metrics,
        "training_seconds": round(max(training_seconds, 1e-9), 6),
        "inference_seconds": round(max(inference_seconds, 1e-9), 6),
    }
    return row, matrix


def quality_summary(events: pd.DataFrame) -> pd.DataFrame:
    engineered = engineer_features(events)
    summary = [
        {"indicator": "rows", "value": len(engineered)},
        {"indicator": "missing_source_user", "value": int((engineered["has_source_user"] == 0).sum())},
        {"indicator": "missing_target_user", "value": int((engineered["has_target_user"] == 0).sum())},
        {"indicator": "invalid_dates", "value": int((engineered["has_valid_date"] == 0).sum())},
        {"indicator": "duplicate_events", "value": int(engineered["is_duplicate"].sum())},
        {"indicator": "invalid_event_types", "value": int((engineered["is_allowed_event_type"] == 0).sum())},
        {"indicator": "valid_events", "value": int((engineered["label_risky_event"] == 0).sum())},
        {"indicator": "risky_events", "value": int((engineered["label_risky_event"] == 1).sum())},
    ]
    for column in [
        "content_length",
        "interaction_velocity_5m",
        "account_age_days",
        "historical_report_rate",
    ]:
        values = pd.to_numeric(engineered[column], errors="coerce")
        mode = values.mode()
        summary.extend(
            [
                {"indicator": f"{column}_mean", "value": round(float(values.mean()), 4)},
                {"indicator": f"{column}_median", "value": round(float(values.median()), 4)},
                {
                    "indicator": f"{column}_mode",
                    "value": round(float(mode.iloc[0]), 4) if not mode.empty else 0.0,
                },
                {"indicator": f"{column}_p25", "value": round(float(values.quantile(0.25)), 4)},
                {"indicator": f"{column}_p75", "value": round(float(values.quantile(0.75)), 4)},
            ]
        )
    summary.append(
        {
            "indicator": "imputation_strategy",
            "value": "mediana para senales numericas; indicadores explicitos para nulos estructurales",
        }
    )
    return pd.DataFrame(summary)


def save_bar_chart(values: pd.Series, title: str, output: Path, color: str = "#2563eb") -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    values.plot(kind="bar", ax=ax, color=color)
    ax.set_title(title)
    ax.set_xlabel("")
    ax.set_ylabel("Cantidad")
    fig.tight_layout()
    fig.savefig(output, dpi=160)
    plt.close(fig)


def save_confusion_matrix_chart(matrix: np.ndarray, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 5))
    image = ax.imshow(matrix, cmap="Blues")
    ax.set_title("Matriz de confusion - evento valido vs riesgoso")
    ax.set_xticks([0, 1], labels=["Pred valido", "Pred riesgoso"])
    ax.set_yticks([0, 1], labels=["Real valido", "Real riesgoso"])
    for row in range(matrix.shape[0]):
        for col in range(matrix.shape[1]):
            ax.text(col, row, str(matrix[row, col]), ha="center", va="center", color="#111827")
    fig.colorbar(image, ax=ax)
    fig.tight_layout()
    fig.savefig(output, dpi=160)
    plt.close(fig)


def save_roc_chart(y_true: pd.Series, probabilities: np.ndarray, output: Path) -> None:
    fpr, tpr, auc = roc_curve_values(y_true, probabilities)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(fpr, tpr, label=f"ROC-AUC = {auc:.3f}", color="#0f766e", linewidth=2)
    ax.plot([0, 1], [0, 1], linestyle="--", color="#9ca3af")
    ax.set_title("Curva ROC - deteccion de eventos riesgosos")
    ax.set_xlabel("Tasa de falsos positivos")
    ax.set_ylabel("Tasa de verdaderos positivos")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=160)
    plt.close(fig)


def save_feature_weights_chart(feature_weights: pd.DataFrame, output: Path) -> None:
    top = feature_weights.reindex(feature_weights["abs_weight"].sort_values(ascending=False).index).head(10)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(top["feature"], top["weight"], color=["#dc2626" if v > 0 else "#2563eb" for v in top["weight"]])
    ax.invert_yaxis()
    ax.set_title("Peso de variables en el filtro inteligente")
    ax.set_xlabel("Peso del modelo")
    fig.tight_layout()
    fig.savefig(output, dpi=160)
    plt.close(fig)


def save_model_comparison_chart(model_comparison: pd.DataFrame, output: Path) -> None:
    metrics = ["accuracy", "precision", "recall", "f1_score", "roc_auc"]
    positions = np.arange(len(model_comparison))
    width = 0.15
    fig, ax = plt.subplots(figsize=(11, 6))
    for index, metric in enumerate(metrics):
        ax.bar(
            positions + (index - 2) * width,
            model_comparison[metric],
            width=width,
            label=metric,
        )
    ax.set_xticks(positions, labels=model_comparison["model"], rotation=12)
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Resultado")
    ax.set_title("Comparacion de modelos con la misma particion")
    ax.legend(ncol=3)
    fig.tight_layout()
    fig.savefig(output, dpi=160)
    plt.close(fig)


def save_runtime_comparison_chart(model_comparison: pd.DataFrame, output: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    axes[0].bar(
        model_comparison["model"],
        model_comparison["training_seconds"] * 1000,
        color="#2d6aa3",
    )
    axes[0].set_title("Tiempo de entrenamiento")
    axes[0].set_ylabel("Milisegundos medidos")
    axes[0].tick_params(axis="x", rotation=15)
    axes[1].bar(
        model_comparison["model"],
        model_comparison["inference_seconds"] * 1000,
        color="#087f73",
    )
    axes[1].set_title("Tiempo de inferencia")
    axes[1].set_ylabel("Milisegundos medidos")
    axes[1].tick_params(axis="x", rotation=15)
    fig.suptitle("Rendimiento local por modelo")
    fig.tight_layout()
    fig.savefig(output, dpi=160)
    plt.close(fig)


def save_correlation_chart(feature_frame: pd.DataFrame, output: Path) -> None:
    corr = feature_frame[FEATURE_COLUMNS + ["label_risky_event"]].corr(numeric_only=True)
    fig, ax = plt.subplots(figsize=(9, 8))
    image = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_title("Matriz de correlacion de variables")
    ax.set_xticks(range(len(corr.columns)), labels=corr.columns, rotation=90)
    ax.set_yticks(range(len(corr.index)), labels=corr.index)
    fig.colorbar(image, ax=ax, shrink=0.75)
    fig.tight_layout()
    fig.savefig(output, dpi=160)
    plt.close(fig)


def save_dashboard_html(
    metrics: Dict[str, float],
    model_comparison: pd.DataFrame,
    quality: pd.DataFrame,
    final_decisions: pd.DataFrame,
    performance: Dict[str, float],
    selected_model: str,
) -> None:
    from src.notifyops_ai.bi_dataset import _roles, _security_audit

    dashboard_data_dir = DASHBOARD / "data"
    dashboard_data_dir.mkdir(parents=True, exist_ok=True)
    decision_rows = final_decisions[
        ["event_id", "event_type", "created_at", "ai_risk_probability", "ai_prediction", "final_decision"]
    ].copy()
    payload = {
        "metrics": metrics,
        "selected_model": selected_model,
        "model_comparison": model_comparison.to_dict(orient="records"),
        "quality": quality.to_dict(orient="records"),
        "performance": performance,
        "decisions": decision_rows.to_dict(orient="records"),
        "security": _security_audit().to_dict(orient="records"),
        "roles": _roles().to_dict(orient="records"),
    }
    serialized_payload = json.dumps(payload, ensure_ascii=True)
    (dashboard_data_dir / "dashboard_data.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )

    html = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NotifyOps | Panel Parcial 3</title>
  <style>
    :root {
      --ink: #162331;
      --muted: #637181;
      --line: #d9e0e7;
      --panel: #ffffff;
      --surface: #f4f6f8;
      --navy: #17324d;
      --teal: #087f73;
      --amber: #bf6b00;
      --red: #b43c3c;
      --blue: #2d6aa3;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Arial, Calibri, sans-serif;
      color: var(--ink);
      background: var(--surface);
    }
    header {
      background: var(--navy);
      color: #fff;
      padding: 18px 28px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
    }
    header h1 { margin: 0; font-size: 23px; letter-spacing: 0; }
    header p { margin: 5px 0 0; color: #c9d7e4; font-size: 13px; }
    .status {
      border: 1px solid #7190aa;
      padding: 8px 11px;
      border-radius: 4px;
      font-size: 12px;
      white-space: nowrap;
    }
    main { max-width: 1440px; margin: 0 auto; padding: 22px 26px 42px; }
    .toolbar {
      display: grid;
      grid-template-columns: minmax(150px, 1fr) minmax(180px, 1fr) auto;
      gap: 12px;
      align-items: end;
      margin-bottom: 18px;
    }
    label { display: block; color: var(--muted); font-size: 12px; font-weight: 700; margin-bottom: 5px; }
    select, button {
      width: 100%;
      min-height: 38px;
      border: 1px solid #b9c5cf;
      border-radius: 4px;
      background: #fff;
      color: var(--ink);
      padding: 8px 10px;
      font-size: 14px;
    }
    button { width: auto; cursor: pointer; font-weight: 700; }
    button:hover { border-color: var(--blue); }
    .tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--line); margin-bottom: 18px; }
    .tab {
      border: 0;
      border-bottom: 3px solid transparent;
      border-radius: 0;
      background: transparent;
      padding: 11px 15px;
    }
    .tab.active { color: var(--blue); border-bottom-color: var(--blue); }
    .view { display: none; }
    .view.active { display: block; }
    .kpis {
      display: grid;
      grid-template-columns: repeat(6, minmax(125px, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }
    .kpi, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
    }
    .kpi { padding: 14px; min-height: 98px; }
    .kpi .label { color: var(--muted); font-size: 12px; font-weight: 700; }
    .kpi .value { font-size: 26px; font-weight: 700; margin-top: 8px; color: var(--navy); }
    .kpi .detail { color: var(--muted); font-size: 11px; margin-top: 5px; }
    .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .grid-3 { display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 14px; }
    .panel { padding: 15px; min-width: 0; }
    .panel h2 { font-size: 15px; margin: 0 0 12px; }
    canvas { width: 100%; height: 280px; display: block; }
    .table-wrap { overflow: auto; max-height: 420px; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th {
      position: sticky;
      top: 0;
      background: #e8eef3;
      color: var(--navy);
      text-align: left;
      padding: 9px;
      border-bottom: 1px solid #b9c5cf;
      white-space: nowrap;
    }
    td { padding: 8px 9px; border-bottom: 1px solid #e5e9ed; vertical-align: top; }
    .pill { display: inline-block; padding: 3px 6px; border-radius: 3px; font-weight: 700; font-size: 10px; }
    .approved { color: #065f55; background: #d9f4ee; }
    .review { color: #8a4d00; background: #fff0d3; }
    .rejected { color: #912f2f; background: #f9dddd; }
    .metric-note { margin: 0 0 14px; color: var(--muted); font-size: 12px; }
    .empty { color: var(--muted); padding: 22px 4px; text-align: center; }
    footer { color: var(--muted); font-size: 11px; margin-top: 18px; }
    @media (max-width: 1050px) {
      .kpis { grid-template-columns: repeat(3, minmax(125px, 1fr)); }
      .grid-3 { grid-template-columns: 1fr; }
    }
    @media (max-width: 720px) {
      header { align-items: flex-start; flex-direction: column; padding: 16px; }
      header h1 { font-size: 20px; }
      .status { width: 100%; white-space: normal; }
      main { padding: 15px; }
      .toolbar, .grid-2 { grid-template-columns: 1fr; }
      .kpis { grid-template-columns: repeat(2, minmax(110px, 1fr)); }
      .tabs { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .tab { min-width: 0; padding: 9px 4px; font-size: 11px; white-space: normal; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>NotifyOps | Panel de Evidencia Parcial 3</h1>
      <p>Calidad, modelos, decisiones operacionales, rendimiento y seguridad</p>
    </div>
    <div class="status" id="modelStatus">Cargando modelo</div>
  </header>
  <main>
    <section class="toolbar">
      <div>
        <label for="eventTypeFilter">Tipo de evento</label>
        <select id="eventTypeFilter"><option value="">Todos</option></select>
      </div>
      <div>
        <label for="decisionFilter">Decision final</label>
        <select id="decisionFilter"><option value="">Todas</option></select>
      </div>
      <button id="resetFilters" type="button">Restablecer filtros</button>
    </section>

    <nav class="tabs" aria-label="Vistas del panel">
      <button class="tab active" data-view="summaryView" type="button">Resumen ejecutivo</button>
      <button class="tab" data-view="modelView" type="button">Modelo y calidad</button>
      <button class="tab" data-view="securityView" type="button">Seguridad y operacion</button>
    </nav>

    <section id="summaryView" class="view active">
      <div class="kpis" id="kpiGrid"></div>
      <div class="grid-2">
        <article class="panel">
          <h2>Decisiones finales</h2>
          <canvas id="decisionChart"></canvas>
        </article>
        <article class="panel">
          <h2>Eventos por tipo</h2>
          <canvas id="eventTypeChart"></canvas>
        </article>
      </div>
      <article class="panel" style="margin-top:14px">
        <h2>Detalle operacional sin datos personales</h2>
        <div class="table-wrap"><table id="decisionTable"></table></div>
      </article>
    </section>

    <section id="modelView" class="view">
      <p class="metric-note">Los modelos usan la misma particion estratificada. La seleccion prioriza F1 y conserva interpretabilidad cuando la diferencia es menor o igual a 0,03.</p>
      <div class="grid-2">
        <article class="panel">
          <h2>Comparacion de F1 y ROC-AUC</h2>
          <canvas id="modelChart"></canvas>
        </article>
        <article class="panel">
          <h2>Calidad de datos</h2>
          <canvas id="qualityChart"></canvas>
        </article>
      </div>
      <article class="panel" style="margin-top:14px">
        <h2>Comparacion numerica</h2>
        <div class="table-wrap"><table id="modelTable"></table></div>
      </article>
    </section>

    <section id="securityView" class="view">
      <div class="grid-3">
        <article class="panel">
          <h2>Rendimiento medido</h2>
          <div id="performanceTable"></div>
        </article>
        <article class="panel">
          <h2>Roles de acceso</h2>
          <div class="table-wrap"><table id="rolesTable"></table></div>
        </article>
        <article class="panel">
          <h2>Controles aplicados</h2>
          <div class="table-wrap"><table id="securityTable"></table></div>
        </article>
      </div>
    </section>
    <footer>Dataset BI generado desde la misma ejecucion del pipeline. Identificadores personales excluidos de este panel.</footer>
  </main>

  <script id="dashboardData" type="application/json">__INLINE_DATA__</script>
  <script>
    const DATA_FILE = "data/dashboard_data.json";
    const inlineData = JSON.parse(document.getElementById("dashboardData").textContent);
    let dashboardData = inlineData;
    let filteredDecisions = [];

    const colors = ["#2d6aa3", "#087f73", "#bf6b00", "#b43c3c", "#6c7a89"];
    const formatPercent = value => `${(Number(value) * 100).toFixed(2)}%`;
    const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
    })[character]);

    function groupCount(rows, field) {
      return rows.reduce((accumulator, row) => {
        const key = row[field] || "sin_valor";
        accumulator[key] = (accumulator[key] || 0) + 1;
        return accumulator;
      }, {});
    }

    function setupFilters() {
      const eventTypes = [...new Set(dashboardData.decisions.map(row => row.event_type || "sin_tipo"))].sort();
      const decisions = [...new Set(dashboardData.decisions.map(row => row.final_decision))].sort();
      const eventSelect = document.getElementById("eventTypeFilter");
      const decisionSelect = document.getElementById("decisionFilter");
      eventTypes.forEach(value => eventSelect.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`));
      decisions.forEach(value => decisionSelect.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`));
      eventSelect.addEventListener("change", applyFilters);
      decisionSelect.addEventListener("change", applyFilters);
      document.getElementById("resetFilters").addEventListener("click", () => {
        eventSelect.value = "";
        decisionSelect.value = "";
        applyFilters();
      });
    }

    function applyFilters() {
      const eventType = document.getElementById("eventTypeFilter").value;
      const decision = document.getElementById("decisionFilter").value;
      filteredDecisions = dashboardData.decisions.filter(row =>
        (!eventType || (row.event_type || "sin_tipo") === eventType) &&
        (!decision || row.final_decision === decision)
      );
      renderSummary();
    }

    function renderKpis() {
      const metricCards = [
        ["Accuracy", formatPercent(dashboardData.metrics.accuracy), "aciertos totales"],
        ["Precision", formatPercent(dashboardData.metrics.precision), "riesgos predichos correctos"],
        ["Recall", formatPercent(dashboardData.metrics.recall), "riesgos detectados"],
        ["F1-score", formatPercent(dashboardData.metrics.f1_score), "equilibrio precision/recall"],
        ["ROC-AUC", formatPercent(dashboardData.metrics.roc_auc), "capacidad de separacion"],
        ["Gini", Number(dashboardData.metrics.gini).toFixed(4), "2 x AUC - 1"],
      ];
      document.getElementById("kpiGrid").innerHTML = metricCards.map(([label, value, detail]) =>
        `<article class="kpi"><div class="label">${label}</div><div class="value">${value}</div><div class="detail">${detail}</div></article>`
      ).join("");
    }

    function resizeCanvas(canvas) {
      const ratio = window.devicePixelRatio || 1;
      const width = Math.max(canvas.clientWidth, 280);
      const height = Math.max(canvas.clientHeight, 240);
      canvas.width = width * ratio;
      canvas.height = height * ratio;
      const context = canvas.getContext("2d");
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      return { context, width, height };
    }

    function drawBars(canvasId, entries, valueFormatter = value => value) {
      const canvas = document.getElementById(canvasId);
      const { context, width, height } = resizeCanvas(canvas);
      context.clearRect(0, 0, width, height);
      if (!entries.length) return;
      const margin = { top: 20, right: 16, bottom: 72, left: 48 };
      const chartWidth = width - margin.left - margin.right;
      const chartHeight = height - margin.top - margin.bottom;
      const maximum = Math.max(...entries.map(entry => Number(entry.value)), 1);
      const slot = chartWidth / entries.length;
      context.strokeStyle = "#c7d1da";
      context.beginPath();
      context.moveTo(margin.left, margin.top);
      context.lineTo(margin.left, margin.top + chartHeight);
      context.lineTo(margin.left + chartWidth, margin.top + chartHeight);
      context.stroke();
      entries.forEach((entry, index) => {
        const barWidth = Math.min(slot * 0.62, 72);
        const barHeight = chartHeight * Number(entry.value) / maximum;
        const x = margin.left + slot * index + (slot - barWidth) / 2;
        const y = margin.top + chartHeight - barHeight;
        context.fillStyle = entry.color || colors[index % colors.length];
        context.fillRect(x, y, barWidth, barHeight);
        context.fillStyle = "#162331";
        context.font = "12px Arial";
        context.textAlign = "center";
        context.fillText(valueFormatter(entry.value), x + barWidth / 2, Math.max(y - 6, 12));
        context.save();
        context.translate(x + barWidth / 2, margin.top + chartHeight + 12);
        context.rotate(-0.45);
        context.textAlign = "right";
        context.fillText(entry.label, 0, 0);
        context.restore();
      });
    }

    function decisionPill(value) {
      const className = value === "aprobado_para_notificar" ? "approved" :
        value === "revision_por_ia" ? "review" : "rejected";
      return `<span class="pill ${className}">${escapeHtml(value)}</span>`;
    }

    function renderDecisionTable() {
      const table = document.getElementById("decisionTable");
      if (!filteredDecisions.length) {
        table.innerHTML = '<tbody><tr><td class="empty">No existen eventos para los filtros seleccionados.</td></tr></tbody>';
        return;
      }
      table.innerHTML = `<thead><tr>
        <th>Evento</th><th>Tipo</th><th>Fecha</th><th>Riesgo IA</th><th>Prediccion</th><th>Decision</th>
      </tr></thead><tbody>${filteredDecisions.slice(0, 200).map(row => `<tr>
        <td>${escapeHtml(row.event_id)}</td>
        <td>${escapeHtml(row.event_type || "sin_tipo")}</td>
        <td>${escapeHtml(row.created_at)}</td>
        <td>${formatPercent(row.ai_risk_probability)}</td>
        <td>${escapeHtml(row.ai_prediction)}</td>
        <td>${decisionPill(row.final_decision)}</td>
      </tr>`).join("")}</tbody>`;
    }

    function renderSummary() {
      drawBars("decisionChart", Object.entries(groupCount(filteredDecisions, "final_decision")).map(([label, value], index) => ({ label, value, color: colors[index] })));
      drawBars("eventTypeChart", Object.entries(groupCount(filteredDecisions, "event_type")).map(([label, value], index) => ({ label, value, color: colors[index] })));
      renderDecisionTable();
    }

    function renderModelView() {
      const modelEntries = dashboardData.model_comparison.flatMap((row, index) => [
        { label: `${row.model} F1`, value: row.f1_score, color: colors[index] },
        { label: `${row.model} AUC`, value: row.roc_auc, color: "#087f73" },
      ]);
      drawBars("modelChart", modelEntries, value => Number(value).toFixed(3));
      const qualityIndicators = ["missing_source_user", "missing_target_user", "invalid_dates", "duplicate_events", "invalid_event_types"];
      const qualityEntries = dashboardData.quality
        .filter(row => qualityIndicators.includes(row.indicator))
        .map((row, index) => ({ label: row.indicator, value: Number(row.value), color: colors[index] }));
      drawBars("qualityChart", qualityEntries);
      document.getElementById("modelTable").innerHTML = `<thead><tr>
        <th>Modelo</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1</th><th>ROC-AUC</th><th>Gini</th><th>Seleccionado</th>
      </tr></thead><tbody>${dashboardData.model_comparison.map(row => `<tr>
        <td>${escapeHtml(row.model)}</td><td>${formatPercent(row.accuracy)}</td>
        <td>${formatPercent(row.precision)}</td><td>${formatPercent(row.recall)}</td>
        <td>${formatPercent(row.f1_score)}</td><td>${formatPercent(row.roc_auc)}</td>
        <td>${Number(row.gini).toFixed(4)}</td><td>${row.selected ? "Si" : "No"}</td>
      </tr>`).join("")}</tbody>`;
    }

    function simpleTable(elementId, rows, columns) {
      const element = document.getElementById(elementId);
      element.innerHTML = `<thead><tr>${columns.map(column => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr></thead>
        <tbody>${rows.map(row => `<tr>${columns.map(column => `<td>${escapeHtml(row[column.key])}</td>`).join("")}</tr>`).join("")}</tbody>`;
    }

    function renderSecurityView() {
      document.getElementById("performanceTable").innerHTML = `<table><tbody>
        <tr><th>Entrenamiento</th><td>${Number(dashboardData.performance.training_seconds).toFixed(6)} s</td></tr>
        <tr><th>Inferencia</th><td>${Number(dashboardData.performance.inference_seconds).toFixed(6)} s</td></tr>
        <tr><th>Filas de prueba</th><td>${dashboardData.performance.inference_rows}</td></tr>
        <tr><th>Filas por segundo</th><td>${Number(dashboardData.performance.inference_rows_per_second).toLocaleString("es-CL")}</td></tr>
      </tbody></table>`;
      simpleTable("rolesTable", dashboardData.roles, [
        { key: "role", label: "Rol" }, { key: "allowed_access", label: "Acceso" }, { key: "restriction", label: "Restriccion" },
      ]);
      simpleTable("securityTable", dashboardData.security, [
        { key: "asset", label: "Activo" }, { key: "sensitivity", label: "Sensibilidad" }, { key: "implemented_control", label: "Control aplicado" },
      ]);
    }

    function setupTabs() {
      document.querySelectorAll(".tab").forEach(button => button.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(tab => tab.classList.remove("active"));
        document.querySelectorAll(".view").forEach(view => view.classList.remove("active"));
        button.classList.add("active");
        document.getElementById(button.dataset.view).classList.add("active");
        if (button.dataset.view === "modelView") renderModelView();
      }));
    }

    function initialize() {
      document.getElementById("modelStatus").textContent = `Modelo seleccionado: ${dashboardData.selected_model}`;
      filteredDecisions = [...dashboardData.decisions];
      renderKpis();
      setupFilters();
      setupTabs();
      renderSummary();
      renderModelView();
      renderSecurityView();
    }

    fetch(DATA_FILE)
      .then(response => response.ok ? response.json() : Promise.reject(new Error("Archivo no disponible")))
      .then(data => { dashboardData = data; initialize(); })
      .catch(() => initialize());

    window.addEventListener("resize", () => {
      renderSummary();
      if (document.getElementById("modelView").classList.contains("active")) renderModelView();
    });
  </script>
</body>
</html>
""".replace("__INLINE_DATA__", serialized_payload)
    (DASHBOARD / "notifyops_ai_dashboard.html").write_text(html, encoding="utf-8")


def predict_new_events(
    weights: np.ndarray,
    mean: np.ndarray,
    std: np.ndarray,
    threshold: float = 0.50,
) -> pd.DataFrame:
    events = pd.DataFrame(
        [
            {
                "event_id": "new-001",
                "event_type": "like",
                "source_user_id": "u150",
                "target_user_id": "u250",
                "created_at": "2026-05-20 10:15:00",
                "content": "",
                "is_duplicate": 0,
                "expected_explanation": "Evento permitido, con usuario destino y fecha valida.",
            },
            {
                "event_id": "new-002",
                "event_type": "share",
                "source_user_id": "u151",
                "target_user_id": "u251",
                "created_at": "2026-05-20 10:16:00",
                "content": "evento externo",
                "is_duplicate": 0,
                "expected_explanation": "Tipo de evento fuera del alcance del caso.",
            },
            {
                "event_id": "new-003",
                "event_type": "comment",
                "source_user_id": "u152",
                "target_user_id": "",
                "created_at": "2026-05-20 10:17:00",
                "content": "Hola",
                "is_duplicate": 0,
                "expected_explanation": "Falta target_user_id; no se sabe a quien notificar.",
            },
            {
                "event_id": "new-004",
                "event_type": "follow",
                "source_user_id": "u153",
                "target_user_id": "u253",
                "created_at": "fecha-invalida",
                "content": "",
                "is_duplicate": 0,
                "expected_explanation": "Fecha invalida; no permite trazabilidad ni latencia.",
            },
        ]
    )
    engineered = engineer_features(events)
    x_new = engineered[FEATURE_COLUMNS].to_numpy(dtype=float)
    x_scaled = (x_new - mean) / std
    probabilities = predict_probabilities(x_scaled, weights)
    output = events.copy()
    output["risk_probability"] = np.round(probabilities, 4)
    output["prediction"] = np.where(probabilities >= threshold, "riesgoso", "valido")
    return output


def rule_error_reason(row: pd.Series) -> str:
    errors: list[str] = []
    event_type = str(row.get("event_type", "")).strip().lower()
    if not str(row.get("event_id", "")).strip():
        errors.append("event_id vacio")
    if event_type not in ALLOWED_EVENT_TYPES:
        errors.append("tipo de evento fuera del alcance")
    if not str(row.get("source_user_id", "")).strip():
        errors.append("source_user_id vacio")
    if not str(row.get("target_user_id", "")).strip():
        errors.append("target_user_id vacio")
    if pd.isna(pd.to_datetime(row.get("created_at", ""), errors="coerce")):
        errors.append("fecha invalida")
    if int(row.get("is_duplicate", 0)) == 1:
        errors.append("evento duplicado")
    return "; ".join(errors)


def build_final_decisions(
    events: pd.DataFrame,
    weights: np.ndarray,
    mean: np.ndarray,
    std: np.ndarray,
    threshold: float = 0.50,
) -> pd.DataFrame:
    engineered = engineer_features(events)
    x_values = engineered[FEATURE_COLUMNS].to_numpy(dtype=float)
    x_scaled = (x_values - mean) / std
    probabilities = predict_probabilities(x_scaled, weights)
    return build_final_decisions_from_probabilities(events, probabilities, threshold)


def build_final_decisions_from_probabilities(
    events: pd.DataFrame,
    probabilities: np.ndarray,
    threshold: float = 0.50,
) -> pd.DataFrame:
    decisions = events.copy()
    decisions["rule_error_reason"] = decisions.apply(rule_error_reason, axis=1)
    decisions["ai_risk_probability"] = np.round(probabilities, 4)
    decisions["ai_prediction"] = np.where(probabilities >= threshold, "riesgoso", "valido")
    decisions["final_decision"] = np.where(
        decisions["rule_error_reason"].ne(""),
        "rechazado_por_reglas",
        np.where(decisions["ai_risk_probability"] >= threshold, "revision_por_ia", "aprobado_para_notificar"),
    )
    decisions["decision_explanation"] = np.where(
        decisions["final_decision"].eq("rechazado_por_reglas"),
        "No pasa reglas duras del pipeline: " + decisions["rule_error_reason"],
        np.where(
            decisions["final_decision"].eq("revision_por_ia"),
            "Pasa reglas duras, pero el modelo IA estima riesgo alto.",
            "Pasa reglas duras y el modelo IA estima riesgo bajo.",
        ),
    )
    return decisions[
        [
            "event_id",
            "event_type",
            "source_user_id",
            "target_user_id",
            "created_at",
            "is_duplicate",
            "rule_error_reason",
            "ai_risk_probability",
            "ai_prediction",
            "final_decision",
            "decision_explanation",
        ]
    ]


def run_ai_pipeline(
    rows: int | None = None,
    seed: int = 42,
    save_plots: bool = True,
    write_outputs: bool = True,
) -> TrainResult:
    ensure_directories()
    if rows is None:
        events = load_official_events()
        dataset_source = OFFICIAL_DATASET.name
    else:
        events = generate_synthetic_events(rows=rows, seed=seed)
        dataset_source = "synthetic_generator"
    engineered = engineer_features(events)
    features = engineered[FEATURE_COLUMNS]
    target = engineered["label_risky_event"].astype(int)
    x_train, x_test, y_train, y_test = stratified_train_test_split(features, target, seed=seed)
    x_train_scaled, x_test_scaled, mean, std = standardize_train_test(x_train, x_test)

    comparison_rows: list[dict[str, float | str]] = []
    matrices: dict[str, np.ndarray] = {}
    candidate_probabilities: dict[str, np.ndarray] = {}

    baseline_started = perf_counter()
    baseline_probability = float(y_train.mean())
    baseline_training_seconds = perf_counter() - baseline_started
    baseline_inference_started = perf_counter()
    baseline_probabilities = np.full(len(y_test), baseline_probability, dtype=float)
    baseline_inference_seconds = perf_counter() - baseline_inference_started
    baseline_row, baseline_matrix = model_evaluation_row(
        "baseline_clase_mayoritaria",
        y_test,
        baseline_probabilities,
        baseline_training_seconds,
        baseline_inference_seconds,
    )
    comparison_rows.append(baseline_row)
    matrices["baseline_clase_mayoritaria"] = baseline_matrix
    candidate_probabilities["baseline_clase_mayoritaria"] = baseline_probabilities

    logistic_training_started = perf_counter()
    weights = train_logistic_regression(x_train_scaled, y_train.to_numpy(dtype=int))
    logistic_training_seconds = perf_counter() - logistic_training_started
    logistic_inference_started = perf_counter()
    logistic_probabilities = predict_probabilities(x_test_scaled, weights)
    logistic_inference_seconds = perf_counter() - logistic_inference_started
    logistic_row, logistic_matrix = model_evaluation_row(
        "regresion_logistica",
        y_test,
        logistic_probabilities,
        logistic_training_seconds,
        logistic_inference_seconds,
    )
    comparison_rows.append(logistic_row)
    matrices["regresion_logistica"] = logistic_matrix
    candidate_probabilities["regresion_logistica"] = logistic_probabilities

    forest = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        min_samples_leaf=3,
        random_state=seed,
        n_jobs=1,
    )
    forest_training_started = perf_counter()
    forest.fit(x_train.to_numpy(dtype=float), y_train.to_numpy(dtype=int))
    forest_training_seconds = perf_counter() - forest_training_started
    forest_inference_started = perf_counter()
    forest_probabilities = forest.predict_proba(x_test.to_numpy(dtype=float))[:, 1]
    forest_inference_seconds = perf_counter() - forest_inference_started
    forest_row, forest_matrix = model_evaluation_row(
        "random_forest",
        y_test,
        forest_probabilities,
        forest_training_seconds,
        forest_inference_seconds,
    )
    comparison_rows.append(forest_row)
    matrices["random_forest"] = forest_matrix
    candidate_probabilities["random_forest"] = forest_probabilities

    model_comparison = pd.DataFrame(comparison_rows)
    ranked = model_comparison.sort_values(["f1_score", "roc_auc", "recall"], ascending=False).reset_index(drop=True)
    best_model = str(ranked.iloc[0]["model"])
    logistic_f1 = float(
        model_comparison.loc[model_comparison["model"] == "regresion_logistica", "f1_score"].iloc[0]
    )
    best_f1 = float(ranked.iloc[0]["f1_score"])
    selected_model = "regresion_logistica" if logistic_f1 >= best_f1 - 0.03 else best_model
    model_comparison["selected"] = model_comparison["model"].eq(selected_model).astype(int)

    selected_row = model_comparison.loc[model_comparison["model"] == selected_model].iloc[0]
    float_metric_names = ["accuracy", "precision", "recall", "f1_score", "roc_auc", "gini", "threshold"]
    count_metric_names = [
        "true_negatives_valid_detected",
        "false_positives_valid_marked_risky",
        "false_negatives_risky_marked_valid",
        "true_positives_risky_detected",
    ]
    metrics = {key: float(selected_row[key]) for key in float_metric_names}
    metrics.update({key: int(selected_row[key]) for key in count_metric_names})
    matrix = matrices[selected_model]
    probabilities = candidate_probabilities[selected_model]
    performance = {
        "training_seconds": float(selected_row["training_seconds"]),
        "inference_seconds": float(selected_row["inference_seconds"]),
        "inference_rows": int(len(y_test)),
        "inference_rows_per_second": round(
            len(y_test) / max(float(selected_row["inference_seconds"]), 1e-9),
            2,
        ),
        "dataset_rows": int(len(events)),
        "dataset_source": dataset_source,
        "train_rows": int(len(y_train)),
        "test_rows": int(len(y_test)),
    }

    predictions = x_test.copy()
    predictions["real_label_risky_event"] = y_test
    predictions["risk_probability"] = np.round(probabilities, 4)
    predictions["predicted_label_risky_event"] = (probabilities >= metrics["threshold"]).astype(int)
    predictions["prediction_text"] = np.where(predictions["predicted_label_risky_event"] == 1, "riesgoso", "valido")
    if selected_model == "random_forest":
        selected_weights = forest.feature_importances_
    elif selected_model == "regresion_logistica":
        selected_weights = weights[1:]
    else:
        selected_weights = np.zeros(len(FEATURE_COLUMNS), dtype=float)
    feature_weights = pd.DataFrame(
        {
            "feature": FEATURE_COLUMNS,
            "weight": np.round(selected_weights, 6),
            "abs_weight": np.round(np.abs(selected_weights), 6),
        }
    ).sort_values("abs_weight", ascending=False)

    quality = quality_summary(events)
    correlation = engineered[FEATURE_COLUMNS + ["label_risky_event"]].corr(numeric_only=True)
    all_features = engineered[FEATURE_COLUMNS]
    if selected_model == "random_forest":
        all_probabilities = forest.predict_proba(all_features.to_numpy(dtype=float))[:, 1]
    elif selected_model == "regresion_logistica":
        all_scaled = (all_features.to_numpy(dtype=float) - mean) / std
        all_probabilities = predict_probabilities(all_scaled, weights)
    else:
        all_probabilities = np.full(len(all_features), baseline_probability, dtype=float)
    new_event_predictions = predict_new_events(weights, mean, std, threshold=float(metrics["threshold"]))
    final_decisions = build_final_decisions_from_probabilities(
        events,
        all_probabilities,
        threshold=float(metrics["threshold"]),
    )

    if write_outputs:
        events.to_csv(AI_DATA / "notifyops_ai_events.csv", index=False)
        engineered[FEATURE_COLUMNS + ["label_risky_event"]].to_csv(AI_DATA / "feature_matrix.csv", index=False)
        quality.to_csv(AI_REPORTS / "quality_summary.csv", index=False)
        predictions.to_csv(AI_REPORTS / "test_predictions.csv", index=False)
        pd.DataFrame([metrics]).to_csv(AI_REPORTS / "model_metrics.csv", index=False)
        (AI_REPORTS / "model_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        model_comparison.to_csv(AI_REPORTS / "model_comparison.csv", index=False)
        pd.DataFrame([performance]).to_csv(AI_REPORTS / "performance_summary.csv", index=False)
        fpr, tpr, _ = roc_curve_values(y_test, probabilities)
        pd.DataFrame({"false_positive_rate": fpr, "true_positive_rate": tpr}).to_csv(
            AI_REPORTS / "roc_curve_points.csv",
            index=False,
        )
        pd.DataFrame(matrix, index=["real_valido", "real_riesgoso"], columns=["pred_valido", "pred_riesgoso"]).to_csv(
            AI_REPORTS / "confusion_matrix.csv",
            index_label="real_class",
        )
        for model_name, candidate_matrix in matrices.items():
            pd.DataFrame(
                candidate_matrix,
                index=["real_valido", "real_riesgoso"],
                columns=["pred_valido", "pred_riesgoso"],
            ).to_csv(AI_REPORTS / f"confusion_matrix_{model_name}.csv", index_label="real_class")
        feature_weights.to_csv(AI_REPORTS / "feature_weights.csv", index=False)
        correlation.to_csv(AI_REPORTS / "correlation_matrix.csv")
        new_event_predictions.to_csv(AI_REPORTS / "new_event_predictions.csv", index=False)
        final_decisions.to_csv(AI_REPORTS / "final_event_decisions.csv", index=False)
        model_payload = {
            "model": selected_model,
            "selection_policy": "mayor F1; preferir regresion logistica si queda a 0.03 o menos del mejor F1",
            "target": "label_risky_event",
            "target_definition": {"0": "evento valido", "1": "evento riesgoso"},
            "feature_columns": FEATURE_COLUMNS,
            "weights": weights.round(8).tolist(),
            "mean": mean.round(8).tolist(),
            "std": std.round(8).tolist(),
            "metrics": metrics,
            "performance": performance,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        (MODELS / "notifyops_ai_model.json").write_text(json.dumps(model_payload, indent=2), encoding="utf-8")
        from src.notifyops_ai.bi_dataset import build_powerbi_workbook

        build_powerbi_workbook()

    if save_plots and write_outputs:
        save_bar_chart(
            engineered["label_risky_event"].map({0: "valido", 1: "riesgoso"}).value_counts(),
            "Distribucion de eventos validos y riesgosos",
            CHARTS / "class_distribution.png",
            "#0f766e",
        )
        save_bar_chart(
            engineered["event_type"].replace("", "vacio").value_counts(),
            "Distribucion por tipo de evento",
            CHARTS / "event_type_distribution.png",
            "#2563eb",
        )
        save_bar_chart(
            final_decisions["final_decision"].value_counts(),
            "Decision final: reglas duras + IA",
            CHARTS / "final_decision_distribution.png",
            "#7c3aed",
        )
        bivariate = engineered.groupby("event_type")["label_risky_event"].mean().sort_values(ascending=False)
        save_bar_chart(bivariate, "Riesgo promedio por tipo de evento", CHARTS / "risk_by_event_type.png", "#dc2626")
        save_confusion_matrix_chart(matrix, CHARTS / "confusion_matrix.png")
        save_roc_chart(y_test, probabilities, CHARTS / "roc_curve.png")
        save_feature_weights_chart(feature_weights, CHARTS / "feature_weights.png")
        save_model_comparison_chart(model_comparison, CHARTS / "model_comparison.png")
        save_runtime_comparison_chart(model_comparison, CHARTS / "runtime_comparison.png")
        save_correlation_chart(engineered, CHARTS / "correlation_matrix.png")
        save_dashboard_html(
            metrics,
            model_comparison,
            quality,
            final_decisions,
            performance,
            selected_model,
        )

    return TrainResult(
        metrics=metrics,
        confusion_matrix=matrix,
        feature_weights=feature_weights,
        test_predictions=predictions,
        model_comparison=model_comparison,
        performance=performance,
        selected_model=selected_model,
    )


def main() -> None:
    result = run_ai_pipeline()
    print("NotifyOps AI - filtro inteligente de eventos sociales")
    for key, value in result.metrics.items():
        print(f"{key}: {value}")
    print(f"Dataset IA: {AI_DATA / 'notifyops_ai_events.csv'}")
    print(f"Metricas: {AI_REPORTS / 'model_metrics.csv'}")
    print(f"Excel Power BI fijo: {BI_DATA / 'notifyops_powerbi_dataset.xlsx'}")
    print(f"Dashboard: {DASHBOARD / 'notifyops_ai_dashboard.html'}")


if __name__ == "__main__":
    main()
