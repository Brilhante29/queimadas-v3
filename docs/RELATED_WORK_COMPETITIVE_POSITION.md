# FireCast related-work benchmark and competitive position

Updated: 2026-07-13.

## Purpose

This document defines how FireCast can honestly compete with recent wildfire ML
papers without fabricating cross-dataset metric comparisons.  AUC, AP, IoU,
precision/recall and WAPE are not interchangeable across labels, prevalence,
spatial resolution, horizons or sampling protocols.  FireCast should claim a win
only when the evaluation axis is actually comparable.

The strongest publishable claim is not "largest neural network".  It is:

> FireCast is a leakage-controlled, production-audited, municipality-month active
> fire count forecasting system for Northeast Brazil, with calibrated intervals,
> a statistical noise-floor audit, prospective reality scoring, fail-closed
> serving and mechanically verified LLM-XAI.

## Literature map

| Work | Task | Reported strength | FireCast position |
|---|---|---|---|
| Prapas et al. 2021, Deep Learning Methods for Daily Wildfire Danger Forecasting | Greece, next-day fire danger classification on 1 km daily grid | ConvLSTM AUROC 0.926; careful temporal split; open datacube | Do not compare WAPE to AUROC. FireCast competes by forecasting counts, exposing calibrated intervals and closing serving/governance gaps that the paper names as future needs: uncertainty and explainability. |
| WISP 2026, Set Prediction for Next-Day Active Fire Forecasting | Global next-day active-fire cluster centers at 375 m | AP 38.2%, FRP-mass coverage 53.4%, 5 km localization 54.1% | WISP is stronger for high-resolution point localization. FireCast should not claim to beat it there. FireCast is stronger for municipal operational count accounting, reality-year aggregate accuracy and fail-closed deployment. |
| Anastasiou et al. 2025, Wildfire spread forecasting with Deep Learning | Final burned-area extent after ignition | Multi-day context improves F1 and IoU by about 5% over ignition-day baseline | Different post-ignition spread task. FireCast competes on pre-season/monthly planning before individual ignitions exist. |
| Yu et al. 2025/2026, Denoising Diffusion Surrogate for Wildfire Spread | Probabilistic fire-spread surrogate | Ensemble-like spread distributions instead of one deterministic spread map | Different spread physics/surrogate task. FireCast can cite it to justify uncertainty, but should not claim spread superiority. |
| Cheerala et al. 2025, RF+SHAP wildfire susceptibility | California susceptibility/risk mapping | RF with SHAP, high random-split AUC, lower spatial/temporal transfer values | FireCast can beat the XAI safety bar: SHAP is post-hoc attribution, while FireCast's champion attribution is exact and the LLM narrative is mechanically numeric-verified. |
| Padua et al. 2026, Cerrado retrospective covariate benchmark | Brazil Cerrado daily active-fire detection/ranking | INPE AQUA_M-T, time-series CV, spatial holdouts, AUC-PR primary; explicitly retrospective because same-day covariates appear | Strong Brazilian comparator. FireCast beats on prospective as-of semantics for the served forecast and production packaging; does not beat daily ranking scope unless evaluated on the same task. |
| Tavares and Olinda 2024, Amazon LSTM/GRU active-fire time series | Amazon monthly aggregate time-series forecasting | Deep recurrent model captures seasonality in AQUA_M-T monthly counts | FireCast competes by municipal decomposition, explicit baselines, noise-floor audit, reality scoring and serving contract, not by claiming a lower error on a different regional aggregate. |
| Pereira et al. 2021, Landsat-8 active fire detection | Pixel/image active-fire detection | Large 10-band Landsat dataset; best combination 87.2% precision and 92.4% recall | Detection, not forecasting. FireCast should cite as complementary label/data line, not as a model to beat in monthly forecasting. |
| Jain et al. 2020 review | Scoping review across wildfire ML | ML has many domains; domain expertise and relevant high-quality data remain essential | Supports FireCast's research framing: simple model with rigorous data contracts can be more credible than complex architecture without operational validation. |

## Beating criteria FireCast can defend

| Criterion | FireCast evidence | Claim level |
|---|---|---|
| Prospective/as-of forecasting | target-month leakage controls, lagged target features, G0/G1 gates, `DATA_SOURCES_AND_IPI.md` | Strong |
| Municipal-month count forecast | `climatology_regional_intensity12`, WAPE/MAE/count metrics and aggregate G3 v2 | Strong for this scope |
| Baseline superiority | EXP-10: WAPE 0.6430 vs 0.7906 baseline; bootstrap delta CI95 [-0.2195, -0.0852] | Strong |
| Reality-year aggregate accuracy | 2025 AQUA_M-T error 79.016; 2026 Jan-Jun error 43.564 | Strong but scope-limited |
| Noise-floor audit | EXP-25 Poisson/NB floor and INPE-FIRMS disagreement quantify practical irreducible noise | Novel/strong |
| Negative-result ledger | EXP-12..24 and EXP-28 record rejected regressions, classification, clustering, FIRMS, IBGE, NDVI, INMET and refresh attempts | Strong research hygiene |
| Calibrated uncertainty | G5 guarded conformal coverage 0.9170 overall, 0.9000 dry, 0.9274 wet | Strong |
| XAI safety | Exact glass-box attribution plus LLM numeric guard; hallucinated number rejected by test | Strong and differentiated |
| Production readiness | API fail-closed, artifact hash, train-serving identity, container `serving-test`, monthly ops, rollback | Strong internal-production claim |
| High-resolution daily localization | Not the FireCast task | No claim |
| Fire spread/IoU | Not the FireCast task | No claim |
| Cross-biome generalization | Not yet validated beyond current scope | No claim |

## Paper positioning

Recommended title direction:

> FireCast: Noise-Floor-Aware and LLM-Verified Forecasting of Monthly Active Fire Counts in Northeast Brazil

Recommended main contributions:

1. A prospective, municipality-month active-fire count forecasting protocol for
   Ceará/Chapada using real INPE AQUA_M-T aligned targets and strict as-of rules.
2. A deliberately simple champion that beats climatology baselines over 120
   walk-forward cuts and passes aggregate/ranking gates without using 2025/2026
   for selection.
3. A noise-floor audit showing why municipal-month WAPE targets below the
   observed measurement/dispersion floor are scientifically misleading.
4. A negative-results ledger across regression, classification, clustering,
   spatial kernels, FIRMS, IBGE, NDVI, INMET and operational refresh variants.
5. Calibrated finite-sample uncertainty and a fail-closed serving contract.
6. LLM-XAI as verified narration only: exact attribution first, narrative second,
   numeric hallucination rejected mechanically.

## Claims to avoid

- Do not say FireCast is better than WISP for point localization.
- Do not compare FireCast WAPE directly to AUROC/AP/IoU from classification or
  spread papers.
- Do not claim external production approval while shadow alerts remain open.
- Do not claim municipal-month magnitude is precise; it is intentionally
  informational under G3 v2 because EXP-25 measured the noise floor.
- Do not claim LLM reasoning improves prediction; it improves explanation safety.

## Sources consulted

- Prapas et al., Deep Learning Methods for Daily Wildfire Danger Forecasting, arXiv:2111.02736, https://arxiv.org/abs/2111.02736
- Bai et al., Set Prediction for Next-Day Active Fire Forecasting, arXiv:2605.10298, https://arxiv.org/abs/2605.10298
- Anastasiou et al., Wildfire spread forecasting with Deep Learning, arXiv:2505.17556, https://arxiv.org/abs/2505.17556
- Yu et al., A Probabilistic Approach to Wildfire Spread Prediction Using a Denoising Diffusion Surrogate Model, arXiv:2507.00761, https://arxiv.org/abs/2507.00761
- Cheerala et al., Probabilistic Wildfire Susceptibility from Remote Sensing Using Random Forests and SHAP, arXiv:2511.11680, https://arxiv.org/abs/2511.11680
- Padua et al., A Retrospective Benchmark of Spatiotemporal Covariates for Daily Active-Fire Detection in Cerrado Conservation Units, arXiv:2606.04170, https://arxiv.org/abs/2606.04170
- Tavares and Olinda, Neural Networks with LSTM and GRU in Modeling Active Fires in the Amazon, arXiv:2409.02681, https://arxiv.org/abs/2409.02681
- Pereira et al., Active Fire Detection in Landsat-8 Imagery, arXiv:2101.03409, https://arxiv.org/abs/2101.03409
- Jain et al., A review of machine learning applications in wildfire science and management, arXiv:2003.00646, https://arxiv.org/abs/2003.00646