# CAT — FY2025 research memo

*Generated 2026-06-12T21:04:01+00:00 by EDGAR-X (Claude Fable 5 pipeline). Confidence: **moderate**.*

## Summary

Caterpillar's FY2025 10-K shows a company growing the top line (sales up 4% to $67.589 billion on higher volume) while absorbing a sharp profitability hit: operating margin fell from 20.2% to 16.5%, with tariffs cited as the primary driver of $2.148 billion in unfavorable manufacturing costs and a further ~$2.6 billion tariff impact expected in 2026. Despite the cost pressure, management's outlook turned notably bullish, guiding FY2026 revenue to the top of its 5-7% CAGR target, with Power & Energy (renamed from Energy & Transportation) and data center/AI-driven power generation demand as the key growth engines. Structural changes include a pending ~$790 million acquisition of mining software firm RPMGlobal and a planned Rail segment recast. The XGBoost ranked screen places CAT near the top at 0.8979, plausibly driven by positive revenue momentum and large-cap scale, but this is a relative ranking signal only, and a gross-margin data artifact plus missing profitability features warrant discounting margin-based contributions.

**Model signal**: XGBoost ranked-screen score **0.8979** for FY2025. XGBoost revenue-direction model used as a RANKED SCREEN (test ROC-AUC 0.726 vs 0.500 majority baseline, FY2024-25 holdout). It is NOT a calibrated classifier: at the default threshold it predicts the majority class for nearly all companies. Scores order companies by relative likelihood of revenue growth; they are not probabilities to act on.

## Key findings

1. Tariffs emerged as the dominant new cost driver in FY2025, cited as the primary cause of unfavorable manufacturing costs that drove the 15% decline in operating profit, with management expecting roughly $2.6 billion of tariff impact in 2026 — about $800 million more than incurred in 2025.
   - *source: extraction agent — “we expect the impact from tariffs to be around $2.6 billion in 2026, which is $800 million higher than incurred in 2025.”*
2. Profitability deteriorated sharply year over year: operating margin compressed from 20.2% to 16.5% on tariff-driven costs and unfavorable pricing, reversing the prior year's margin expansion trend.
   - *source: comparison agent — “Operating profit margin was 16.5 percent in 2025, compared with 20.2 percent in 2024.”*
3. The top-line outlook flipped from prior-year contraction guidance to strong growth: management now expects FY2026 sales and revenues to grow around the top end of the 5-7% CAGR target, versus the FY2024 filing's guidance for slightly lower sales with unfavorable pricing.
   - *source: comparison agent — “we anticipate sales and revenues to grow around the top end of our 5 to 7 percent compound annual growth rate (CAGR) target”*
4. FY2025 revenue grew 4% to $67.589 billion, driven primarily by higher sales volume (mainly equipment sales to end users) of $3.389 billion, partially offset by unfavorable price realization of $817 million.
   - *source: extraction agent — “The increase was primarily driven by higher sales volume of $3.389 billion, partially offset by unfavorable price realization of $817 million.”*
5. Power & Energy was the growth engine, with segment sales up 12% led by Power Generation — particularly large reciprocating engines for data center applications — and management expects 2026 growth driven by data center build-out for cloud computing and generative AI.
   - *source: extraction agent — “Power Generation – Sales increased in large reciprocating engines, primarily data center applications.”*
6. The XGBoost ranked screen scores CAT FY2025 at 0.8979, near the top of the screen; this is a relative ranking of revenue-direction likelihood, not a probability or forecast, particularly given the model's modest AUC of 0.726.
   - *source: signal agent — “xgboost_score = 0.8979”*
7. The high screen rank is most plausibly driven by trailing one-year revenue growth of roughly 4.3% — the model's most important feature family — reinforced by CAT's large-cap scale, consistent with the filing-reported revenue growth.
   - *source: signal agent — “revenue_growth_1y = 0.04289527689055528”*
8. The data center/AI demand theme broadened year over year beyond Power Generation into construction outlook and prime-power orders, indicating a structurally widening growth narrative.
   - *source: comparison agent — “we are starting to see orders for prime power trend higher as data center customers look for alternative power solutions”*
9. Caterpillar is making structural portfolio moves: a pending ~$790 million acquisition of mining software company RPMGlobal expected to close in late February 2026, tied to newly articulated strategic growth pillars.
   - *source: extraction agent — “The transaction is expected to close in the final two weeks of February with a purchase price of approximately $790 million, excluding cash acquired.”*
10. Margin-based features in the model score are unreliable for this company-year: the recorded gross margin of 99.93% is almost certainly a data extraction artifact for a heavy-equipment manufacturer, and net margin was unavailable, so margin contributions to the score should be heavily discounted.
   - *source: signal agent — “gross_margin = 0.9992750299604966”*

**Confidence rationale**: The extraction and comparison outputs are well-grounded with verbatim filing evidence, mutually consistent (both identify tariffs as the new dominant cost driver, the margin decline, the bullish FY2026 outlook, and the data center/AI growth theme), and declare no data gaps; risk-factor language is essentially stable year over year, matching near-zero numeric deltas. However, confidence is held to moderate because of material signal-agent caveats: the gross margin of 99.93% is flagged as a data artifact, net margin and annualised ROE were unavailable so profitability features could not be assessed, Cat Financial's captive-finance balance sheet may sit atypically in the model's training distribution, and the model itself has limited discriminative power (AUC 0.726) and is survivorship-biased. There is also mild internal tension between the model's positive ranking (driven by revenue momentum) and the filing's significant tariff-driven margin compression, which the revenue-direction screen does not capture.

## ⚠ Traceability warnings

- finding cites signal but its attribution was not found in that agent's output: "The XGBoost ranked screen scores CAT FY2025 at 0.8979, near the top of the screen; this is a relative ranking of revenue-direction likelihood, not a probability or forecast, particularly given the model's modest AUC of 0.726." (attribution: 'xgboost_score = 0.8979')
- finding cites signal but its attribution was not found in that agent's output: "The high screen rank is most plausibly driven by trailing one-year revenue growth of roughly 4.3% — the model's most important feature family — reinforced by CAT's large-cap scale, consistent with the filing-reported revenue growth." (attribution: 'revenue_growth_1y = 0.04289527689055528')
- finding cites signal but its attribution was not found in that agent's output: 'Margin-based features in the model score are unreliable for this company-year: the recorded gross margin of 99.93% is almost certainly a data extraction artifact for a heavy-equipment manufacturer, and net margin was unavailable, so margin contributions to the score should be heavily discounted.' (attribution: 'gross_margin = 0.9992750299604966')

## Year-over-year filing changes (comparison agent)

- **new_driver** (mdna): Tariffs emerge as a major new cost driver, cited as the primary cause of unfavorable manufacturing costs and a quantified ~$2.6B expected 2026 headwind.
  - FY2025: “we expect the impact from tariffs to be around $2.6 billion in 2026, which is $800 million higher than incurred in 2025”
  - FY2024: “(absent prior year)”
- **tone_shift** (mdna): Profitability tone shifts sharply negative: operating margin fell from 20.2% to 16.5% on tariff-driven costs and unfavorable pricing, versus prior-year margin expansion.
  - FY2025: “Operating profit margin was 16.5 percent in 2025, compared with 20.2 percent in 2024.”
  - FY2024: “Operating profit margin was 20.2 percent in 2024, compared with 19.3 percent in 2023.”
- **tone_shift** (mdna): Top-line outlook flips from contraction to strong growth: FY2025 guides to ~top of 5-7% CAGR with favorable pricing, versus FY2024 guiding slightly lower sales with unfavorable pricing.
  - FY2025: “we anticipate sales and revenues to grow around the top end of our 5 to 7 percent compound annual growth rate (CAGR) target”
  - FY2024: “we anticipate sales and revenues will be slightly lower compared to 2024, primarily driven by lower sales volume and unfavorable price realization”
- **language_drift** (mdna): Segment and entity nomenclature changed: 'Energy & Transportation' renamed 'Power & Energy' and 'Machinery, Energy & Transportation (ME&T)' became 'Machinery, Power & Energy (MP&E)'.
  - FY2025: “Power & Energy’s total sales were $32.201 billion in 2025”
  - FY2024: “Energy & Transportation’s total sales were $28.854 billion in 2024”
- **new_driver** (mdna): New structural driver disclosed: the Rail division will be moved from Power & Energy into Resource Industries, with historical segments recast in March 2026.
  - FY2025: “we will file a Form 8-K recasting historical periods to reflect the movement of the Rail division to Resource Industries”
  - FY2024: “(absent prior year)”
- **new_driver** (mdna): New growth driver: pending ~$790M acquisition of mining software firm RPMGlobal, tied to newly articulated 'strategic growth pillars'.
  - FY2025: “the Federal Court of Australia approved Caterpillar's acquisition of RPMGlobal Holdings Limited, an Australian based software company”
  - FY2024: “(absent prior year)”
- **tone_shift** (mdna): Data center/AI demand emphasis broadens beyond Power Generation into construction outlook and prime-power orders.
  - FY2025: “we are starting to see orders for prime power trend higher as data center customers look for alternative power solutions”
  - FY2024: “increasing energy demands to support data center growth related to cloud computing and generative artificial intelligence (AI)”
- **language_drift** (risk_factors): Pension risk factor wording softened, dropping 'significantly' from the funding-obligation impact, consistent with the small negative risk-word delta.
  - FY2025: “These factors could increase our payment obligations under the plans”
  - FY2024: “These factors could significantly increase our payment obligations under the plans”

Numeric language-feature deltas (computed by dbt, not the LLM):

- decline_mentions: 5.0 → 4.0 (Δ -1.0)
- risk_word_total: 46.0 → 45.0 (Δ -1.0)
- risk_words_per_1000: 3.44931 → 3.326926 (Δ -0.1224)

## Filing claims (extraction agent)

- [business_driver | mdna] 2025 sales and revenues increased 4% to $67.589 billion, primarily driven by higher sales volume (mainly higher sales of equipment to end users), partially offset by unfavorable price realization.
  - quote: “The increase was primarily driven by higher sales volume of $3.389 billion, partially offset by unfavorable price realization of $817 million.”
- [business_driver | mdna] Profit declined in 2025 mainly because of unfavorable manufacturing costs, which management attributes largely to higher tariffs, plus unfavorable price realization.
  - quote: “The decrease was mainly due to unfavorable
 manufacturing costs
 and unfavorable price realization, partially offset by the profit impact of higher sales volume.”
- [business_driver | mdna] Higher tariffs were the primary cause of the $2.148 billion of unfavorable manufacturing costs that drove the 15% decline in operating profit.
  - quote: “Unfavorable manufacturing costs largely reflected the impact of higher tariffs.”
- [business_driver | mdna] Power & Energy was the growth engine in 2025, with segment sales up 12% led by Power Generation, particularly large reciprocating engines for data center applications.
  - quote: “Power Generation – Sales increased in large reciprocating engines, primarily data center applications.”
- [forward_looking | mdna] Management expects full-year 2026 sales and revenues to grow around the top end of its 5 to 7 percent CAGR target, supported by a strong backlog and healthy end markets.
  - quote: “For the full-year 2026, we anticipate sales and revenues to grow around the top end of our 5 to 7 percent compound annual growth rate (CAGR) target, as compared to 2025.”
- [forward_looking | mdna] Management expects roughly $2.6 billion of tariff impact in 2026, about $800 million more than incurred in 2025, and ~20% higher absent planned mitigating actions.
  - quote: “we expect the impact from tariffs to be around $2.6 billion in 2026, which is $800 million higher than incurred in 2025.”
- [forward_looking | mdna] Power Generation growth in 2026 is expected to be driven by rising energy demand tied to data center build-out for cloud computing and generative AI.
  - quote: “driven by increasing energy demand to support data center build-out related to cloud computing and generative Artificial Intelligence (AI).”
- [forward_looking | mdna] For 2026, the company guides to restructuring costs of about $300-$350 million, capital expenditures of around $3.5 billion, and an estimated annual effective tax rate of 23.0%.
  - quote: “we expect restructuring costs of approximately $300 million to $350 million and capital expenditures of around $3.5 billion. We anticipate our 2026 estimated annual effective tax rate to be 23.0 percent”
- [forward_looking | mdna] Caterpillar expects to close its approximately $790 million acquisition of mining software company RPMGlobal in late February 2026.
  - quote: “The transaction is expected to close in the final two weeks of February with a purchase price of approximately $790 million, excluding cash acquired.”
- [stated_risk | risk_factors] Demand for Caterpillar products is highly cyclical and sensitive to global and regional economic conditions, with energy, transportation and mining customers basing purchases on expected commodity dynamics.
  - quote: “The demand for our products and services tends to be cyclical and can be significantly reduced in periods of economic weakness”
- [stated_risk | risk_factors] Restrictive international trade policies, including higher tariffs, could reduce demand for the company's products and harm its competitive position.
  - quote: “The implementation of more restrictive trade policies (such as more detailed inspections, higher tariffs or new barriers to entry) in countries where we sell large quantities of products”
- [stated_risk | risk_factors] Because Caterpillar sells primarily through independent dealers and OEMs, their inventory management decisions can cause company sales to diverge from end-user demand.
  - quote: “If the inventory levels of our dealers and OEM customers are higher than they desire, they may postpone product purchases from us, which could cause our sales to be lower than the end-user demand”

## Model-signal statements (signal agent)

- The score of 0.8979 places this company-year high in the model's ranked screen of revenue-direction candidates; it should be read as a relative ranking, not a probability of growth, particularly given the model's modest AUC of 0.726. (*xgboost_score = 0.8979*)
- Trailing one-year revenue growth of roughly 4.3% provides positive momentum, which is the single most important feature family for this model and is the most plausible primary driver of the elevated score. (*revenue_growth_1y = 0.04289527689055528*)
- Revenue of approximately $67.6 billion marks this as a very large company; size is the model's second-most-important feature group, and large-cap scale likely reinforces the high ranking. (*revenue = 67589000000.0*)
- Gross margin is recorded as 99.93%, which is implausible for a heavy-equipment manufacturer like Caterpillar and is almost certainly a data extraction artifact; any contribution from this feature should be treated as unreliable. (*gross_margin = 0.9992750299604966*)
- Debt-to-equity of 1.44 indicates meaningful but not extreme leverage; leverage features carry relatively low importance in this model, so this is unlikely to be a major score driver. (*debt_to_equity = 1.4399099352659723*)
- Liabilities at about 78.4% of assets is consistent with the leveraged balance sheet typical of a capital-intensive industrial with a financing arm; like debt-to-equity, this feature has limited influence on the score. (*liabilities_to_assets = 0.7837602069280316*)

## Declared data gaps and caveats

- Net margin and annualised ROE were not available for this company-year, so profitability features could not be assessed and the model may have imputed or ignored them.
- The reported gross margin of 99.93% is almost certainly a data quality artifact (e.g., cost-of-revenue tagging issue in the filing data) rather than a real economic figure; interpretations relying on margins should be discounted.
- The model's training universe is survivorship-biased toward companies that continued filing, which can inflate apparent signal quality.
- The model excludes Financials, and while CAT is an industrial, its captive finance segment (Cat Financial) means some balance-sheet features (leverage, liabilities-to-assets) may look atypical relative to the training distribution.
- All features are as of the filing date; the score does not incorporate any information released after the fiscal-year 2025 filing.
- With an AUC of 0.726, the model has meaningful but limited discriminative power; a high rank should prompt further research, not be treated as a forecast.

## Limitations

- XGBoost revenue-direction model used as a RANKED SCREEN (test ROC-AUC 0.726 vs 0.500 majority baseline, FY2024-25 holdout). It is NOT a calibrated classifier: at the default threshold it predicts the majority class for nearly all companies. Scores order companies by relative likelihood of revenue growth; they are not probabilities to act on.
- Universe: current S&P 500 excluding Financials; training data carries survivorship bias that tilts the base rate positive.
- All inputs are information available at the 10-K filing date only; nothing after the filing date is reflected.
- Filing-language features cover ~56% of historical company-years; qualitative text analysis depends on best-effort section parsing.
- This memo is generated by an LLM pipeline from the sources listed below. Verify against the cited filings before relying on any claim.

## Sources

- EDGAR_X.INTERMEDIATE.INT_ML_FEATURES (ticker=CAT, fiscal_year=2024)
- EDGAR_X.INTERMEDIATE.INT_ML_FEATURES (ticker=CAT, fiscal_year=2025)
- EDGAR_X.RAW.RAW_FILINGS accession 0000018230-25-000008 (10-K filed 2025-02-14, fields mdna_text / risk_factors_text)
- EDGAR_X.RAW.RAW_FILINGS accession 0000018230-26-000008 (10-K filed 2026-02-13, fields mdna_text / risk_factors_text)
- XGBoost revenue-direction model (xgboost_revenue_direction.json) scored on the FY2025 feature row from EDGAR_X.INTERMEDIATE.INT_ML_FEATURES
