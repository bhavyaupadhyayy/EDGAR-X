# EDGAR-X model calibration report

*Generated 2026-06-13T19:52:22+00:00. Revenue-direction XGBoost model.*

## ⚠ Read this first — sample constraint

- Out-of-sample evaluation rests on 447 rows across 2 fiscal year(s) (FY2024-FY2025). This is a SMALL sample; treat all figures as tentative.
- These out-of-sample rows ARE the model's Layer-3 held-out test set, so realized metrics reproducing the reported metrics is expected — it is NOT independent validation. Independent validation requires a new fiscal year of realized outcomes (currently pending).
- 5787 in-sample (train) rows are EXCLUDED from all performance metrics; they appear only as a labeled reference and are not valid for measuring performance.
- Class imbalance: 83% of out-of-sample companies grew revenue, so high accuracy is largely the base rate. Read ROC-AUC, not accuracy.

## Out-of-sample performance (the only valid numbers)

- Rows: **447** across FY2024-FY2025
- Accuracy: **83.0%** (Wilson 95% CI 79.2%–86.2%)
- Realized ROC-AUC: **0.726** (reported 0.726)
- Majority-class baseline accuracy: 83.0% · out-of-sample base rate (grew): 83.0%

## Calibration by score decile (do higher scores actually grow more?)

| decile | score range | n | mean score | actual growth rate | note |
|---|---|---|---|---|---|
| 1 | 0.521–0.567 | 4 | 0.549 | 1.000 | ⚠ small n |
| 2 | 0.567–0.613 | 6 | 0.593 | 0.333 | ⚠ small n |
| 3 | 0.613–0.659 | 22 | 0.635 | 0.500 | ⚠ small n |
| 4 | 0.659–0.705 | 22 | 0.682 | 0.682 | ⚠ small n |
| 5 | 0.705–0.750 | 38 | 0.731 | 0.658 |  |
| 6 | 0.750–0.796 | 38 | 0.773 | 0.789 |  |
| 7 | 0.796–0.842 | 42 | 0.822 | 0.833 |  |
| 8 | 0.842–0.888 | 84 | 0.869 | 0.845 |  |
| 9 | 0.888–0.934 | 114 | 0.913 | 0.921 |  |
| 10 | 0.934–0.980 | 77 | 0.952 | 0.948 |  |

## Accuracy drift by fiscal year

| fiscal year | n | accuracy | 95% CI | note |
|---|---|---|---|---|
| 2024 | 414 | 82.4% | 78.4%–85.7% |  |
| 2025 | 33 | 90.9% | 76.4%–96.9% |  |

## Per-sector calibration

| sector | n | accuracy | 95% CI | note |
|---|---|---|---|---|
| Communication Services | 24 | 75.0% | 55.1%–88.0% | ⚠ small n |
| Consumer Discretionary | 58 | 81.0% | 69.1%–89.1% |  |
| Consumer Staples | 43 | 67.4% | 52.5%–79.5% |  |
| Energy | 20 | 50.0% | 29.9%–70.1% | ⚠ small n |
| Health Care | 62 | 90.3% | 80.5%–95.5% |  |
| Industrials | 75 | 81.3% | 71.1%–88.5% |  |
| Information Technology | 80 | 92.5% | 84.6%–96.5% |  |
| Materials | 26 | 80.8% | 62.1%–91.5% | ⚠ small n |
| Real Estate | 30 | 90.0% | 74.4%–96.5% |  |
| Utilities | 29 | 96.6% | 82.8%–99.4% | ⚠ small n |

## In-sample reference (NOT valid for performance)

- 5787 in-sample (train) rows, accuracy 81.3%. The model was trained on these labels; this number is reference only and must not be read as performance.

## Verdict

On 447 out-of-sample rows (FY2024-FY2025), accuracy 83.0% (95% CI 79.2%-86.2%), realized ROC-AUC 0.726 (reported 0.726; matches because it is the same held-out set). The model ranks better than chance but the confidence interval is wide and only one-to-two fiscal years are observed — no claim of stability or decay is supportable yet. The framework will produce robust numbers as out-of-sample years accumulate.
