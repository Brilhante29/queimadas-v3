"""EXP-10 reexecutado no escopo REAL da APA Chapada do Araripe.

Diferenca essencial em relacao ao EXP-10 original
-------------------------------------------------
O EXP-10 original calcula o fator de intensidade regional sobre o universo
elegivel do snapshot antigo -- que era o **Ceara**. Aqui o universo passa a ser
os municipios derivados da APA (CE+PE+PI). Isso muda a matematica da previsao:
o fator deixa de medir "o Ceara esta vindo mais intenso" e passa a medir "a APA
esta vindo mais intensa". Por isso o retreino e obrigatorio e nenhuma previsao
antiga pode ser reaproveitada (SDD 14).

Protocolo preservado sem afrouxamento (SDD 13, 16, 17):
- walk-forward 2015-01..2024-12 (120 cortes), treino so com passado;
- ``MIN_TRAIN_MONTHS = 60`` inalterado;
- ``TRAILING_MONTHS=12``, ``SHRINK_FIRE_COUNT=100``, ``RATIO_CLIP=[0.5, 2.0]``
  inalterados;
- 2025+ nao entra em selecao de modelo.

Decisao de promocao (SDD 19): REJECT se qualquer criterio falhar. O nome
"champion" nao e preservado por conveniencia.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.backtest_real_baselines import MIN_TRAIN_MONTHS  # noqa: E402
from src.models.baselines import ClimatologyMunicipal  # noqa: E402
from src.scopes import apa_geocodes  # noqa: E402
from src.utils.metrics import mae, wape  # noqa: E402

TARGET_SNAPSHOT = PROJECT_ROOT / "data" / "snapshots" / "inpe_apa33_satref_v1" / "municipality_month.csv"
SCOPE_CSV = PROJECT_ROOT / "data" / "reference" / "apa_chapada_araripe.csv"
OUT_DIR = PROJECT_ROOT / "outputs" / "apa33" / "exp10"

BASELINE = "climatology_municipal"
CANDIDATE = "climatology_apa_intensity12"

TEST_MONTHS = [(y, m) for y in range(2015, 2025) for m in range(1, 13)]
TRAILING_MONTHS = 12
SHRINK_FIRE_COUNT = 100.0
RATIO_CLIP = (0.5, 2.0)

CRITICAL_MONTHS = (10, 11)
DRY_MONTHS = (8, 9, 10, 11, 12)

FEATURE_COLS = ["mes", "municipio_id"]


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_apa_target() -> pd.DataFrame:
    """Carrega a etapa `load apa target` do fluxo FireCast.

    Le o alvo historico novo e recorta pelo escopo derivado da APA. Falha
    fechada se algum municipio do escopo nao existir no alvo -- nunca treina
    em cima de escopo incompleto sem avisar."""
    df = pd.read_csv(TARGET_SNAPSHOT)
    scope = apa_geocodes()

    missing = scope - set(df["geocodigo"].astype(int))
    if missing:
        raise ValueError(f"municipios do escopo ausentes do alvo (falha fechada): {sorted(missing)}")

    df = df[df["geocodigo"].astype(int).isin(scope)].copy()

    # `observed=False` significa "fonte nao validada", nunca zero (SDD 10).
    if "observed" in df.columns:
        df.loc[~df["observed"].astype(bool), "fire_count"] = np.nan

    df["period"] = pd.PeriodIndex(
        pd.to_datetime(df["ano"].astype(str) + "-" + df["mes"].astype(str).str.zfill(2)),
        freq="M",
    )
    df = df.sort_values(["geocodigo", "period"]).reset_index(drop=True)
    df["municipio_id"] = df["geocodigo"].astype("category").cat.codes
    df["fire_count_lag12"] = df.groupby("geocodigo")["fire_count"].shift(12)
    return df


def compute_cut_predictions(df: pd.DataFrame, cut: pd.Period):
    """Calcula a etapa `compute cut predictions` do fluxo FireCast.

    O fator regional e calculado **somente sobre os municipios elegiveis da
    APA** -- e essa a mudanca material em relacao ao experimento original."""
    train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()].copy()
    test = df[(df["period"] == cut) & df["fire_count"].notna()].copy()

    hist = train.groupby("geocodigo")["fire_count"].count()
    eligible = hist[hist >= MIN_TRAIN_MONTHS].index
    test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()].copy()
    if len(train) == 0 or len(test) == 0:
        return None, None

    baseline = ClimatologyMunicipal().fit(train, FEATURE_COLS, "fire_count")
    base_pred = np.asarray(baseline.predict(test), dtype=float)

    prior_periods = pd.period_range(cut - TRAILING_MONTHS, cut - 1, freq="M")
    prior = df[
        df["period"].isin(prior_periods)
        & df["geocodigo"].isin(eligible)
        & df["fire_count"].notna()
    ].copy()

    if len(prior):
        expected_12m = float(np.asarray(baseline.predict(prior), dtype=float).sum())
        observed_12m = float(prior["fire_count"].sum())
        raw_ratio = (observed_12m + SHRINK_FIRE_COUNT) / (expected_12m + SHRINK_FIRE_COUNT)
    else:
        expected_12m = observed_12m = 0.0
        raw_ratio = 1.0
    ratio = float(np.clip(raw_ratio, RATIO_CLIP[0], RATIO_CLIP[1]))
    cand_pred = np.maximum(base_pred * ratio, 0.0)

    rows = []
    for model, pred in [(BASELINE, base_pred), (CANDIDATE, cand_pred)]:
        out = test[["geocodigo", "municipio", "uf", "ano", "mes", "fire_count"]].copy()
        out["model"] = model
        out["y_pred"] = pred
        out["cut"] = str(cut)
        rows.append(out)

    ratio_row = {
        "cut": str(cut),
        "ano": int(cut.year),
        "mes": int(cut.month),
        "observed_trailing_12m": observed_12m,
        "expected_trailing_12m": expected_12m,
        "raw_ratio": float(raw_ratio),
        "applied_ratio": ratio,
        "n_eligible_municipios": int(len(eligible)),
        "n_test_rows": int(len(test)),
    }
    return pd.concat(rows, ignore_index=True), ratio_row


def block(preds: pd.DataFrame, label: str) -> dict:
    """Calcula a etapa `block` do fluxo FireCast."""
    out = {"block": label}
    for model in (BASELINE, CANDIDATE):
        sub = preds[preds["model"] == model]
        if len(sub) == 0:
            continue
        y = sub["fire_count"].to_numpy(dtype=float)
        p = sub["y_pred"].to_numpy(dtype=float)
        out[f"{model}_wape"] = float(wape(y, p))
        out[f"{model}_mae"] = float(mae(y, p))
        out[f"{model}_bias"] = float((p - y).mean())
    out["n_rows"] = int(len(preds[preds["model"] == BASELINE]))
    return out


def bootstrap_delta_by_cut(base: pd.DataFrame, cand: pd.DataFrame, n: int = 2000):
    """Calcula a etapa `bootstrap delta by cut` do fluxo FireCast.

    Reamostra CORTES (nao linhas), preservando a dependencia temporal dentro
    de cada corte."""
    cuts = sorted(base["cut"].unique())
    per_cut = {}
    skipped_undefined = []
    for c in cuts:
        b = base[base["cut"] == c]
        k = cand[cand["cut"] == c]
        if len(b) == 0 or len(k) == 0:
            continue
        # WAPE e indefinido quando o corte nao tem nenhum foco observado
        # (denominador zero). Incluir NaN aqui contamina todo o bootstrap e
        # faz o gate `ci_high >= 0` passar por acidente -- o corte tem que sair
        # explicitamente, e ser contado.
        if b["fire_count"].abs().sum() == 0:
            skipped_undefined.append(c)
            continue
        bw = wape(b["fire_count"].to_numpy(float), b["y_pred"].to_numpy(float))
        kw = wape(k["fire_count"].to_numpy(float), k["y_pred"].to_numpy(float))
        if not (np.isfinite(bw) and np.isfinite(kw)):
            skipped_undefined.append(c)
            continue
        per_cut[c] = (bw, kw)
    cuts = list(per_cut)
    rng = np.random.default_rng(42)
    deltas = []
    for _ in range(n):
        sample = rng.choice(cuts, size=len(cuts), replace=True)
        bw = np.mean([per_cut[c][0] for c in sample])
        kw = np.mean([per_cut[c][1] for c in sample])
        deltas.append(kw - bw)
    wins = sum(1 for c in cuts if per_cut[c][1] < per_cut[c][0])
    return deltas, (wins / len(cuts) if cuts else 0.0), skipped_undefined


def main() -> None:
    """Executa a etapa `main` do fluxo FireCast."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_apa_target()
    scope_n = len(apa_geocodes())

    all_preds, ratios = [], []
    for y, m in TEST_MONTHS:
        cut = pd.Period(f"{y}-{m:02d}", freq="M")
        preds, ratio_row = compute_cut_predictions(df, cut)
        if preds is None:
            continue
        all_preds.append(preds)
        ratios.append(ratio_row)

    preds = pd.concat(all_preds, ignore_index=True)
    preds.to_csv(OUT_DIR / "predictions_2015_2024.csv", index=False)
    pd.DataFrame(ratios).to_csv(OUT_DIR / "regional_ratio_by_cut.csv", index=False)

    blocks = [block(preds, "all")]
    blocks.append(block(preds[preds["mes"].isin(CRITICAL_MONTHS)], "critical_out_nov"))
    blocks.append(block(preds[preds["mes"].isin(DRY_MONTHS)], "dry_ago_dez"))
    for uf in sorted(preds["uf"].unique()):
        blocks.append(block(preds[preds["uf"] == uf], f"uf_{uf}"))
    summary = pd.DataFrame(blocks)
    summary.to_csv(OUT_DIR / "summary.csv", index=False)

    base = preds[preds["model"] == BASELINE]
    cand = preds[preds["model"] == CANDIDATE]
    deltas, win_rate, skipped_cuts = bootstrap_delta_by_cut(base, cand)
    ci_low, ci_high = float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5))

    all_block = blocks[0]
    crit_block = blocks[1]
    base_all = all_block[f"{BASELINE}_wape"]
    cand_all = all_block[f"{CANDIDATE}_wape"]
    base_crit = crit_block[f"{BASELINE}_wape"]
    cand_crit = crit_block[f"{CANDIDATE}_wape"]

    reasons = []
    # Falha fechada: metrica nao-finita nunca pode passar por acidente. Sem
    # esta guarda, `ci_high >= 0` com NaN avalia False e PROMOVE em cima de
    # estatistica quebrada.
    for label, value in (
        ("all_wape_baseline", base_all),
        ("all_wape_candidate", cand_all),
        ("critical_wape_baseline", base_crit),
        ("critical_wape_candidate", cand_crit),
        ("bootstrap_ci_low", ci_low),
        ("bootstrap_ci_high", ci_high),
    ):
        if not np.isfinite(value):
            reasons.append(f"{label} nao e finito ({value}) -- gate falha fechado")

    if cand_all >= base_all:
        reasons.append(f"candidate all_wape {cand_all:.4f} >= baseline {base_all:.4f}")
    if cand_crit > base_crit:
        reasons.append(f"candidate critical_wape {cand_crit:.4f} > baseline {base_crit:.4f}")
    if win_rate <= 0.50:
        reasons.append(f"win rate {win_rate:.3f} <= 0.50")
    if np.isfinite(ci_high) and ci_high >= 0:
        reasons.append(f"bootstrap CI95 delta [{ci_low:.4f}, {ci_high:.4f}] nao exclui zero")
    decision = "REJECT" if reasons else "PROMOTE"

    result = {
        "experiment": "EXP-10-APA",
        "scope": "apa_chapada_araripe",
        "scope_n_municipios": scope_n,
        "scope_sha256": sha256_file(SCOPE_CSV),
        "target_snapshot": str(TARGET_SNAPSHOT.relative_to(PROJECT_ROOT)),
        "target_sha256": sha256_file(TARGET_SNAPSHOT),
        "protocol": "walk-forward 2015-2024, treino so com passado, 2025+ congelado",
        "n_cuts": len(ratios),
        "hyperparameters_unchanged": {
            "trailing_months": TRAILING_MONTHS,
            "shrink_fire_count": SHRINK_FIRE_COUNT,
            "ratio_clip": list(RATIO_CLIP),
            "min_train_months": MIN_TRAIN_MONTHS,
        },
        "baseline": BASELINE,
        "candidate": CANDIDATE,
        "all_wape_baseline": base_all,
        "all_wape_candidate": cand_all,
        "delta_all_wape": cand_all - base_all,
        "critical_wape_baseline": base_crit,
        "critical_wape_candidate": cand_crit,
        "win_rate_by_cut": win_rate,
        "bootstrap_delta_ci95": [ci_low, ci_high],
        "bootstrap_n": 2000,
        "bootstrap_cuts_used": len(set(base["cut"])) - len(skipped_cuts),
        "bootstrap_cuts_skipped_wape_undefined": skipped_cuts,
        "decision": decision,
        "reject_reasons": reasons,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (OUT_DIR / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({k: result[k] for k in (
        "scope_n_municipios", "n_cuts", "all_wape_baseline", "all_wape_candidate",
        "delta_all_wape", "critical_wape_baseline", "critical_wape_candidate",
        "win_rate_by_cut", "bootstrap_delta_ci95", "decision", "reject_reasons",
    )}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
