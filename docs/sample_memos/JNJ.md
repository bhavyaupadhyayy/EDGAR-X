# JNJ — FY2025 research memo

*Generated 2026-06-12T21:01:29+00:00 by EDGAR-X (Claude Fable 5 pipeline). Confidence: **moderate**.*

## Summary

JNJ's FY2025 10-K shows worldwide sales rising 6.0% to $94.2 billion on strong volume growth, led by Oncology (+22.1%) and MedTech Cardiovascular (+15.8%), while the realized STELARA biosimilar erosion cut roughly 6.2 points from worldwide operational growth. The filing introduces material new items: the planned Orthopaedics separation (targeted within 18-24 months of the October 2025 announcement), the $14.5 billion Intra-Cellular (CAPLYTA) acquisition funded partly with new debt, Medicare Part D/IRA pricing headwinds, tariffs on MedTech costs, and expected OPSUMIT generic competition in 2026. Litigation tone improved markedly, with a ~$7.0 billion talc reserve reversal versus a $5.1 billion FY2024 charge, and overall risk-word density in the filing declined modestly. The XGBoost ranked-screen score of 0.9118 places JNJ near the top of the screen, most plausibly driven by its ~6% revenue momentum and very large scale; this is a relative prioritization signal, not a forecast, and forward-looking pricing and exclusivity pressures flagged in the filing are not reflected in it.

**Model signal**: XGBoost ranked-screen score **0.9118** for FY2025. XGBoost revenue-direction model used as a RANKED SCREEN (test ROC-AUC 0.726 vs 0.500 majority baseline, FY2024-25 holdout). It is NOT a calibrated classifier: at the default threshold it predicts the majority class for nearly all companies. Scores order companies by relative likelihood of revenue growth; they are not probabilities to act on.

## Key findings

1. FY2025 worldwide sales grew 6.0% to $94.2 billion, driven primarily by volume growth (8.4%) partially offset by negative price impact (-3.1%), with acquisitions/divestitures (CAPLYTA, Shockwave) adding 1.1 points.
   - *source: extraction agent — “In 2025, worldwide sales increased 6.0% to $94.2 billion as compared to an increase of 4.3% in 2024.”*
2. STELARA biosimilar erosion shifted from an anticipated risk in the FY2024 filing to a realized, quantified drag in FY2025, reducing worldwide operational sales growth by approximately 6.2 percentage points, and management expects continued biosimilar launches to keep pressuring sales.
   - *source: comparison agent — “Current year: 'the negative impact of the STELARA sales decline, due to biosimilar competition, was approximately 6.2%, 7.6% and 4.4% on worldwide, U.S. and international'; prior year: 'the Company expects continued launches of biosimilar versions of STELARA in Europe and the United States in 2025 which will impact the Company's sales'”*
3. The XGBoost ranked-screen score of 0.9118 places JNJ near the top of the screen; per the model's feature hierarchy this likely reflects positive revenue momentum plus very large scale, and it should be read as a relative ranking signal, not a probability of growth.
   - *source: signal agent — “A score of 0.9118 places this company-year near the top of the model's ranked screen, indicating the model sees a profile it associates with favorable revenue direction relative to peers — not a 91% chance of growth. (xgboost_score = 0.9118; revenue_growth_1y = 0.06048119251078021; revenue = 94193000000.0)”*
4. The Company announced its intention to separate its Orthopaedics business within 18-24 months of the October 2025 announcement; this appears as an entirely new risk-factor category in FY2025, with explicit caution that the separation may not be completed on contemplated terms or timeline.
   - *source: comparison agent — “The planned separation of the Company's Orthopaedics business may not be completed on the terms or timeline currently contemplated, if at all”*
5. Talc litigation tone reversed materially: a $5.1 billion FY2024 charge became a ~$7.0 billion reserve reversal in FY2025, with the talc reserve falling from ~$11.6 billion to ~$3.4 billion, though the Company remains a defendant in numerous talc lawsuits with potential payments exceeding accruals.
   - *source: comparison agent — “Current year: 'The fiscal year 2025 includes the reversal of approximately $7.0 billion, a significant portion of the previously accrued talc reserve'; prior year: 'charges for talc matters of approximately $5.1 billion and $7.0 billion, respectively'”*
6. Growth was led by Oncology, up 22.1% to $25.4 billion on DARZALEX share gains, CARVYKTI capacity expansion, and launches of TECVAYLI, TALVEY and RYBREVANT/LAZCLUZE, alongside MedTech Cardiovascular up 15.8% on electrophysiology, Abiomed Impella, and Shockwave.
   - *source: extraction agent — “Strong sales of DARZALEX (daratumumab) were driven by continued share gains and market growth.”*
7. The $14.5 billion Intra-Cellular Therapies (CAPLYTA) acquisition, which closed April 2, 2025, is a new growth driver and the cause of higher debt in FY2025.
   - *source: comparison agent — “The net proceeds from this offering were used to fund the Intra-Cellular Therapies, Inc. acquisition for approximately $14.5 billion which closed on April 2, 2025”*
8. Pricing and cost headwinds are intensifying: the IRA subjects certain products to government-established pricing beginning in 2026, Medicare Part D redesign newly appears across FY2025 MD&A as a pricing headwind (price contributed -3.1% to sales growth), and tariffs are newly cited as raising MedTech cost of products sold.
   - *source: extraction agent — “the Inflation Reduction Act of 2022 (IRA) has changed Medicare Part D benefit design and has subjected certain of the Company's products to government-established pricing beginning in 2026”*
9. FY2025 newly flags expected generic competition for OPSUMIT in 2026 as a likely significant reduction in future sales, extending the exclusivity-loss pattern beyond STELARA.
   - *source: comparison agent — “The Company expects generic competition for OPSUMIT in 2026, which would likely result in a significant reduction in future sales”*
10. Aggregate filing risk language eased modestly year-over-year, with risk_word_total falling from 57 to 53 and risk_words_per_1000 from 6.285 to 6.032, consistent with the condensing of geopolitical-conflict discussion in FY2025 MD&A.
   - *source: comparison agent — “risk_word_total: prior_value 57.0, current_value 53.0, delta -4.0; risk_words_per_1000: prior_value 6.285147, current_value 6.032324, delta -0.2528 (EDGAR_X.INTERMEDIATE.INT_ML_FEATURES, computed by dbt, not by the LLM)”*

**Confidence rationale**: The three specialist outputs are mutually consistent — the filing-derived 6.0% sales growth aligns with the model's revenue_growth_1y of ~6%, and the qualitative narrative (volume-driven growth, realized STELARA erosion, improved litigation tone) coheres across extraction and comparison. However, confidence is held at moderate because: (1) the extraction agent could not verify legal accruals (Note 19), tax (Note 8), or borrowings (Note 7) detail; (2) the comparison agent notes COVID-19 vaccine product detail was folded into another line, limiting one YoY comparison, and per-section attribution of risk-word declines is inferred; (3) the signal agent's score is a ranked-screen output with AUC 0.726, carries survivorship-bias and macro-attribution caveats, an anomalous ROE figure that should not be read at face value, and reflects only filing-date features — it does not capture the forward-looking STELARA, OPSUMIT, and IRA pricing pressures that the filing itself flags as material headwinds, creating modest tension between the high screen rank and the qualitative outlook.

## ⚠ Traceability warnings

- finding cites comparison but its attribution was not found in that agent's output: 'STELARA biosimilar erosion shifted from an anticipated risk in the FY2024 filing to a realized, quantified drag in FY2025, reducing worldwide operational sales growth by approximately 6.2 percentage points, and management expects continued biosimilar launches to keep pressuring sales.' (attribution: "Current year: 'the negative impact of the STELARA sales decline, due to biosimilar competition, was approximately 6.2%, ")
- finding cites comparison but its attribution was not found in that agent's output: 'Talc litigation tone reversed materially: a $5.1 billion FY2024 charge became a ~$7.0 billion reserve reversal in FY2025, with the talc reserve falling from ~$11.6 billion to ~$3.4 billion, though the Company remains a defendant in numerous talc lawsuits with potential payments exceeding accruals.' (attribution: "Current year: 'The fiscal year 2025 includes the reversal of approximately $7.0 billion, a significant portion of the pr")
- finding cites comparison but its attribution was not found in that agent's output: 'Aggregate filing risk language eased modestly year-over-year, with risk_word_total falling from 57 to 53 and risk_words_per_1000 from 6.285 to 6.032, consistent with the condensing of geopolitical-conflict discussion in FY2025 MD&A.' (attribution: 'risk_word_total: prior_value 57.0, current_value 53.0, delta -4.0; risk_words_per_1000: prior_value 6.285147, current_va')

## Year-over-year filing changes (comparison agent)

- **new_risk** (risk_factors): FY2025 adds an entirely new risk-factor category covering the planned separation of the Orthopaedics business announced in October 2025.
  - FY2025: “The planned separation of the Company's Orthopaedics business may not be completed on the terms or timeline currently contemplated, if at all”
  - FY2024: “(absent prior year)”
- **tone_shift** (mdna): STELARA biosimilar erosion shifts from a forward-looking warning in FY2024 to a realized, quantified major sales drag in FY2025.
  - FY2025: “the negative impact of the STELARA sales decline, due to biosimilar competition, was approximately 6.2%, 7.6% and 4.4% on worldwide, U.S. and international”
  - FY2024: “the Company expects continued launches of biosimilar versions of STELARA in Europe and the United States in 2025 which will impact the Company's sales”
- **new_driver** (mdna): The Intra-Cellular Therapies acquisition (CAPLYTA) is a new growth driver and the cause of higher debt in FY2025.
  - FY2025: “The net proceeds from this offering were used to fund the Intra-Cellular Therapies, Inc. acquisition for approximately $14.5 billion which closed on April 2, 2025”
  - FY2024: “(absent prior year)”
- **new_driver** (mdna): Medicare Part D redesign newly appears throughout FY2025 MD&A as a pricing headwind across multiple products, with price contributing -3.1% to sales growth.
  - FY2025: “Growth of ERLEADA (apalutamide) was primarily due to continued share gains and market growth partially offset by the impact of Medicare Part D redesign”
  - FY2024: “(absent prior year)”
- **new_driver** (mdna): Tariffs are newly cited in FY2025 MD&A as a driver of higher MedTech cost of products sold.
  - FY2025: “Tariffs, unfavorable transactional currency and macroeconomic factors in the MedTech business”
  - FY2024: “(absent prior year)”
- **tone_shift** (mdna): Talc litigation tone reverses: a $5.1B charge in FY2024 becomes a $7.0B reserve reversal in FY2025, and the talc reserve falls from ~$11.6B to ~$3.4B.
  - FY2025: “The fiscal year 2025 includes the reversal of approximately $7.0 billion, a significant portion of the previously accrued talc reserve”
  - FY2024: “charges for talc matters of approximately $5.1 billion and $7.0 billion, respectively”
- **new_risk** (mdna): FY2025 newly flags expected generic competition for OPSUMIT in 2026 and biosimilar threats to SIMPONI as likely significant future sales reductions.
  - FY2025: “The Company expects generic competition for OPSUMIT in 2026, which would likely result in a significant reduction in future sales”
  - FY2024: “(absent prior year)”
- **language_drift** (mdna): Dedicated Russia-Ukraine and Middle East discussions in FY2024 MD&A are condensed to a generic regional-conflicts statement in FY2025, consistent with lower risk-word and decline-mention counts.
  - FY2025: “The long-term implications of regional conflicts on the Company are difficult to predict. The financial impact of known existing conflicts in the fiscal 2025 was not material.”
  - FY2024: “Although the long-term implications of Russia's invasion of Ukraine are difficult to predict at this time, the financial impact of the conflict in the fiscal year 2024”

Numeric language-feature deltas (computed by dbt, not the LLM):

- litigation_mentions: 22.0 → 21.0 (Δ -1.0)
- decline_mentions: 15.0 → 12.0 (Δ -3.0)
- risk_word_total: 57.0 → 53.0 (Δ -4.0)
- risk_words_per_1000: 6.285147 → 6.032324 (Δ -0.2528)

## Filing claims (extraction agent)

- [business_driver | mdna] Worldwide sales grew 6.0% to $94.2 billion in 2025, driven primarily by volume growth (8.4%) partially offset by negative price impact (-3.1%).
  - quote: “In 2025, worldwide sales increased 6.0% to $94.2 billion as compared to an increase of 4.3% in 2024.”
- [business_driver | mdna] STELARA sales declined sharply due to biosimilar competition, reducing worldwide operational sales growth by approximately 6.2 percentage points in 2025.
  - quote: “the negative impact of the STELARA sales decline, due to biosimilar competition, was approximately 6.2%, 7.6% and 4.4% on worldwide, U.S. and international operational sales, respectively.”
- [business_driver | mdna] Acquisitions and divestitures contributed a positive 1.1% to worldwide sales growth in 2025, mainly from the CAPLYTA (Intra-Cellular) and Shockwave acquisitions.
  - quote: “The net impact of acquisitions and divestitures on the worldwide sales growth was a positive impact of 1.1% in 2025, primarily related to CAPLYTA and Shockwave”
- [business_driver | mdna] Oncology sales grew 22.1% to $25.4 billion, led by DARZALEX share gains and market growth, CARVYKTI capacity expansion, and ongoing launches of TECVAYLI, TALVEY and RYBREVANT/LAZCLUZE.
  - quote: “Strong sales of DARZALEX (daratumumab) were driven by continued share gains and market growth.”
- [business_driver | mdna] MedTech Cardiovascular franchise sales grew 15.8%, driven by electrophysiology procedure growth, strong Impella adoption at Abiomed, and Shockwave's Coronary and Peripheral portfolios.
  - quote: “The Cardiovascular franchise achieved sales of $8.9 billion in 2025, representing an increase of 15.8% from 2024.”
- [forward_looking | mdna] Management expects continued global launches of STELARA biosimilars to keep negatively impacting STELARA sales.
  - quote: “The Company expects continued launches of biosimilar versions of STELARA globally which will continue to negatively impact the Company’s sales of STELARA.”
- [forward_looking | mdna] Management expects generic competition for OPSUMIT beginning in 2026, which would likely cause a significant reduction in future sales.
  - quote: “The Company expects generic competition for OPSUMIT in 2026, which would likely result in a significant reduction in future sales.”
- [forward_looking | mdna] The Company announced its intention to separate its Orthopaedics business, targeting completion within 18 to 24 months of the October 2025 announcement.
  - quote: “The Company intends to explore multiple paths to effect the planned separation with a targeted completion within 18 to 24 months after the initial announcement.”
- [stated_risk | risk_factors] Loss of patent exclusivity in the Innovative Medicine business is typically followed by substantial sales declines as generic and biosimilar competitors enter the market.
  - quote: “loss of patent exclusivity for a product often is followed by a substantial reduction in sales as competitors gain regulatory approval for generic, biosimilar and other competing products”
- [stated_risk | risk_factors] The Inflation Reduction Act subjects certain of the Company's products to government-established pricing beginning in 2026, creating pricing pressure on U.S. Innovative Medicine sales.
  - quote: “the Inflation Reduction Act of 2022 (IRA) has changed Medicare Part D benefit design and has subjected certain of the Company's products to government-established pricing beginning in 2026”
- [stated_risk | risk_factors] The Company faces significant litigation exposure, notably numerous talc-related lawsuits, where payments could exceed accruals and materially affect results in a given period.
  - quote: “the Company is a defendant in numerous lawsuits arising out of the use of body powders containing talc, primarily JOHNSON’S Baby Powder.”
- [stated_risk | risk_factors] The planned Orthopaedics separation may not be completed on the contemplated terms or timeline, and the Company may not achieve the expected strategic and financial benefits.
  - quote: “There can be no assurance regarding the ultimate timing of the planned separation or that such separation will be completed.”

## Model-signal statements (signal agent)

- A score of 0.9118 places this company-year near the top of the model's ranked screen, indicating the model sees a profile it associates with favorable revenue direction relative to peers — not a 91% chance of growth. (*xgboost_score = 0.9118*)
- One-year revenue growth of roughly 6% (0.06048119251078021) is positive momentum, and revenue momentum is the model's dominant feature, making this the most plausible primary driver of the high score. (*revenue_growth_1y = 0.06048119251078021*)
- Revenue of 94,193,000,000 makes JNJ one of the largest companies in the universe; company size is the model's second-most-important feature group, and very large scale likely reinforces the high ranking. (*revenue = 94193000000.0*)
- A gross margin of about 67.9% (0.6787871710212011) signals strong pricing power and product economics, consistent with the high score, though margins carry less weight in this model than momentum and size. (*gross_margin = 0.6787871710212011*)
- A net margin near 28.5% (0.2845646704107524) reflects robust bottom-line profitability; this is a supportive but secondary signal given the model's feature importance ordering. (*net_margin = 0.2845646704107524*)
- Debt-to-equity of about 0.51 (0.5081673697635632) indicates moderate leverage; leverage features matter less in this model, so this likely had limited influence on the score either way. (*debt_to_equity = 0.5081673697635632*)
- Liabilities-to-assets of roughly 0.59 (0.5906631193213192) shows a balance sheet that is somewhat liability-heavy but not unusual for a mature large-cap; again, a low-weight feature in this model. (*liabilities_to_assets = 0.5906631193213192*)
- Annualised ROE of about 131% (1.3148238987540468) is extremely high and likely reflects a relatively small equity base or an annualisation artifact rather than a clean profitability read; the model weights such ratios lightly in any case. (*roe_annualised = 1.3148238987540468*)

## Declared data gaps and caveats

- Detailed legal proceeding outcomes and accrual amounts are referenced to Note 19 of the Consolidated Financial Statements, which was not included in the provided sections.
- Tax detail (Note 8) and borrowings detail (Note 7) referenced in MD&A were not provided, so claims rely only on the summarized MD&A figures.
- COVID-19 vaccine product-level detail was folded into 'Other Infectious Diseases' in FY2025, limiting direct year-over-year comparison for that line.
- Numeric deltas were provided in aggregate; per-section (MD&A vs risk factors) attribution of the risk-word decline is inferred, not given.
- The score is a ranked-screen output, not a probability: with an AUC of 0.726, the model meaningfully separates likely growers from non-growers in aggregate but is far from precise at the individual company level.
- The training universe is survivorship-biased toward companies that continued filing, which can inflate apparent signal quality for large, stable firms like JNJ.
- The model was trained excluding Financials; JNJ is in scope, but cross-sector calibration may still vary.
- All features are as of the filing date only — subsequent events, guidance changes, or macro shifts are not reflected in the score.
- The annualised ROE of 1.3148238987540468 (over 130%) is anomalously high and may stem from annualisation mechanics or a compressed equity base; it should not be read at face value.
- Macro-regime features influence the score but their specific values were not provided here, so their contribution cannot be attributed.

## Limitations

- XGBoost revenue-direction model used as a RANKED SCREEN (test ROC-AUC 0.726 vs 0.500 majority baseline, FY2024-25 holdout). It is NOT a calibrated classifier: at the default threshold it predicts the majority class for nearly all companies. Scores order companies by relative likelihood of revenue growth; they are not probabilities to act on.
- Universe: current S&P 500 excluding Financials; training data carries survivorship bias that tilts the base rate positive.
- All inputs are information available at the 10-K filing date only; nothing after the filing date is reflected.
- Filing-language features cover ~56% of historical company-years; qualitative text analysis depends on best-effort section parsing.
- This memo is generated by an LLM pipeline from the sources listed below. Verify against the cited filings before relying on any claim.

## Sources

- EDGAR_X.INTERMEDIATE.INT_ML_FEATURES (ticker=JNJ, fiscal_year=2024)
- EDGAR_X.INTERMEDIATE.INT_ML_FEATURES (ticker=JNJ, fiscal_year=2025)
- EDGAR_X.RAW.RAW_FILINGS accession 0000200406-25-000038 (10-K filed 2025-02-13, fields mdna_text / risk_factors_text)
- EDGAR_X.RAW.RAW_FILINGS accession 0000200406-26-000016 (10-K filed 2026-02-11, fields mdna_text / risk_factors_text)
- XGBoost revenue-direction model (xgboost_revenue_direction.json) scored on the FY2025 feature row from EDGAR_X.INTERMEDIATE.INT_ML_FEATURES
