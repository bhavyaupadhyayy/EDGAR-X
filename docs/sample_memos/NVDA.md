# NVDA — FY2026 research memo

*Generated 2026-06-13T01:10:17+00:00 by EDGAR-X (Claude Fable 5 pipeline). Confidence: **moderate**.*

## Summary

NVDA's FY2026 10-K reports 65% revenue growth to $215.9 billion, driven by Blackwell-led data center compute and networking, and the company-year ranks near the top of the XGBoost revenue-direction screen (score 0.9371), primarily on trailing revenue momentum and scale. However, the filing marks a decisive negative pivot on China — from constrained-but-growing in FY2025 to effective foreclosure from China's data center compute market, accompanied by a $4.5 billion H20 charge and a 3.9-point gross margin decline to 71.1%. New risk disclosures around customer concentration (22% and 14% direct customers), counterparty/financing exposure tied to large ecosystem investments (including $17.5B in private companies and a pending OpenAI partnership), energy and capital constraints on AI buildouts, and open-source model competition add forward-looking tension that the backward-looking model score cannot capture. The screen signal and qualitative disclosures are directionally consistent on realized growth, but the score should be read strictly as a relative ranking, with several model caveats (out-of-distribution feature values, survivorship bias) warranting moderated conviction.

**Model signal**: XGBoost ranked-screen score **0.9371** for FY2026. XGBoost revenue-direction model used as a RANKED SCREEN (test ROC-AUC 0.726 vs 0.500 majority baseline, FY2024-25 holdout). It is NOT a calibrated classifier: at the default threshold it predicts the majority class for nearly all companies. Scores order companies by relative likelihood of revenue growth; they are not probabilities to act on.

## Key findings

1. FY2026 revenue grew 65% to $215.9 billion, driven by data center compute and networking platforms for accelerated computing and AI, with Blackwell architectures representing the majority of Data Center revenue.
   - *source: extraction agent — “Revenue growth in fiscal year 2026 was driven by data center compute and networking platforms for accelerated computing and AI solutions. Our Blackwell architectures represented the majority of our Data Center revenue.”*
2. The company-year ranks very high on the model's screen, but this is a relative ranking with moderate discriminative power, not a forecast that revenue will grow.
   - *source: signal agent — “The model assigns a score of 0.9371, ranking this company-year very high on the screen; given an AUC of 0.726, this should be read as a strong relative ranking rather than a precise forecast that revenue will grow.”*
3. The high screen score is most likely driven by trailing revenue momentum — the model's dominant feature — which aligns with the 65% growth disclosed in the MD&A; the score therefore largely reflects realized results rather than forward visibility.
   - *source: signal agent — “Trailing one-year revenue growth of roughly 65% is the most likely primary driver of the high score, since revenue momentum dominates the model's feature importance.”*
4. The China narrative deteriorated sharply year-over-year, shifting from growth in FY2025 to effective market foreclosure in FY2026 following the April 2025 H20 license requirement and $4.5B charge — a material structural negative not reflected in the momentum-driven model score.
   - *source: comparison agent — “Current year: "we were effectively foreclosed from competing in China's data center computing/compute market"; prior year: "Our Data Center revenue in China grew in fiscal year 2025."”*
5. Gross margin compressed 3.9 points to 71.1%, attributable to the Hopper-to-Blackwell business model transition and the $4.5 billion H20 charge tied to US export license requirements for China.
   - *source: extraction agent — “Gross margins decreased to 71.1% in fiscal year 2026 from 75.0% in fiscal year 2025 as our business model transitioned from offering Hopper HGX systems to Blackwell full-scale datacenter solutions”*
6. Revenue concentration is acute and rising in disclosure prominence: two direct customers represented 22% and 14% of total revenue, with management warning that losing large customers could harm results.
   - *source: extraction agent — “For fiscal year 2026, sales to one direct customer represented 22% of total revenue and sales to another direct customer represented 14% of total revenue”*
7. FY2026 introduces a new standalone counterparty risk factor connected to the company's expanding ecosystem financing role, including financial guarantees and customer financing requests — a structural change to the risk profile versus FY2025.
   - *source: comparison agent — “Commercial arrangements expose us to counterparty risk, including customers' or partners' inability to fulfill their financial commitments”*
8. A new driver/constraint emerges around large-scale ecosystem investments, including $17.5B deployed into private companies and infrastructure funds, alongside guarantees and a pending OpenAI partnership, deepening NVIDIA's financial entanglement with its own demand base.
   - *source: comparison agent — “We invested $17.5 billion in private companies and infrastructure funds, primarily to support early‑stage startups.”*
9. The filing newly flags external infrastructure constraints — availability of data centers, energy, and capital for customers' AI buildouts — as crucial to future revenue, meaning demand realization now depends on factors outside NVIDIA's control.
   - *source: extraction agent — “The availability of data centers, energy, and capital to support the buildout of NVIDIA AI infrastructure by our customers and partners is crucial”*
10. A new competitive risk on open-source foundation models (e.g., DeepSeek, Qwen) is disclosed, with the potential to shift workloads to competitors' platforms and reduce demand.
   - *source: comparison agent — “Open-source AI is dependent on developer adoption and if deployed on our competitors’ platforms, it could reduce demand for our products and services.”*

**Confidence rationale**: The extraction and comparison agents reported no data gaps and their evidence is internally consistent (e.g., the China foreclosure and H20 charge appear in both qualitative claims and year-over-year changes, and the model's revenue and gross margin metrics match the filing's disclosed figures). However, confidence is held to moderate because of material signal-agent caveats: the score is a ranked-screen output from a model with only moderate AUC (0.726); extreme feature values (65% revenue growth, ~3.05 annualised ROE) sit far from the training distribution where tree-based models can be less reliable; the training universe is survivorship-biased toward momentum names; the macro-regime feature value was unavailable; and features reflect only filing-date information, so the score cannot incorporate the substantial new forward-looking risks (China foreclosure, counterparty exposure, energy/capital constraints, open-source competition) that the qualitative agents surfaced. This creates genuine tension between the backward-looking quantitative signal and the deteriorating disclosed risk profile.

## ⚠ Traceability warnings

- finding cites comparison but its attribution was not found in that agent's output: 'The China narrative deteriorated sharply year-over-year, shifting from growth in FY2025 to effective market foreclosure in FY2026 following the April 2025 H20 license requirement and $4.5B charge — a material structural negative not reflected in the momentum-driven model score.' (attribution: 'Current year: "we were effectively foreclosed from competing in China\'s data center computing/compute market"; prior yea')

## Year-over-year filing changes (comparison agent)

- **new_risk** (risk_factors): FY2026 adds a new standalone risk factor on counterparty exposure from commercial arrangements, financial guarantees, and requested customer financing.
  - FY2026: “Commercial arrangements expose us to counterparty risk, including customers' or partners' inability to fulfill their financial commitments”
  - FY2025: “(absent prior year)”
- **tone_shift** (risk_factors): China narrative shifts from constrained-but-growing to effective market foreclosure after the April 2025 H20 license requirement and $4.5B charge.
  - FY2026: “we were effectively foreclosed from competing in China's data center computing/compute market”
  - FY2025: “Our Data Center revenue in China grew in fiscal year 2025.”
- **new_driver** (mdna): New demand driver/constraint: availability of data centers, energy, and capital for customers' AI infrastructure buildouts is flagged as crucial to future revenue.
  - FY2026: “The availability of data centers, energy, and capital to support the buildout of NVIDIA AI infrastructure by our customers and partners is crucial”
  - FY2025: “(absent prior year)”
- **new_driver** (mdna): New driver: large-scale ecosystem investments, including $17.5B in private companies, $3.5B in guarantees, the Groq license, and a pending OpenAI partnership.
  - FY2026: “We invested $17.5 billion in private companies and infrastructure funds, primarily to support early‑stage startups.”
  - FY2025: “(absent prior year)”
- **new_risk** (risk_factors): New risk: open-source foundation models (e.g., DeepSeek, Qwen) could shift workloads to competitors' platforms and reduce demand.
  - FY2026: “Open-source AI is dependent on developer adoption and if deployed on our competitors’ platforms, it could reduce demand for our products and services.”
  - FY2025: “(absent prior year)”
- **language_drift** (risk_factors): The AI Diffusion IFR worldwide licensing regime, heavily discussed in FY2025, was rescinded; replaced by uncertainty over a successor rule, China antitrust findings, and revenue-share license terms — consistent with higher risk-word density and litigation mentions.
  - FY2026: “In May 2025, the USG announced that it would rescind the AI Diffusion IFR and implement a replacement rule.”
  - FY2025: “the IFR will, unless modified, impose a worldwide licensing requirement on all products classified under Export Control Classification Numbers”

Numeric language-feature deltas (computed by dbt, not the LLM):

- litigation_mentions: 11.0 → 12.0 (Δ 1.0)
- impairment_mentions: 9.0 → 10.0 (Δ 1.0)
- decline_mentions: 15.0 → 14.0 (Δ -1.0)
- risk_word_total: 50.0 → 51.0 (Δ 1.0)
- risk_words_per_1000: 9.264406 → 10.574331 (Δ 1.3099)

## Filing claims (extraction agent)

- [business_driver | mdna] FY2026 revenue grew 65% to $215.9 billion, driven primarily by data center compute and networking platforms for accelerated computing and AI, with Blackwell architectures representing the majority of Data Center revenue.
  - quote: “Revenue growth in fiscal year 2026 was driven by data center compute and networking platforms for accelerated computing and AI solutions. Our Blackwell architectures represented the majority of our Data Center revenue.”
- [business_driver | mdna] Data Center networking revenue grew 142% driven by the ramp of NVLink compute fabric for GB200/GB300 systems and growth of Ethernet and InfiniBand platforms.
  - quote: “Revenue from Data Center networking grew 142% driven by the introduction and continued ramp of NVLink compute fabric for GB200 and GB300 systems”
- [business_driver | mdna] Gross margin fell 3.9 points to 71.1% due to the transition from Hopper HGX systems to Blackwell full-scale datacenter solutions and a $4.5 billion H20 charge tied to US export license requirements for China.
  - quote: “Gross margins decreased to 71.1% in fiscal year 2026 from 75.0% in fiscal year 2025 as our business model transitioned from offering Hopper HGX systems to Blackwell full-scale datacenter solutions”
- [forward_looking | mdna] Management expects supply constraints to be a headwind to Gaming in the first quarter of fiscal 2027 and beyond.
  - quote: “We expect supply constraints to be a headwind to Gaming in the first quarter of fiscal 2027 and beyond.”
- [forward_looking | mdna] The company expects to increase capital expenditures in fiscal year 2027 (versus $6.1 billion in FY2026) and is finalizing an investment and partnership agreement with OpenAI, though completion is not assured.
  - quote: “We expect to increase capital expenditures in fiscal year 2027 relative to fiscal year 2026 to support the future growth of our business.”
- [stated_risk | risk_factors] Revenue is highly concentrated: one direct customer represented 22% and another 14% of FY2026 total revenue, and losing or being prevented from selling to large customers could harm results.
  - quote: “For fiscal year 2026, sales to one direct customer represented 22% of total revenue and sales to another direct customer represented 14% of total revenue”
- [stated_risk | risk_factors] US export controls have effectively foreclosed NVIDIA from China's data center compute market, helping competitors build ecosystems, with a material adverse impact unless approved products can return.
  - quote: “As of the end of fiscal year 2026, we were effectively foreclosed from competing in China's data center computing/compute market”
- [stated_risk | risk_factors] Availability of data centers, energy, and capital for customers' AI infrastructure buildouts is crucial, and shortages could delay deployments and reduce the scale of AI adoption, impacting future revenue.
  - quote: “The availability of data centers, energy, and capital to support the buildout of NVIDIA AI infrastructure by our customers and partners is crucial”
- [stated_risk | risk_factors] Long manufacturing lead times (at times over 12 months) combined with demand estimation errors have caused and could again cause supply-demand mismatches, excess inventory, and harm to financial results.
  - quote: “Significant mismatches between supply and demand have varied across our market platforms, resulted in both product shortages and excess inventory, significantly harmed our financial results and could reoccur.”

## Model-signal statements (signal agent)

- The model assigns a score of 0.9371, ranking this company-year very high on the screen; given an AUC of 0.726, this should be read as a strong relative ranking rather than a precise forecast that revenue will grow. (*xgboost_score = 0.9371*)
- Trailing one-year revenue growth of roughly 65% is the most likely primary driver of the high score, since revenue momentum dominates the model's feature importance. (*revenue_growth_1y = 0.6547353579009478*)
- Revenue of about $215.9 billion makes this one of the largest companies in the universe; company size is the model's second-tier feature, and large scale here reinforces the elevated score. (*revenue = 215938000000.0*)
- A gross margin of roughly 71% is exceptionally high, consistent with strong pricing power, though margins carry comparatively modest weight in the model. (*gross_margin = 0.7106808435754708*)
- A net margin near 56% is extraordinary and signals very high profitability, but like gross margin it is a secondary contributor to the score. (*net_margin = 0.5560253406070261*)
- Debt-to-equity of about 0.054 indicates minimal leverage; leverage features matter little to the model, so this is supportive context rather than a score driver. (*debt_to_equity = 0.05383583503398117*)
- Liabilities-to-assets of roughly 0.24 confirms a conservative balance sheet, again a low-importance feature in the model's ranking. (*liabilities_to_assets = 0.23940658501085574*)
- Annualised ROE of approximately 3.05 (about 305%) is extreme and may reflect a small equity base or annualisation effects; the model does not weight profitability ratios heavily, so this is unlikely to be a major driver of the 0.9371 score. (*roe_annualised = 3.0533335876358136*)

## Declared data gaps and caveats

- The score is a ranked-screen output, not a probability of revenue growth; with an AUC of 0.726 the model has only moderate discriminative power and high scores can still be wrong.
- The training universe is survivorship-biased: companies that delisted or failed are under-represented, which can inflate apparent signal quality for momentum-driven names.
- The model is trained ex-Financials, so cross-sector comparisons of the score outside that scope are not meaningful.
- Features reflect information only as of the filing date; subsequent developments (demand shifts, competition, macro changes) are not captured.
- Extreme values such as 65% revenue growth and a ~3.05 annualised ROE sit far from the bulk of the training distribution, where tree-based models can behave less reliably.
- No macro-regime feature value was provided in the input, so its contribution to the score cannot be assessed here despite being a known second-tier driver.

## Limitations

- XGBoost revenue-direction model used as a RANKED SCREEN (test ROC-AUC 0.726 vs 0.500 majority baseline, FY2024-25 holdout). It is NOT a calibrated classifier: at the default threshold it predicts the majority class for nearly all companies. Scores order companies by relative likelihood of revenue growth; they are not probabilities to act on.
- Universe: current S&P 500 excluding Financials; training data carries survivorship bias that tilts the base rate positive.
- All inputs are information available at the 10-K filing date only; nothing after the filing date is reflected.
- Filing-language features cover ~56% of historical company-years; qualitative text analysis depends on best-effort section parsing.
- This memo is generated by an LLM pipeline from the sources listed below. Verify against the cited filings before relying on any claim.

## Sources

- EDGAR_X.INTERMEDIATE.INT_ML_FEATURES (ticker=NVDA, fiscal_year=2025)
- EDGAR_X.INTERMEDIATE.INT_ML_FEATURES (ticker=NVDA, fiscal_year=2026)
- EDGAR_X.RAW.RAW_FILINGS accession 0001045810-25-000023 (10-K filed 2025-02-26, fields mdna_text / risk_factors_text)
- EDGAR_X.RAW.RAW_FILINGS accession 0001045810-26-000021 (10-K filed 2026-02-25, fields mdna_text / risk_factors_text)
- XGBoost revenue-direction model (xgboost_revenue_direction.json) scored on the FY2026 feature row from EDGAR_X.INTERMEDIATE.INT_ML_FEATURES
