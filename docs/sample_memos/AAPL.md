# AAPL — FY2025 research memo

*Generated 2026-06-12T20:20:06+00:00 by EDGAR-X (Claude Fable 5 pipeline). Confidence: **moderate**.*

## Summary

Apple's FY2025 10-K shows steady top-line performance — total net sales up 6% with Services up 14% — but the filing pivots sharply toward trade-policy risk, with a new tariff section in MD&A and tariff costs cited for the first time as an actual drag on Products gross margin. Greater China was the only declining segment, and management explicitly expects gross margins to remain under downward pressure. New risk-factor disclosures cover the Google antitrust remedies threatening search-licensing revenue, AI copyright-training exposure, and online-safety regulation, while the effective tax rate fell to 15.6% as the prior-year State Aid charge resolved out. The XGBoost ranked screen places AAPL near the top (score 0.9081), most plausibly driven by positive revenue momentum and very large scale, but this is a relative ranking signal — not a prediction — and it sits in mild tension with the filing's newly disclosed margin and regulatory pressures.

**Model signal**: XGBoost ranked-screen score **0.9081** for FY2025. XGBoost revenue-direction model used as a RANKED SCREEN (test ROC-AUC 0.726 vs 0.500 majority baseline, FY2024-25 holdout). It is NOT a calibrated classifier: at the default threshold it predicts the majority class for nearly all companies. Scores order companies by relative likelihood of revenue growth; they are not probabilities to act on.

## Key findings

1. Tariffs have moved from absent in FY2024 to an actual, quantified driver of margin compression in FY2025: the filing now attributes the decline in Products gross margin percentage to product mix and tariff costs, whereas the prior year credited margin gains to cost savings. This is the single most important year-over-year change in the filing.
   - *source: comparison agent — “Products gross margin percentage decreased during 2025 compared to 2024 primarily due to a different mix of products and tariff costs”*
2. FY2025 adds an entirely new MD&A section and risk language on U.S. tariffs covering imports from China, India, Japan, South Korea, Taiwan, Vietnam and the EU; per the extraction agent, the company states the ultimate impact on supply chain, pricing and gross margin remains uncertain. This aligns with the +3 rise in 'uncertain' mentions flagged by the comparison agent.
   - *source: comparison agent — “Beginning in the second quarter of 2025, new U.S. Tariffs were announced, including additional tariffs on imports from China, India, Japan, South Korea, Taiwan, Vietnam and the EU”*
3. The model's ranked screen places AAPL near the top of its universe with a score of 0.9081, most plausibly driven by positive revenue momentum (~6.4% growth) and very large company size — the two most heavily weighted feature families. This is a relative ranking signal with moderate discriminative power (test ROC-AUC 0.726), not a probability that revenue will grow.
   - *source: signal agent — “xgboost_score: 0.9081”*
4. Underlying business momentum is positive and mix-shifting toward higher-margin recurring revenue: total net sales grew 6%, iPhone rose 4% on Pro-model strength, and Services was the fastest-growing category at 14%, driven by advertising, the App Store and cloud services.
   - *source: extraction agent — “Services net sales increased during 2025 compared to 2024 primarily due to higher net sales from advertising, the App Store and cloud services.”*
5. Greater China was the only segment to decline in FY2025, falling 4% primarily on lower iPhone sales — a geographic soft spot that compounds the trade-policy and supply-chain concentration risks elsewhere in the filing.
   - *source: extraction agent — “Greater China net sales decreased during 2025 compared to 2024 primarily due to lower net sales of iPhone, partially offset by higher net sales of Mac.”*
6. Management itself guides to continued margin pressure, stating that gross margins will be subject to volatility and downward pressure — consistent with the tariff drag already observed in FY2025 and a counterweight to the favorable model screen.
   - *source: extraction agent — “the Company believes, in general, gross margins will be subject to volatility and downward pressure.”*
7. FY2025 adds a specific, escalated risk from the Google antitrust ruling: ordered remedies could materially reduce the search-licensing revenue Apple earns on its platforms, upgrading what was generic 'government investigations' language in FY2024. This directly threatens a component of the high-growth Services segment.
   - *source: comparison agent — “On August 5, 2024, Google was found to have violated U.S. antitrust laws... on September 2, 2025, the U.S. District Court for the District of Columbia ("D.C. District Court") ordered certain remedies.”*
8. The effective tax rate fell to 15.6% from 24.1%, largely a non-operating effect: the FY2024 one-time State Aid charge resolved out, producing a $10.7 billion year-over-year decrease in the tax provision. Analysts should treat the resulting earnings uplift as non-recurring.
   - *source: extraction agent — “a $10.7 billion year-over-year decrease in the provision for income taxes related to the State Aid Decision”*
9. FY2025 introduces a new intellectual-property risk around AI/ML copyright-training infringement, absent from FY2024 — one of several newly disclosed regulatory exposures (alongside online-safety/age-verification laws and ongoing DMA compliance challenges).
   - *source: comparison agent — “exacerbated by the use of new and emerging technologies, including machine learning and artificial intelligence, which can involve, among other things, the acquisition and use of copyrighted materials for training”*
10. Capital return remains a central pillar: a new $100 billion buyback was announced in May 2025 with the dividend raised to $0.26 and intended to grow annually, backed by $132.4 billion of cash and marketable securities. Note the signal agent's caveat that buyback-shrunken equity inflates the annualised ROE of 6.08, which should not be read as a standalone quality signal.
   - *source: extraction agent — “The Company intends to increase its dividend on an annual basis, subject to declaration by the Board.”*

**Confidence rationale**: The extraction and comparison agents reported no data gaps and no grounding warnings, and their narratives are mutually consistent (tariff drag, uncertainty language, State Aid resolution all corroborate across agents). Confidence is held at moderate rather than high for three reasons: (1) the signal agent's material caveats — the score is a ranked-screen output from a model with only moderate discriminative power (AUC 0.726), trained on a survivorship-biased universe, with the macro feature component unattributable from the inputs provided; (2) mild internal tension between the favorable model ranking (driven by backward-looking revenue momentum and scale) and the filing's forward-looking disclosures of tariff-driven margin pressure, Greater China weakness, and new regulatory threats to Services revenue, none of which the model can capture post-filing-date; and (3) the headline tax-rate improvement and elevated ROE both reflect non-operating distortions (State Aid resolution; buyback-shrunken equity) that flatter reported metrics.

## ⚠ Traceability warnings

- finding cites signal but its attribution was not found in that agent's output: "The model's ranked screen places AAPL near the top of its universe with a score of 0.9081, most plausibly driven by positive revenue momentum (~6.4% growth) and very large company size — the two most heavily weighted feature families. This is a relative ranking signal with moderate discriminative power (test ROC-AUC 0.726), not a probability that revenue will grow." (attribution: 'xgboost_score: 0.9081')

## Year-over-year filing changes (comparison agent)

- **new_risk** (mdna): FY2025 adds an entirely new MD&A section and risk language on U.S. tariffs and retaliatory trade measures, absent from FY2024.
  - FY2025: “Beginning in the second quarter of 2025, new U.S. Tariffs were announced, including additional tariffs on imports from China, India, Japan, South Korea, Taiwan, Vietnam and the EU”
  - FY2024: “(absent prior year)”
- **tone_shift** (mdna): Tariffs are now cited as an actual drag on Products gross margin, whereas FY2024 attributed margin movement only to cost savings and mix.
  - FY2025: “Products gross margin percentage decreased during 2025 compared to 2024 primarily due to a different mix of products and tariff costs”
  - FY2024: “Products gross margin and Products gross margin percentage increased during 2024 compared to 2023 due to cost savings”
- **new_risk** (risk_factors): FY2025 introduces AI/ML copyright-training infringement exposure as a new intellectual property risk.
  - FY2025: “exacerbated by the use of new and emerging technologies, including machine learning and artificial intelligence, which can involve, among other things, the acquisition and use of copyrighted materials for training”
  - FY2024: “(absent prior year)”
- **new_risk** (risk_factors): FY2025 adds specific risk from the Google antitrust ruling and ordered remedies threatening Apple's search licensing revenue.
  - FY2025: “On August 5, 2024, Google was found to have violated U.S. antitrust laws... on September 2, 2025, the U.S. District Court for the District of Columbia ("D.C. District Court") ordered certain remedies.”
  - FY2024: “certain of these arrangements are currently subject to government investigations and legal proceedings”
- **new_risk** (risk_factors): FY2025 adds a new risk on online safety laws, protections for minors and mandatory age verification, absent in FY2024.
  - FY2025: “new and changing laws and regulations regarding online safety, including enhanced protections for minors and mandatory age verification requirements”
  - FY2024: “(absent prior year)”
- **language_drift** (risk_factors): The ESG risk factor is rewritten to 'varied stakeholder expectations,' dropping explicit references to climate change, human rights, and diversity, equity and inclusion.
  - FY2025: “Various stakeholders, including governments, regulators, investors, employees, customers and others, have differing expectations about a wide range of social and other issues”
  - FY2024: “increasingly focused on environmental, social and governance considerations relating to businesses, including climate change and greenhouse gas emissions, human and civil rights, and diversity, equity and inclusion”
- **language_drift** (risk_factors): Manufacturing footprint language shifts from 'substantially all' outsourced abroad to a 'significant majority,' newly highlighting U.S. sourcing.
  - FY2025: “A significant majority of the Company's manufacturing is performed in whole or in part by outsourcing partners... in addition to sourcing from partners and facilities located in the U.S.”
  - FY2024: “Substantially all of the Company's manufacturing is performed in whole or in part by outsourcing partners located primarily in China mainland, India, Japan, South Korea, Taiwan and Vietnam”
- **dropped_risk** (mdna): The FY2024 one-time $10.2B State Aid tax charge driver is replaced in FY2025 by a sharply lower effective tax rate narrative.
  - FY2025: “lower compared to 2024 due to a $10.7 billion year-over-year decrease in the provision for income taxes related to the State Aid Decision”
  - FY2024: “higher than the statutory federal income tax rate due primarily to a one-time income tax charge of $10.2 billion, net, related to the State Aid Decision”

Numeric language-feature deltas (computed by dbt, not the LLM):

- impairment_mentions: 4.0 → 3.0 (Δ -1.0)
- uncertain_mentions: 16.0 → 19.0 (Δ 3.0)
- risk_word_total: 40.0 → 42.0 (Δ 2.0)
- risk_words_per_1000: 19.417476 → 17.312448 (Δ -2.105)

## Filing claims (extraction agent)

- [business_driver | mdna] Total net sales grew 6% in fiscal 2025, with iPhone net sales rising 4% driven by higher sales of Pro models.
  - quote: “iPhone net sales increased during 2025 compared to 2024 due to higher net sales of Pro models.”
- [business_driver | mdna] Services was the fastest-growing category, up 14% in 2025, driven by advertising, the App Store and cloud services.
  - quote: “Services net sales increased during 2025 compared to 2024 primarily due to higher net sales from advertising, the App Store and cloud services.”
- [business_driver | mdna] Greater China was the only segment to decline in 2025, falling 4% primarily due to lower iPhone sales, partially offset by higher Mac sales.
  - quote: “Greater China net sales decreased during 2025 compared to 2024 primarily due to lower net sales of iPhone, partially offset by higher net sales of Mac.”
- [business_driver | mdna] Tariff costs weighed on Products gross margin percentage in 2025, which decreased due to product mix and tariff costs despite otherwise favorable costs.
  - quote: “Products gross margin percentage decreased during 2025 compared to 2024 primarily due to a different mix of products and tariff costs, partially offset by other favorable costs.”
- [business_driver | mdna] The 2025 effective tax rate fell to 15.6% from 24.1%, largely due to a $10.7 billion year-over-year decrease in tax provision related to the State Aid Decision.
  - quote: “a $10.7 billion year-over-year decrease in the provision for income taxes related to the State Aid Decision”
- [forward_looking | mdna] Management expects gross margins to remain under pressure going forward.
  - quote: “the Company believes, in general, gross margins will be subject to volatility and downward pressure.”
- [forward_looking | mdna] The company believes its $132.4 billion of cash and marketable securities plus operating cash flow and debt market access will fund cash requirements and the capital return program for at least 12 months.
  - quote: “will be sufficient to satisfy its cash requirements and capital return program over the next 12 months and beyond.”
- [forward_looking | mdna] The company announced a new $100 billion share repurchase program in May 2025, raised its quarterly dividend to $0.26, and intends to increase the dividend annually.
  - quote: “The Company intends to increase its dividend on an annual basis, subject to declaration by the Board.”
- [stated_risk | risk_factors] New U.S. tariffs announced beginning in Q2 2025 (covering imports from China, India, Japan, South Korea, Taiwan, Vietnam and the EU, among others) could materially harm the supply chain, raw-material availability, pricing and gross margin, and the ultimate impact remains uncertain.
  - quote: “Beginning in the second quarter of 2025, new tariffs were announced on imports to the U.S. (“U.S. Tariffs”), including additional tariffs on imports from China, India, Japan, South Korea, Taiwan, Vietnam and the European Union (“EU”)”
- [stated_risk | risk_factors] The company is exposed to concentrated supply-chain risk because most manufacturing is performed by outsourcing partners primarily in Asia, with single-source partners for many critical components.
  - quote: “The Company relies on single-source partners in the U.S., Asia and Europe to supply and manufacture many components, and on partners primarily located in Asia, for final assembly of substantially all of the Company’s hardware products.”
- [stated_risk | risk_factors] Remedies in the Google antitrust case could materially reduce the revenue Apple earns from search-licensing arrangements on its platforms.
  - quote: “If implemented, these remedies could materially adversely affect the Company’s ability to earn revenue from such licensing arrangements.”
- [stated_risk | risk_factors] Regulatory regimes like the EU Digital Markets Act have forced changes to iOS, the App Store and Safari, carry significant fines for noncompliance, and the company's compliance plan has been challenged by the Commission.
  - quote: “Although the Company’s compliance plan is intended to address the DMA’s obligations, it has been challenged by the Commission and may be challenged further by private litigants. The DMA provides for significant fines and penalties for noncompliance.”

## Model-signal statements (signal agent)

- The xgboost_score of 0.9081 places this company-year high in the model's ranked screen; with an AUC of 0.726, this indicates a favorable relative ranking rather than a confident prediction of revenue growth. (*xgboost_score = 0.9081*)
- Trailing revenue of 416161000000.0 makes AAPL one of the largest companies the model could score; company size is the second-most important feature family, and very large scale tends to be associated with revenue stability in the training data. (*revenue = 416161000000.0*)
- One-year revenue growth of 0.06425511782832749 (about 6.4%) is positive but moderate; because revenue momentum dominates the model's feature importance, this steady positive trend is plausibly the single biggest driver of the high score. (*revenue_growth_1y = 0.06425511782832749*)
- A gross margin of 0.4690516410716045 (about 46.9%) signals strong pricing power, but margins carry relatively low feature importance in this model, so this likely contributes only modestly to the score. (*gross_margin = 0.4690516410716045*)
- A net margin of 0.2691506412181824 (about 26.9%) is exceptionally high and indicates a very profitable business, though again margin features are secondary in the model's importance ranking. (*net_margin = 0.2691506412181824*)
- Debt-to-equity of 1.229815686327696 indicates leverage exceeding the equity base, partly reflecting Apple's capital-return strategy shrinking equity; leverage features matter less to the model and likely have limited influence on the score. (*debt_to_equity = 1.229815686327696*)
- Liabilities-to-assets of 0.7947533828265705 (about 79.5%) shows a liability-heavy balance sheet, but as a low-importance feature it is unlikely to be a major driver of the 0.9081 score in either direction. (*liabilities_to_assets = 0.7947533828265705*)
- An annualised ROE of 6.076519333270042 is extremely elevated, consistent with Apple's small equity base from years of buybacks inflating the ratio; this distortion should temper any read-through, and the model does not weight return ratios heavily in any case. (*roe_annualised = 6.076519333270042*)

## Declared data gaps and caveats

- The score is a ranked-screen output, not a probability: with an AUC of 0.726, the model has only moderate discriminative power and a high score does not mean revenue growth is likely to occur.
- The training universe is survivorship-biased toward companies that continued filing, which can inflate apparent reliability of high scores.
- The model was trained ex-Financials; AAPL is in scope, but the score should not be compared against financial-sector companies.
- All features reflect information only as of the filing date; subsequent events, guidance, or macro shifts are not captured.
- The extremely high annualised ROE likely reflects a buyback-shrunken equity base rather than underlying economics, and should not be interpreted as a standalone quality signal.
- No multi-year growth, cash-flow, or macro-regime values were provided in the input, so the macro component of the score (a known feature family) cannot be attributed to a specific value here.

## Limitations

- XGBoost revenue-direction model used as a RANKED SCREEN (test ROC-AUC 0.726 vs 0.500 majority baseline, FY2024-25 holdout). It is NOT a calibrated classifier: at the default threshold it predicts the majority class for nearly all companies. Scores order companies by relative likelihood of revenue growth; they are not probabilities to act on.
- Universe: current S&P 500 excluding Financials; training data carries survivorship bias that tilts the base rate positive.
- All inputs are information available at the 10-K filing date only; nothing after the filing date is reflected.
- Filing-language features cover ~56% of historical company-years; qualitative text analysis depends on best-effort section parsing.
- This memo is generated by an LLM pipeline from the sources listed below. Verify against the cited filings before relying on any claim.

## Sources

- EDGAR_X.INTERMEDIATE.INT_ML_FEATURES (ticker=AAPL, fiscal_year=2024)
- EDGAR_X.INTERMEDIATE.INT_ML_FEATURES (ticker=AAPL, fiscal_year=2025)
- EDGAR_X.RAW.RAW_FILINGS accession 0000320193-24-000123 (10-K filed 2024-11-01, fields mdna_text / risk_factors_text)
- EDGAR_X.RAW.RAW_FILINGS accession 0000320193-25-000079 (10-K filed 2025-10-31, fields mdna_text / risk_factors_text)
- XGBoost revenue-direction model (xgboost_revenue_direction.json) scored on the FY2025 feature row from EDGAR_X.INTERMEDIATE.INT_ML_FEATURES
