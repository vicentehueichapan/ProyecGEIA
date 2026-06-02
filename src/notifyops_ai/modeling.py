from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
AI_DATA = DATA / "ai"
REPORTS = DATA / "reports"
AI_REPORTS = REPORTS / "ai"
CHARTS = AI_REPORTS / "charts"
DASHBOARD = ROOT / "dashboard"
MODELS = ROOT / "models"

ALLOWED_EVENT_TYPES = ("like", "comment", "follow")
ALL_EVENT_TYPES = ("like", "comment", "follow", "share", "reaction", "unknown", "")
FEATURE_COLUMNS = [
    "content_length",
    "hour",
    "day_of_week",
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
        historical_feedback_risk = bool((not rule_based_risk) and rng.random() < 0.06)
        is_risky = bool(rule_based_risk or historical_feedback_risk)

        records.append(
            {
                "event_id": event_id,
                "event_type": event_type,
                "source_user_id": source_user_id,
                "target_user_id": target_user_id,
                "created_at": created_at_value,
                "content": content,
                "is_duplicate": int(duplicate),
                "historical_feedback_risk": int(historical_feedback_risk),
                "label_risky_event": int(is_risky),
            }
        )

    return pd.DataFrame(records)


def engineer_features(events: pd.DataFrame) -> pd.DataFrame:
    frame = events.copy().fillna("")
    frame["event_type"] = frame["event_type"].astype(str).str.strip().str.lower()
    parsed_dates = pd.to_datetime(frame["created_at"], errors="coerce")
    frame["content_length"] = frame["content"].astype(str).str.len()
    frame["hour"] = parsed_dates.dt.hour.fillna(-1).astype(int)
    frame["day_of_week"] = parsed_dates.dt.dayofweek.fillna(-1).astype(int)
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
    auc = float(np.trapezoid(tpr[order], fpr[order]))
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


def save_dashboard_html(metrics: Dict[str, float]) -> None:
    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>NotifyOps AI Dashboard</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; background: #f8fafc; color: #111827; }}
    h1 {{ margin-bottom: 4px; }}
    .subtitle {{ color: #475569; margin-bottom: 24px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); gap: 14px; }}
    .card {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; }}
    .value {{ font-size: 28px; font-weight: 700; color: #0f766e; }}
    .charts {{ display: grid; grid-template-columns: repeat(2, minmax(280px, 1fr)); gap: 18px; margin-top: 24px; }}
    img {{ width: 100%; background: white; border: 1px solid #e5e7eb; border-radius: 8px; }}
    code {{ background: #e5e7eb; padding: 2px 5px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>NotifyOps AI Dashboard</h1>
  <div class="subtitle">Filtro inteligente para clasificar eventos sociales como validos o riesgosos.</div>
  <div class="grid">
    <div class="card"><div>Accuracy</div><div class="value">{metrics['accuracy']}</div></div>
    <div class="card"><div>Precision</div><div class="value">{metrics['precision']}</div></div>
    <div class="card"><div>Recall</div><div class="value">{metrics['recall']}</div></div>
    <div class="card"><div>Gini</div><div class="value">{metrics['gini']}</div></div>
  </div>
  <div class="charts">
    <img src="../data/reports/ai/charts/class_distribution.png" alt="Distribucion de clases">
    <img src="../data/reports/ai/charts/confusion_matrix.png" alt="Matriz de confusion">
    <img src="../data/reports/ai/charts/roc_curve.png" alt="Curva ROC">
    <img src="../data/reports/ai/charts/feature_weights.png" alt="Importancia de variables">
    <img src="../data/reports/ai/charts/final_decision_distribution.png" alt="Decision final reglas mas IA">
  </div>
  <p>Archivos principales: <code>data/ai/notifyops_ai_events.csv</code>, <code>data/reports/ai/model_metrics.csv</code>, <code>data/reports/ai/final_event_decisions.csv</code>, <code>data/reports/ai/new_event_predictions.csv</code>.</p>
</body>
</html>
"""
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


def run_ai_pipeline(rows: int = 320, seed: int = 42, save_plots: bool = True, write_outputs: bool = True) -> TrainResult:
    ensure_directories()
    events = generate_synthetic_events(rows=rows, seed=seed)
    engineered = engineer_features(events)
    features = engineered[FEATURE_COLUMNS]
    target = engineered["label_risky_event"].astype(int)
    x_train, x_test, y_train, y_test = stratified_train_test_split(features, target, seed=seed)
    x_train_scaled, x_test_scaled, mean, std = standardize_train_test(x_train, x_test)
    weights = train_logistic_regression(x_train_scaled, y_train.to_numpy(dtype=int))
    probabilities = predict_probabilities(x_test_scaled, weights)
    metrics, matrix = classification_metrics(y_test, probabilities)
    predictions = x_test.copy()
    predictions["real_label_risky_event"] = y_test
    predictions["risk_probability"] = np.round(probabilities, 4)
    predictions["predicted_label_risky_event"] = (probabilities >= metrics["threshold"]).astype(int)
    predictions["prediction_text"] = np.where(predictions["predicted_label_risky_event"] == 1, "riesgoso", "valido")
    feature_weights = pd.DataFrame(
        {
            "feature": FEATURE_COLUMNS,
            "weight": np.round(weights[1:], 6),
            "abs_weight": np.round(np.abs(weights[1:]), 6),
        }
    ).sort_values("abs_weight", ascending=False)

    quality = quality_summary(events)
    correlation = engineered[FEATURE_COLUMNS + ["label_risky_event"]].corr(numeric_only=True)
    new_event_predictions = predict_new_events(weights, mean, std, threshold=metrics["threshold"])
    final_decisions = build_final_decisions(events, weights, mean, std, threshold=metrics["threshold"])

    if write_outputs:
        events.to_csv(AI_DATA / "notifyops_ai_events.csv", index=False)
        engineered[FEATURE_COLUMNS + ["label_risky_event"]].to_csv(AI_DATA / "feature_matrix.csv", index=False)
        quality.to_csv(AI_REPORTS / "quality_summary.csv", index=False)
        predictions.to_csv(AI_REPORTS / "test_predictions.csv", index=False)
        pd.DataFrame([metrics]).to_csv(AI_REPORTS / "model_metrics.csv", index=False)
        (AI_REPORTS / "model_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        pd.DataFrame(matrix, index=["real_valido", "real_riesgoso"], columns=["pred_valido", "pred_riesgoso"]).to_csv(
            AI_REPORTS / "confusion_matrix.csv",
            index_label="real_class",
        )
        feature_weights.to_csv(AI_REPORTS / "feature_weights.csv", index=False)
        correlation.to_csv(AI_REPORTS / "correlation_matrix.csv")
        new_event_predictions.to_csv(AI_REPORTS / "new_event_predictions.csv", index=False)
        final_decisions.to_csv(AI_REPORTS / "final_event_decisions.csv", index=False)
        model_payload = {
            "model": "logistic_regression_numpy",
            "target": "label_risky_event",
            "target_definition": {"0": "evento valido", "1": "evento riesgoso"},
            "feature_columns": FEATURE_COLUMNS,
            "weights": weights.round(8).tolist(),
            "mean": mean.round(8).tolist(),
            "std": std.round(8).tolist(),
            "metrics": metrics,
        }
        (MODELS / "notifyops_ai_model.json").write_text(json.dumps(model_payload, indent=2), encoding="utf-8")

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
        save_correlation_chart(engineered, CHARTS / "correlation_matrix.png")
        save_dashboard_html(metrics)

    return TrainResult(metrics=metrics, confusion_matrix=matrix, feature_weights=feature_weights, test_predictions=predictions)


def main() -> None:
    result = run_ai_pipeline()
    print("NotifyOps AI - filtro inteligente de eventos sociales")
    for key, value in result.metrics.items():
        print(f"{key}: {value}")
    print(f"Dataset IA: {AI_DATA / 'notifyops_ai_events.csv'}")
    print(f"Metricas: {AI_REPORTS / 'model_metrics.csv'}")
    print(f"Dashboard: {DASHBOARD / 'notifyops_ai_dashboard.html'}")


if __name__ == "__main__":
    main()
