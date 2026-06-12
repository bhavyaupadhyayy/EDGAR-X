"""Train the revenue-direction XGBoost model with honest evaluation.

Protocol:

* TIME-BASED split only: train on fiscal years <= 2023, test on 2024-2025.
* Optuna tunes on the train years exclusively, with an inner time-based
  validation split (fit <= 2021, validate 2022-2023). The test set is touched
  exactly once, after tuning is frozen.
* Reported against two baselines on the same test set: majority-class
  ("always up") and logistic regression (median-impute + standardise).
* SHAP importance on the final model, grouped by feature family.

Usage::

    set -a; source .env; set +a
    python -m ml.revenue_predictor.train
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from core.logging import configure_logging, get_logger
from ml.revenue_predictor.feature_engineering import (
    DatasetSummary,
    encode_features,
    feature_groups,
    load_training_set,
    summarise,
    time_split,
)

if TYPE_CHECKING:  # pragma: no cover - heavy imports, typing only
    import pandas as pd

configure_logging()
logger = get_logger(__name__)

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
TEST_YEARS: tuple[int, ...] = (2024, 2025)
VALIDATION_YEARS: tuple[int, ...] = (2022, 2023)
OPTUNA_TRIALS = 40
RANDOM_SEED = 42


class ModelMetrics(BaseModel):
    """Evaluation metrics for one model on the held-out test set."""

    model_name: str
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float
    confusion: list[list[int]]  # [[tn, fp], [fn, tp]]


def evaluate(name: str, y_true: Any, y_pred: Any, y_score: Any) -> ModelMetrics:
    """Compute the metric set for one model.

    Args:
        name: Model name for reporting.
        y_true: Ground-truth labels.
        y_pred: Hard predictions (0/1).
        y_score: Probability scores for the positive class.

    Returns:
        The populated metrics model.
    """
    from sklearn import metrics as skm  # noqa: PLC0415 - deferred heavy import

    return ModelMetrics(
        model_name=name,
        accuracy=float(skm.accuracy_score(y_true, y_pred)),
        precision=float(skm.precision_score(y_true, y_pred, zero_division=0)),
        recall=float(skm.recall_score(y_true, y_pred, zero_division=0)),
        f1=float(skm.f1_score(y_true, y_pred, zero_division=0)),
        roc_auc=float(skm.roc_auc_score(y_true, y_score)),
        confusion=skm.confusion_matrix(y_true, y_pred).tolist(),
    )


def tune_xgboost(
    x_fit: pd.DataFrame,
    y_fit: pd.Series,
    x_val: pd.DataFrame,
    y_val: pd.Series,
    *,
    n_trials: int = OPTUNA_TRIALS,
) -> dict[str, Any]:
    """Tune XGBoost hyperparameters on the inner time-based validation split.

    Args:
        x_fit: Features for fiscal years <= 2021.
        y_fit: Labels for the fit slice.
        x_val: Features for the 2022-2023 validation years.
        y_val: Labels for the validation slice.
        n_trials: Optuna trial budget.

    Returns:
        The best hyperparameter dict (validation ROC-AUC objective).
    """
    import optuna  # noqa: PLC0415 - deferred heavy import
    from sklearn.metrics import roc_auc_score  # noqa: PLC0415
    from xgboost import XGBClassifier  # noqa: PLC0415

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: optuna.Trial) -> float:
        params = {
            "max_depth": trial.suggest_int("max_depth", 2, 6),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 600),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 20),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-2, 10.0, log=True),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 1.0, log=True),
            "scale_pos_weight": trial.suggest_float("scale_pos_weight", 0.3, 3.0),
        }
        model = XGBClassifier(
            **params,
            objective="binary:logistic",
            eval_metric="auc",
            random_state=RANDOM_SEED,
            n_jobs=-1,
        )
        model.fit(x_fit, y_fit, verbose=False)
        return float(roc_auc_score(y_val, model.predict_proba(x_val)[:, 1]))

    study = optuna.create_study(
        direction="maximize", sampler=optuna.samplers.TPESampler(seed=RANDOM_SEED)
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    logger.info("optuna_complete", best_val_auc=round(study.best_value, 4))
    return dict(study.best_params)


def shap_importance(model: Any, x_test: pd.DataFrame) -> pd.Series:
    """Mean absolute SHAP value per feature on the test set.

    Args:
        model: The fitted XGBoost classifier.
        x_test: Test feature matrix.

    Returns:
        Per-feature mean |SHAP|, descending.
    """
    import numpy as np  # noqa: PLC0415 - deferred heavy import
    import pandas as pd  # noqa: PLC0415
    import shap  # noqa: PLC0415

    explainer = shap.TreeExplainer(model)
    values = explainer.shap_values(x_test)
    importance = pd.Series(np.abs(values).mean(axis=0), index=x_test.columns)
    return importance.sort_values(ascending=False)


def write_model_card(
    *,
    summaries: list[DatasetSummary],
    metrics: list[ModelMetrics],
    importance: pd.Series,
    group_share: dict[str, float],
    params: dict[str, Any],
) -> Path:
    """Write the model card with metrics and explicit limitations.

    Args:
        summaries: Train/test slice summaries.
        metrics: Metrics for all evaluated models.
        importance: SHAP importance per feature.
        group_share: Share of total |SHAP| per feature family.
        params: Final XGBoost hyperparameters.

    Returns:
        Path of the written model card.
    """
    lines = [
        "# Model card — revenue-direction classifier (XGBoost)",
        "",
        f"Trained {datetime.now(UTC).date()} on `EDGAR_X.MARTS.ML_TRAINING_SET` "
        "(real SEC EDGAR + FRED data only).",
        "",
        "**Target**: P(FY N+1 revenue > FY N revenue), using only information "
        "available at the FY N 10-K filing date.",
        "",
        "## Data split (time-based, no shuffling)",
        "",
    ]
    for s in summaries:
        lines.append(
            f"- **{s.name}**: {s.rows} rows, {s.companies} companies, "
            f"FY{s.fiscal_year_min}-FY{s.fiscal_year_max}, "
            f"{100 * s.positive_rate:.1f}% positive"
        )
    lines += [
        "",
        "## Test-set metrics (held out, evaluated once)",
        "",
        "| model | accuracy | precision | recall | F1 | ROC-AUC |",
        "|---|---|---|---|---|---|",
    ]
    for m in metrics:
        lines.append(
            f"| {m.model_name} | {m.accuracy:.3f} | {m.precision:.3f} "
            f"| {m.recall:.3f} | {m.f1:.3f} | {m.roc_auc:.3f} |"
        )
    lines += [
        "",
        "## SHAP importance (top 12, mean |SHAP| on test)",
        "",
        *[f"- {name}: {value:.4f}" for name, value in importance.head(12).items()],
        "",
        "Share of total |SHAP| by feature family: "
        + ", ".join(f"{k} {100 * v:.1f}%" for k, v in group_share.items()),
        "",
        "## Limitations (read before using)",
        "",
        "- **Survivorship bias**: universe is the CURRENT S&P 500 only. "
        "Companies that shrank and exited the index are absent, which tilts "
        "the base rate positive (~76%) and flatters apparent predictability.",
        "- **Financials excluded** (~70 companies): the XBRL revenue concepts "
        "used do not capture bank/insurer revenue.",
        "- **Filing-language coverage is ~56%** of rows (10-year filing "
        "lookback vs 19 years of fundamentals); language features are NaN "
        "for older rows and XGBoost treats missingness as signal.",
        "- **High base rate (76.3% positive)**: accuracy is a misleading "
        "headline; compare ROC-AUC against the 0.5 of the majority baseline.",
        "- **Prediction time is the filing date**, not fiscal year end: "
        "macro features legitimately include the first ~2-3 months of FY N+1.",
        "- **Revenue extraction is best-effort XBRL**: REIT/lease tagging and "
        "filer errors were corrected where bounds tests caught them; residual "
        "tag noise may remain in both features and labels.",
        "",
        f"## Final hyperparameters\n\n```json\n{json.dumps(params, indent=2)}\n```",
        "",
    ]
    path = ARTIFACT_DIR / "MODEL_CARD.md"
    path.write_text("\n".join(lines))
    return path


def main() -> int:
    """Run the full train/evaluate/report pipeline."""
    import joblib  # noqa: PLC0415 - deferred heavy import
    import numpy as np  # noqa: PLC0415
    from sklearn.impute import SimpleImputer  # noqa: PLC0415
    from sklearn.linear_model import LogisticRegression  # noqa: PLC0415
    from sklearn.pipeline import Pipeline  # noqa: PLC0415
    from sklearn.preprocessing import StandardScaler  # noqa: PLC0415
    from xgboost import XGBClassifier  # noqa: PLC0415

    ARTIFACT_DIR.mkdir(exist_ok=True)
    frame = load_training_set()
    train_frame, test_frame = time_split(frame, test_years=TEST_YEARS)
    summaries = [summarise("train", train_frame), summarise("test", test_frame)]
    for s in summaries:
        logger.info("split_summary", **s.model_dump())

    x_train, y_train = encode_features(train_frame)
    x_test, y_test = encode_features(test_frame)
    x_test = x_test.reindex(columns=x_train.columns, fill_value=0.0)

    # Inner time-based validation for tuning: fit <= 2021, validate 2022-23.
    inner_fit = train_frame[~train_frame["fiscal_year"].isin(VALIDATION_YEARS)]
    inner_val = train_frame[train_frame["fiscal_year"].isin(VALIDATION_YEARS)]
    x_fit, y_fit = encode_features(inner_fit)
    x_val, y_val = encode_features(inner_val)
    x_val = x_val.reindex(columns=x_fit.columns, fill_value=0.0)
    best_params = tune_xgboost(x_fit, y_fit, x_val, y_val)

    # Final model: refit on the full train years with frozen hyperparameters.
    model = XGBClassifier(
        **best_params,
        objective="binary:logistic",
        eval_metric="auc",
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )
    model.fit(x_train, y_train, verbose=False)

    results: list[ModelMetrics] = []

    majority_pred = np.ones(len(y_test), dtype=int)
    majority_score = np.full(len(y_test), 0.5)
    results.append(evaluate("majority-class (always up)", y_test, majority_pred, majority_score))

    logistic = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(max_iter=2000, random_state=RANDOM_SEED)),
        ]
    )
    logistic.fit(x_train, y_train)
    results.append(
        evaluate(
            "logistic regression",
            y_test,
            logistic.predict(x_test),
            logistic.predict_proba(x_test)[:, 1],
        )
    )

    results.append(
        evaluate(
            "xgboost (tuned)",
            y_test,
            model.predict(x_test),
            model.predict_proba(x_test)[:, 1],
        )
    )

    importance = shap_importance(model, x_test)
    groups = feature_groups(list(x_train.columns))
    total = float(importance.sum())
    group_share = {
        name: float(importance.reindex(columns_).fillna(0).sum()) / total
        for name, columns_ in groups.items()
    }

    model.save_model(ARTIFACT_DIR / "xgboost_revenue_direction.json")
    joblib.dump(logistic, ARTIFACT_DIR / "logistic_baseline.joblib")
    (ARTIFACT_DIR / "feature_columns.json").write_text(json.dumps(list(x_train.columns)))
    (ARTIFACT_DIR / "metrics.json").write_text(
        json.dumps([m.model_dump() for m in results], indent=2)
    )
    card = write_model_card(
        summaries=summaries,
        metrics=results,
        importance=importance,
        group_share=group_share,
        params=best_params,
    )

    print("\n=== split ===")
    for s in summaries:
        print(
            f"{s.name}: {s.rows} rows / {s.companies} companies / "
            f"FY{s.fiscal_year_min}-{s.fiscal_year_max} / pos {100 * s.positive_rate:.1f}%"
        )
    print("\n=== test-set metrics ===")
    print(f"{'model':<28}{'acc':>7}{'prec':>7}{'rec':>7}{'f1':>7}{'auc':>7}")
    for m in results:
        print(
            f"{m.model_name:<28}{m.accuracy:>7.3f}{m.precision:>7.3f}"
            f"{m.recall:>7.3f}{m.f1:>7.3f}{m.roc_auc:>7.3f}"
        )
        print(f"  confusion [[tn, fp], [fn, tp]]: {m.confusion}")
    print("\n=== SHAP top 12 ===")
    for name, value in importance.head(12).items():
        print(f"  {name:<28}{value:.4f}")
    print("group share:", {k: f"{100 * v:.1f}%" for k, v in group_share.items()})
    print(f"\nmodel card: {card}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
