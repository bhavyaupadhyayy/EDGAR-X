# Model card — revenue-direction classifier (XGBoost)

Trained 2026-06-12 on `EDGAR_X.MARTS.ML_TRAINING_SET` (real SEC EDGAR + FRED data only).

**Target**: P(FY N+1 revenue > FY N revenue), using only information available at the FY N 10-K filing date.

## Data split (time-based, no shuffling)

- **train**: 5787 rows, 425 companies, FY2007-FY2023, 75.8% positive
- **test**: 447 rows, 416 companies, FY2024-FY2025, 83.0% positive

## Test-set metrics (held out, evaluated once)

| model | accuracy | precision | recall | F1 | ROC-AUC |
|---|---|---|---|---|---|
| majority-class (always up) | 0.830 | 0.830 | 1.000 | 0.907 | 0.500 |
| logistic regression | 0.834 | 0.838 | 0.992 | 0.909 | 0.607 |
| xgboost (tuned) | 0.830 | 0.830 | 1.000 | 0.907 | 0.726 |

## SHAP importance (top 12, mean |SHAP| on test)

- revenue_growth_1y: 0.3158
- revenue: 0.2394
- yield_curve_spread: 0.2166
- cpi_yoy: 0.1973
- unemployment_rate: 0.1501
- net_margin: 0.1160
- sector_Health Care: 0.0985
- fed_funds_rate: 0.0673
- risk_word_total: 0.0671
- gross_margin: 0.0663
- sector_Utilities: 0.0568
- impairment_mentions: 0.0524

Share of total |SHAP| by feature family: language 15.5%, sector 16.0%, fundamental 39.3%, macro 29.2%

## Limitations (read before using)

- **Survivorship bias**: universe is the CURRENT S&P 500 only. Companies that shrank and exited the index are absent, which tilts the base rate positive (~76%) and flatters apparent predictability.
- **Financials excluded** (~70 companies): the XBRL revenue concepts used do not capture bank/insurer revenue.
- **Filing-language coverage is ~56%** of rows (10-year filing lookback vs 19 years of fundamentals); language features are NaN for older rows and XGBoost treats missingness as signal.
- **High base rate (76.3% positive)**: accuracy is a misleading headline; compare ROC-AUC against the 0.5 of the majority baseline.
- **Prediction time is the filing date**, not fiscal year end: macro features legitimately include the first ~2-3 months of FY N+1.
- **Revenue extraction is best-effort XBRL**: REIT/lease tagging and filer errors were corrected where bounds tests caught them; residual tag noise may remain in both features and labels.

## Final hyperparameters

```json
{
  "max_depth": 5,
  "learning_rate": 0.011040426799586047,
  "n_estimators": 576,
  "min_child_weight": 18,
  "subsample": 0.706711013151552,
  "colsample_bytree": 0.5699012578388758,
  "reg_lambda": 0.040613942131060274,
  "reg_alpha": 0.0011273926795746854,
  "scale_pos_weight": 1.742333883111424
}
```
