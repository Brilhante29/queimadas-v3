"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/diagnose_exp03_failures.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PREDICTIONS = PROJECT_ROOT / "outputs" / "exp03_climate_candidate" / "predictions.csv"
TARGET = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
OUT_DIR = PROJECT_ROOT / "outputs" / "exp03_failure_diagnosis"

BASELINE = "climatology_municipal"
CANDIDATES = ["gbm_target_only", "gbm_climate", "gbm_climate_ndvi"]


def wape(y_true: pd.Series, y_pred: pd.Series) -> float:
    """Executa a etapa `wape` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/diagnose_exp03_failures.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    denom = float(np.abs(y_true).sum())
    if denom == 0:
        return float("nan")
    return float(np.abs(y_true - y_pred).sum() / denom)


def load_wide() -> pd.DataFrame:
    """Carrega a etapa `load wide` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/diagnose_exp03_failures.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if not PREDICTIONS.exists():
        raise FileNotFoundError(f"Predições ausentes: {PREDICTIONS}")
    preds = pd.read_csv(PREDICTIONS)
    needed = {"geocodigo", "ano", "mes", "fire_count", "model", "y_pred", "cut"}
    missing = needed - set(preds.columns)
    if missing:
        raise ValueError(f"Predições sem colunas obrigatórias: {sorted(missing)}")

    models = {BASELINE, *CANDIDATES}
    subset = preds[preds["model"].isin(models)].copy()
    wide = subset.pivot_table(
        index=["geocodigo", "ano", "mes", "cut", "fire_count"],
        columns="model",
        values="y_pred",
        aggfunc="first",
    ).reset_index()
    missing_models = models - set(wide.columns)
    if missing_models:
        raise ValueError(f"Predições sem modelos obrigatórios: {sorted(missing_models)}")

    names = (
        pd.read_csv(TARGET)[["geocodigo", "municipio_ibge", "uf"]]
        .drop_duplicates("geocodigo")
    )
    wide = wide.merge(names, on="geocodigo", how="left")
    wide["municipio_ibge"] = wide["municipio_ibge"].fillna("UNKNOWN")
    wide["uf"] = wide["uf"].fillna("UNKNOWN")
    wide["volume_bin"] = pd.cut(
        wide["fire_count"],
        bins=[-0.1, 0, 2, 10, np.inf],
        labels=["zero", "1-2", "3-10", ">10"],
    )
    return wide


def add_errors(wide: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `add errors` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/diagnose_exp03_failures.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out = wide.copy()
    out["abs_err_baseline"] = (out["fire_count"] - out[BASELINE]).abs()
    for cand in CANDIDATES:
        out[f"abs_err_{cand}"] = (out["fire_count"] - out[cand]).abs()
        out[f"delta_abs_err_{cand}"] = out[f"abs_err_{cand}"] - out["abs_err_baseline"]
        out[f"candidate_wins_{cand}"] = out[f"delta_abs_err_{cand}"] < 0
    return out


def summarize_slice(df: pd.DataFrame, group_cols: list[str], cand: str) -> pd.DataFrame:
    """Executa a etapa `summarize slice` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/diagnose_exp03_failures.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    rows = []
    for keys, g in df.groupby(group_cols, dropna=False, observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_cols, keys))
        row.update(
            n=int(len(g)),
            observed_total=float(g["fire_count"].sum()),
            baseline_wape=wape(g["fire_count"], g[BASELINE]),
            candidate_wape=wape(g["fire_count"], g[cand]),
            delta_abs_error=float(g[f"delta_abs_err_{cand}"].sum()),
            mean_delta_abs_error=float(g[f"delta_abs_err_{cand}"].mean()),
            candidate_win_rate=float(g[f"candidate_wins_{cand}"].mean()),
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["delta_abs_error", "observed_total"], ascending=[False, False]
    )


def write_report(wide: pd.DataFrame, summaries: dict[str, pd.DataFrame]) -> None:
    """Grava a etapa `write report` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/diagnose_exp03_failures.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    best_climate = "gbm_climate_ndvi"
    target_only = "gbm_target_only"
    total_fire = wide["fire_count"].sum()
    baseline_w = wape(wide["fire_count"], wide[BASELINE])
    target_w = wape(wide["fire_count"], wide[target_only])
    climate_w = wape(wide["fire_count"], wide[best_climate])
    top_muni = summaries[f"municipality_{best_climate}"].head(8)
    top_month = summaries[f"month_{best_climate}"].head(6)
    top_volume = summaries[f"volume_{best_climate}"].head(4)
    top_rows = wide.sort_values(f"delta_abs_err_{best_climate}", ascending=False).head(10)

    def md_table(df: pd.DataFrame, cols: list[str]) -> str:
        """Executa a etapa `md table` do fluxo FireCast.
        
        A funcao faz parte de `src/experiments/diagnose_exp03_failures.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        if df.empty:
            return "_Sem linhas._"
        view = df[cols].copy()
        for col in view.columns:
            if pd.api.types.is_float_dtype(view[col]):
                view[col] = view[col].map(lambda x: "" if pd.isna(x) else f"{x:.4f}")
        lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
        for _, row in view.iterrows():
            lines.append("| " + " | ".join(str(row[col]) for col in cols) + " |")
        return "\n".join(lines)

    report = f"""# Diagnóstico de failure cases — EXP-03

## Escopo

- Entrada: `{PREDICTIONS.relative_to(PROJECT_ROOT)}`.
- Baseline comparado: `{BASELINE}`.
- Candidatos avaliados: `{', '.join(CANDIDATES)}`.
- Amostras: {len(wide)} predições por modelo nos cortes 2023–2024.
- Focos observados no teste: {total_fire:.0f}.

## Resultado global reproduzido

| Modelo | WAPE |
|---|---:|
| {BASELINE} | {baseline_w:.4f} |
| {target_only} | {target_w:.4f} |
| {best_climate} | {climate_w:.4f} |

## Evidência principal

O bloco clima/NDVI não falhou apenas por ruído médio: ele concentrou aumento de erro em meses e municípios de maior volume, exatamente onde o sistema precisa ser operacionalmente útil. Como o candidato `gbm_target_only` também não superou o baseline, o próximo passo não deve ser tuning do GBM; deve isolar se o problema é representação temporal/sazonal, qualidade/disponibilidade do NDVI ou granularidade espacial do clima por centroide.

## Municípios que mais aumentaram erro absoluto com clima+NDVI

{md_table(top_muni, ['municipio_ibge', 'uf', 'n', 'observed_total', 'baseline_wape', 'candidate_wape', 'delta_abs_error', 'candidate_win_rate'])}

## Meses que mais aumentaram erro absoluto com clima+NDVI

{md_table(top_month, ['mes', 'n', 'observed_total', 'baseline_wape', 'candidate_wape', 'delta_abs_error', 'candidate_win_rate'])}

## Volume observado

{md_table(top_volume, ['volume_bin', 'n', 'observed_total', 'baseline_wape', 'candidate_wape', 'delta_abs_error', 'candidate_win_rate'])}

## Maiores linhas individuais de regressão do clima+NDVI

{md_table(top_rows, ['cut', 'municipio_ibge', 'fire_count', BASELINE, best_climate, 'abs_err_baseline', f'abs_err_{best_climate}', f'delta_abs_err_{best_climate}'])}

## Próxima hipótese recomendada

Hipótese EXP-04: o baseline municipal vence porque captura sazonalidade local estável melhor que o GBM com exógenas pontuais; antes de novas fontes ou tuning, testar uma mudança única e segura: um candidato aditivo simples que preserve a climatologia municipal como âncora e aprenda apenas um residual regularizado com features defasadas. Condição de rejeição: WAPE agregado >= `climatology_municipal` ou piora nos meses out–nov.

Se EXP-04 falhar, retornar à camada de dados: auditar NDVI por disponibilidade/publicação e substituir clima por estatísticas zonais ERA5, conforme já previsto no SDD.
"""
    (OUT_DIR / "failure_report.md").write_text(report, encoding="utf-8")


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/diagnose_exp03_failures.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wide = add_errors(load_wide())
    wide.to_csv(OUT_DIR / "wide_errors.csv", index=False)

    summaries: dict[str, pd.DataFrame] = {}
    for cand in CANDIDATES:
        summaries[f"municipality_{cand}"] = summarize_slice(wide, ["geocodigo", "municipio_ibge", "uf"], cand)
        summaries[f"month_{cand}"] = summarize_slice(wide, ["mes"], cand)
        summaries[f"volume_{cand}"] = summarize_slice(wide, ["volume_bin"], cand)
        summaries[f"cut_{cand}"] = summarize_slice(wide, ["cut"], cand)
        for name, df in list(summaries.items()):
            if name.endswith(cand):
                df.to_csv(OUT_DIR / f"{name}.csv", index=False)

    write_report(wide, summaries)
    print(f"Diagnóstico gravado em {OUT_DIR}")


if __name__ == "__main__":
    main()
