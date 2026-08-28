"""Artefato de serving do escopo APA Chapada do Araripe.

Contrato de incerteza (regra dura)
----------------------------------
Enquanto o gate G5 nao passar, este servico **nao expoe intervalo como se
fosse validado**. Ele devolve:

```json
{"forecast": 12.4, "interval": null, "uncertainty_status": "not_validated"}
```

Previsao pontual e permitida; intervalo com aparencia de garantia, nao. O
status vem lido do proprio arquivo de gate, nunca de constante no codigo --
se o G5 passar, o serving passa a expor intervalo sem edicao manual.

Escopo
------
O artefato declara o escopo derivado (`apa_chapada_araripe.csv`) e seu hash.
Municipio fora da APA falha fechado: o endpoint da APA nao pode aceitar
silenciosamente um municipio que o modelo nao cobre.

O consumidor (back-end) deve ler os municipios DESTE artefato, nunca manter
lista propria hardcoded -- foi exatamente esse acoplamento que produziu o
mapa fixo de 29 cidades do Cariri na integracao anterior.
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

SCOPE_CSV = PROJECT_ROOT / "data" / "reference" / "apa_chapada_araripe.csv"
TARGET = PROJECT_ROOT / "data" / "snapshots" / "inpe_ce_pe_pi_satref_v1" / "municipality_month.csv"
EXP_RESULT = PROJECT_ROOT / "outputs" / "apa_araripe" / "exp10" / "result.json"
G5_GATE = PROJECT_ROOT / "outputs" / "apa_araripe" / "gates" / "G5_conformal.json"
OUT_DIR = PROJECT_ROOT / "outputs" / "apa_araripe" / "serving"

MODEL_NAME = "climatology_apa_intensity12"
TRAILING_MONTHS = 12
SHRINK_FIRE_COUNT = 100.0
RATIO_CLIP = (0.5, 2.0)


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def uncertainty_status() -> tuple[str, str]:
    """Carrega a etapa `uncertainty status` do fluxo FireCast.

    Le o status direto do gate G5. Fail-closed: gate ausente ou ilegivel
    tambem resulta em `not_validated`, nunca em intervalo exposto."""
    if not G5_GATE.exists():
        return "not_validated", "gate G5 ausente"
    try:
        gate = json.loads(G5_GATE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return "not_validated", f"gate G5 ilegivel: {exc}"
    if gate.get("status") == "PASS":
        return "validated", "G5 PASS"
    return "not_validated", f"G5 {gate.get('status')}: {gate.get('failures')}"


def build_artifact() -> dict:
    """Constroi a etapa `build artifact` do fluxo FireCast.

    Serializa climatologia municipal-mes e o fator regional da APA a partir do
    historico completo disponivel, para servir previsoes h=1."""
    scope = pd.read_csv(SCOPE_CSV)
    geos = set(scope["geocodigo"].astype(int))

    target = pd.read_csv(TARGET)
    target = target[target["geocodigo"].astype(int).isin(geos)].copy()
    if "observed" in target.columns:
        target.loc[~target["observed"].astype(bool), "fire_count"] = np.nan
    target["period"] = pd.PeriodIndex(
        pd.to_datetime(target["ano"].astype(str) + "-" + target["mes"].astype(str).str.zfill(2)),
        freq="M",
    )

    hist = target[target["fire_count"].notna()]
    clim = (
        hist.groupby(["geocodigo", "mes"])["fire_count"].mean().reset_index(name="climatologia")
    )

    last = hist["period"].max()
    prior = hist[(hist["period"] > last - TRAILING_MONTHS) & (hist["period"] <= last)]
    expected = float(
        prior.merge(clim, on=["geocodigo", "mes"], how="left")["climatologia"].sum()
    )
    observed = float(prior["fire_count"].sum())
    raw_ratio = (observed + SHRINK_FIRE_COUNT) / (expected + SHRINK_FIRE_COUNT)
    ratio = float(np.clip(raw_ratio, RATIO_CLIP[0], RATIO_CLIP[1]))

    status, reason = uncertainty_status()
    exp_result = json.loads(EXP_RESULT.read_text(encoding="utf-8"))

    names = dict(zip(scope["geocodigo"].astype(int), scope["municipio"]))
    ufs = dict(zip(scope["geocodigo"].astype(int), scope["uf"]))

    artifact = {
        "model_name": MODEL_NAME,
        "scope": "apa_chapada_araripe",
        "scope_sha256": sha256_file(SCOPE_CSV),
        "scope_n_municipios": len(geos),
        "scope_by_uf": scope["uf"].value_counts().to_dict(),
        "target_snapshot": str(TARGET.relative_to(PROJECT_ROOT)),
        "target_sha256": sha256_file(TARGET),
        "training_period": {"start": str(hist["period"].min()), "end": str(last)},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "trailing_months": TRAILING_MONTHS,
            "shrink_fire_count": SHRINK_FIRE_COUNT,
            "ratio_clip": list(RATIO_CLIP),
        },
        "regional_factor": {
            "observed_trailing_12m": observed,
            "expected_trailing_12m": expected,
            "raw_ratio": raw_ratio,
            "applied_ratio": ratio,
            "window_end": str(last),
            "contract": "fator calculado SOMENTE sobre municipios do escopo APA",
        },
        "point_forecast_evidence": {
            "all_wape_baseline": exp_result["all_wape_baseline"],
            "all_wape_candidate": exp_result["all_wape_candidate"],
            "bootstrap_delta_ci95": exp_result["bootstrap_delta_ci95"],
            "decision": exp_result["decision"],
        },
        "uncertainty": {
            "status": status,
            "reason": reason,
            "contract": (
                "enquanto status != validated o serving devolve interval=null; "
                "previsao pontual permitida, intervalo com aparencia de garantia nao"
            ),
        },
        "municipios": [
            {"geocodigo": int(g), "municipio": names[int(g)], "uf": ufs[int(g)]}
            for g in sorted(geos)
        ],
        "climatology": [
            {"geocodigo": int(r.geocodigo), "mes": int(r.mes), "prediction": float(r.climatologia)}
            for r in clim.itertuples()
        ],
    }
    return artifact


def predict(artifact: dict, geocodigo: int, ano: int, mes: int) -> dict:
    """Gera a etapa `predict` do fluxo FireCast.

    Falha fechada para municipio fora da APA. Intervalo so e exposto se o
    gate de incerteza estiver validado."""
    geos = {m["geocodigo"] for m in artifact["municipios"]}
    if geocodigo not in geos:
        raise ValueError(
            f"geocodigo {geocodigo} fora do escopo {artifact['scope']} "
            f"({artifact['scope_n_municipios']} municipios) -- fail closed"
        )
    if not 1 <= mes <= 12:
        raise ValueError(f"mes invalido: {mes}")

    key = (int(geocodigo), int(mes))
    clim = {(c["geocodigo"], c["mes"]): c["prediction"] for c in artifact["climatology"]}
    if key not in clim:
        raise ValueError(f"sem climatologia para geocodigo={geocodigo} mes={mes} -- fail closed")

    base = clim[key]
    ratio = artifact["regional_factor"]["applied_ratio"]
    forecast = max(base * ratio, 0.0)

    info = next(m for m in artifact["municipios"] if m["geocodigo"] == geocodigo)
    validated = artifact["uncertainty"]["status"] == "validated"
    return {
        "geocodigo": geocodigo,
        "municipio": info["municipio"],
        "uf": info["uf"],
        "ano": ano,
        "mes": mes,
        "scope": artifact["scope"],
        "scope_sha256": artifact["scope_sha256"],
        "model_name": artifact["model_name"],
        "forecast": round(forecast, 4),
        "interval": None if not validated else {"low": None, "high": None},
        "uncertainty_status": artifact["uncertainty"]["status"],
        "uncertainty_reason": artifact["uncertainty"]["reason"],
    }


def main() -> None:
    """Executa a etapa `main` do fluxo FireCast."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    artifact = build_artifact()
    path = OUT_DIR / "model.json"
    path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")

    sample = predict(artifact, 2602001, 2026, 10)  # Bodoco/PE
    print(json.dumps(
        {
            "artifact": str(path.relative_to(PROJECT_ROOT)),
            "artifact_sha256": sha256_file(path),
            "scope_n": artifact["scope_n_municipios"],
            "scope_by_uf": artifact["scope_by_uf"],
            "regional_ratio": artifact["regional_factor"]["applied_ratio"],
            "uncertainty_status": artifact["uncertainty"]["status"],
            "sample_prediction": sample,
        },
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
