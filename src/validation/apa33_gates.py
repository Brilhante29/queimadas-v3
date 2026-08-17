"""Gates G0/G1/G2 do escopo APA, gerados a partir dos artefatos.

Nenhuma metrica e digitada aqui: tudo e lido de arquivo produzido por codigo
(SDD 36, 37, 38, 45). Se um artefato estiver ausente, o gate FALHA -- nunca
assume sucesso.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

SNAP = PROJECT_ROOT / "data" / "snapshots" / "inpe_apa33_satref_v1"
SCOPE_CSV = PROJECT_ROOT / "data" / "reference" / "apa_chapada_araripe.csv"
EXP_DIR = PROJECT_ROOT / "outputs" / "apa33" / "exp10"
GATES_DIR = PROJECT_ROOT / "outputs" / "apa33" / "gates"

MIN_TRAIN_MONTHS = 60
EXPECTED_MONTHS = 264  # 2003-01 .. 2024-12


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gate_g0_data() -> dict:
    """Calcula a etapa `gate g0 data` do fluxo FireCast.

    Contratos de dados. ML nao roda se isto falhar (SDD 36)."""
    checks: dict[str, object] = {}
    failures: list[str] = []

    scope = pd.read_csv(SCOPE_CSV)
    target = pd.read_csv(SNAP / "municipality_month.csv")
    quality = json.loads((SNAP / "quality_report.json").read_text(encoding="utf-8"))

    scope_geos = set(scope["geocodigo"].astype(int))
    checks["scope_n"] = len(scope_geos)
    checks["scope_by_uf"] = scope["uf"].value_counts().to_dict()
    checks["scope_geocodigo_unique"] = len(scope_geos) == len(scope)
    if not checks["scope_geocodigo_unique"]:
        failures.append("geocodigos duplicados no escopo")

    ref = json.loads((PROJECT_ROOT / "data" / "reference" / "ibge_municipios_CE_PE_PI.json").read_text(encoding="utf-8"))
    ref_geos = {m["geocodigo"] for m in ref}
    unknown = scope_geos - ref_geos
    checks["scope_all_in_ibge_reference"] = not unknown
    if unknown:
        failures.append(f"geocodigos fora da referencia IBGE: {sorted(unknown)}")

    sub = target[target["geocodigo"].astype(int).isin(scope_geos)]
    checks["scope_present_in_target"] = int(sub["geocodigo"].nunique())
    if checks["scope_present_in_target"] != len(scope_geos):
        failures.append("municipio do escopo ausente do alvo")

    dup = int(sub.duplicated(subset=["geocodigo", "ano", "mes"]).sum())
    checks["duplicate_monthly_keys"] = dup
    if dup:
        failures.append(f"{dup} chaves (geocodigo,ano,mes) duplicadas")

    months = sub.groupby("geocodigo").size()
    checks["months_per_municipality_min"] = int(months.min())
    checks["months_per_municipality_max"] = int(months.max())
    if months.min() != EXPECTED_MONTHS or months.max() != EXPECTED_MONTHS:
        failures.append(f"grade temporal incompleta (esperado {EXPECTED_MONTHS} meses/municipio)")

    observed = sub[sub["observed"].astype(bool)] if "observed" in sub.columns else sub
    elig = observed.groupby("geocodigo").size()
    n_elig = int((elig >= MIN_TRAIN_MONTHS).sum())
    checks["min_train_months"] = MIN_TRAIN_MONTHS
    checks["n_eligible"] = n_elig
    checks["eligible_fraction"] = round(n_elig / len(scope_geos), 4)

    neg = int((sub["fire_count"].dropna() < 0).sum())
    checks["negative_fire_count"] = neg
    if neg:
        failures.append(f"{neg} linhas com fire_count negativo")

    checks["unresolved_municipality_names"] = quality.get("n_unresolved_municipality_names")
    if quality.get("n_unresolved_municipality_names"):
        failures.append("nomes de municipio nao resolvidos na ingestao")

    checks["source_files_ok"] = quality.get("files_ok")
    checks["source_files_failed"] = quality.get("files_failed")
    if quality.get("files_failed"):
        failures.append(f"{quality.get('files_failed')} arquivos-fonte falharam")

    checks["target_sha256"] = sha256_file(SNAP / "municipality_month.csv")
    checks["scope_sha256"] = sha256_file(SCOPE_CSV)

    return {
        "gate": "G0_data",
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "checks": checks,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def gate_g1_training() -> dict:
    """Calcula a etapa `gate g1 training` do fluxo FireCast."""
    failures: list[str] = []
    required = ["predictions_2015_2024.csv", "summary.csv", "regional_ratio_by_cut.csv", "result.json"]
    missing = [f for f in required if not (EXP_DIR / f).exists()]
    if missing:
        return {
            "gate": "G1_training",
            "status": "FAIL",
            "failures": [f"artefatos ausentes: {missing}"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    result = json.loads((EXP_DIR / "result.json").read_text(encoding="utf-8"))
    preds = pd.read_csv(EXP_DIR / "predictions_2015_2024.csv")

    checks = {
        "artifacts_present": required,
        "n_cuts": result["n_cuts"],
        "n_prediction_rows": int(len(preds)),
        "predictions_nonnegative": bool((preds["y_pred"] >= 0).all()),
        "test_years": sorted(preds["ano"].unique().tolist()),
        "hyperparameters_unchanged": result["hyperparameters_unchanged"],
        "bootstrap_present": "bootstrap_delta_ci95" in result,
    }
    if result["n_cuts"] != 120:
        failures.append(f"esperava 120 cortes, obtive {result['n_cuts']}")
    if not checks["predictions_nonnegative"]:
        failures.append("previsoes negativas")
    if max(checks["test_years"]) > 2024:
        failures.append("ano >2024 entrou na selecao (2025+ deve ficar congelado)")
    if result["hyperparameters_unchanged"]["min_train_months"] != MIN_TRAIN_MONTHS:
        failures.append("MIN_TRAIN_MONTHS foi alterado")

    return {
        "gate": "G1_training",
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "checks": checks,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def gate_g2_selection() -> dict:
    """Calcula a etapa `gate g2 selection` do fluxo FireCast."""
    result = json.loads((EXP_DIR / "result.json").read_text(encoding="utf-8"))
    return {
        "gate": "G2_selection",
        "status": "PASS" if result["decision"] == "PROMOTE" else "FAIL",
        "baseline": result["baseline"],
        "candidate": result["candidate"],
        "all_wape_baseline": result["all_wape_baseline"],
        "all_wape_candidate": result["all_wape_candidate"],
        "delta_all_wape": result["delta_all_wape"],
        "critical_wape_baseline": result["critical_wape_baseline"],
        "critical_wape_candidate": result["critical_wape_candidate"],
        "win_rate_by_cut": result["win_rate_by_cut"],
        "bootstrap_delta_ci95": result["bootstrap_delta_ci95"],
        "bootstrap_cuts_used": result.get("bootstrap_cuts_used"),
        "bootstrap_cuts_skipped_wape_undefined": result.get("bootstrap_cuts_skipped_wape_undefined"),
        "decision": result["decision"],
        "reject_reasons": result["reject_reasons"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    """Executa a etapa `main` do fluxo FireCast."""
    GATES_DIR.mkdir(parents=True, exist_ok=True)
    overall = {}
    for fn, name in ((gate_g0_data, "G0_data"), (gate_g1_training, "G1_training"), (gate_g2_selection, "G2_selection")):
        g = fn()
        (GATES_DIR / f"{name}.json").write_text(json.dumps(g, indent=2, ensure_ascii=False), encoding="utf-8")
        overall[name] = g["status"]
        print(f"{name}: {g['status']}" + (f"  {g.get('failures')}" if g.get("failures") else ""))
    print(json.dumps(overall, indent=2))


if __name__ == "__main__":
    main()
