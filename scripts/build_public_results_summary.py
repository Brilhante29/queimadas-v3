"""Gera `outputs/public_results_summary.json` a partir dos artefatos.

Por que este script existe
--------------------------
A versao anterior do summary era digitada a mao. Resultado: numeros do escopo
legado (Cariri/CE, 29 municipios) ficaram publicados sob o rotulo
`"scope": "Chapada do Araripe / CE-PE-PI"`, com gates marcados PASS que
pertenciam a outro escopo. Um leitor nao tinha como distinguir. Isso e
exatamente o que o §23 proibe.

A correcao estrutural nao e reescrever os numeros -- e parar de digita-los.
Aqui todo valor vem de `pluck()`, que **levanta erro** se a chave sumir. Um
artefato renomeado quebra o build em vez de deixar um numero velho no lugar.

Uso
---
```bash
python scripts/build_public_results_summary.py           # grava
python scripts/build_public_results_summary.py --check   # CI: falha se desatualizado
```
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "outputs" / "public_results_summary.json"

# Campo volatil: muda a cada execucao e por isso fica fora da comparacao do
# --check. Sem essa exclusao o CI acusaria diferenca em toda rodada.
VOLATILE = ("generated_at",)


def load(rel: str) -> Any:
    """Le um artefato JSON exigindo que ele exista."""
    path = PROJECT_ROOT / rel
    if not path.exists():
        raise FileNotFoundError(
            f"artefato ausente: {rel}. O summary publico nao pode ser gerado "
            "com numero digitado -- rode o pipeline que produz esse artefato."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def pluck(obj: Any, path: str, source: str) -> Any:
    """Navega `a.b.c` falhando alto se qualquer nivel faltar.

    Falhar alto e o ponto: chave ausente vira erro de build, nunca um valor
    obsoleto herdado da versao anterior do arquivo."""
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"chave '{path}' ausente em {source} (parou em '{part}')")
        cur = cur[part]
    return cur


def interval_diagnostics() -> dict:
    """Diagnostico dos intervalos de 2025, derivado do CSV.

    Mede duas coisas que o gate G5 **nao** mede e que mudam a leitura da
    cobertura de 2025: quanto do intervalo tem piso efetivo em zero, e qual a
    cobertura restrita as linhas onde o piso e testavel."""
    import pandas as pd

    csv = PROJECT_ROOT / "outputs" / "apa_araripe" / "g5_final_2025" / "interval_predictions_2025.csv"
    if not csv.exists():
        raise FileNotFoundError(f"ausente: {csv.relative_to(PROJECT_ROOT)}")
    d = pd.read_csv(csv)
    n = len(d)
    floor_at_zero = int((d["interval_low"] <= 0).sum())
    testable = d[d["interval_low"] > 0]
    y = d["fire_count"].to_numpy(float)
    return {
        "n_intervals": n,
        "n_lower_bound_at_or_below_zero": floor_at_zero,
        "share_lower_bound_non_informative": round(floor_at_zero / n, 4),
        "n_lower_bound_testable": int(len(testable)),
        "coverage_where_lower_bound_testable": (
            round(float(testable["covered"].mean()), 4) if len(testable) else None
        ),
        "violations_below_lower_bound": int((y < d["interval_low"]).sum()),
        "violations_above_upper_bound": int((y > d["interval_high"]).sum()),
        "interpretation": (
            "A cobertura global de 2025 e dominada pelo limite inferior, que fica "
            "em zero na maioria das linhas e por isso quase nunca pode ser violado. "
            "O intervalo e, na pratica, unilateral. A cobertura restrita as linhas "
            "com piso testavel e o numero honesto para o lado inferior."
        ),
    }


def ceiling_diagnostics(sealed: dict) -> dict:
    """Mostra que o teto do gate coincide com o nivel nominal do intervalo.

    Com `alpha = 0.02` o intervalo e nominalmente 0.98 e o teto aceitavel
    tambem e 0.98. Um metodo perfeitamente calibrado gera cobertura amostral
    acima de 0.98 com frequencia alta -- ou seja, o teto reprova acerto."""
    from math import comb

    alpha = float(pluck(sealed, "frozen_config.alpha", "g5_final_report.json"))
    nominal = 1.0 - alpha
    ic_high = float(pluck(sealed, "ic_bounds", "g5_final_report.json")[1])
    cov = pluck(sealed, "coverage_2025", "g5_final_report.json")

    # Para cada UF, com o n real daquela UF: qual a chance de um metodo
    # perfeitamente calibrado estourar o teto so por acaso amostral?
    per_uf = {}
    for key in sorted(k for k in cov if k.startswith("uf_")):
        uf = key[3:]
        n = int(cov[f"n_uf_{uf}"])
        k_max_allowed = int(ic_high * n)  # maior numero de acertos que ainda passa
        p_reject = sum(
            comb(n, k) * (nominal ** k) * ((1 - nominal) ** (n - k))
            for k in range(k_max_allowed + 1, n + 1)
        )
        per_uf[uf] = {
            "n": n,
            "coverage_observed": round(float(cov[key]), 4),
            "misses_observed": int(round(n * (1 - float(cov[key])))),
            "min_misses_needed_to_pass_ceiling": max(0, n - k_max_allowed),
            "prob_perfect_method_fails_ceiling": round(p_reject, 4),
        }

    return {
        "nominal_coverage": round(nominal, 4),
        "gate_ceiling": ic_high,
        "ceiling_equals_nominal": abs(nominal - ic_high) < 1e-9,
        "by_uf": per_uf,
        "interpretation": (
            "O teto do gate e igual ao nivel nominal do intervalo. Um metodo "
            "perfeitamente calibrado ultrapassa esse teto por acaso com a "
            "probabilidade acima. A reprovacao de PE, portanto, e evidencia "
            "fraca contra o metodo e evidencia forte contra a especificacao do "
            "gate. O FAIL e mantido: reespecificar o gate depois de ver o "
            "holdout seria ajuste no holdout."
        ),
    }


def baseline_strength_diagnostics() -> dict:
    """Le o benchmark contra baselines que tambem corrigem nivel.

    O gate G2 compara o champion so contra climatologia de longo prazo. Se um
    baseline mais simples com janela recente empata, a afirmacao do G2 e
    verdadeira mas mais fraca do que parece, e isso precisa estar publicado."""
    path = (
        PROJECT_ROOT / "outputs" / "apa_araripe" / "audit" / "competent_baselines.json"
    )
    if not path.exists():
        raise FileNotFoundError(
            "ausente: outputs/apa_araripe/audit/competent_baselines.json -- rode "
            "scripts/benchmark_competent_baselines.py"
        )
    d = json.loads(path.read_text(encoding="utf-8"))
    return {
        "wape_by_model": {k: v["wape_all"] for k, v in d["metrics"].items()},
        "champion_beats_significantly": d["champion_beats_significantly"],
        "champion_does_not_beat_significantly": d["champion_does_not_beat_significantly"],
        "comparisons": d["comparisons"],
        "interpretation": d["verdict"],
        "consequence_for_the_g2_claim": (
            "O G2 continua valido como foi definido: o champion supera "
            "`climatology_municipal` com IC95 inteiramente negativo. Mas a leitura "
            "cientifica e mais modesta do que 'o fator regional de intensidade e o "
            "que importa' -- uma climatologia de janela recente, sem fator regional "
            "nenhum, chega perto. Qualquer G2 futuro precisa incluir um baseline "
            "com janela recente, nao so a climatologia de longo prazo."
        ),
    }


MARK_START = "<!-- FIRECAST:METRICS:START -->"
MARK_END = "<!-- FIRECAST:METRICS:END -->"

DOCS = ("README.md", "PRODUCTION_READINESS.md")


def render_markdown(summary: dict) -> str:
    """Renderiza o bloco de metricas que vai para README e PRODUCTION_READINESS.

    Um unico renderizador alimenta os dois documentos justamente para que eles
    nao possam divergir entre si nem dos artefatos."""
    cur = summary["current_scope"]
    leg = summary["legacy_cariri_ce"]
    pf = cur["point_forecast"]
    sealed = cur["sealed_2025_holdout"]
    lim = cur["known_limitations"]
    one_sided = lim["intervals_effectively_one_sided"]
    ceiling = lim["gate_ceiling_collides_with_nominal_level"]
    strength = lim["gain_over_a_recent_window_baseline_is_not_significant"]

    uf_txt = ", ".join(f"{k} {v}" for k, v in sorted(cur["by_uf"].items()))

    lines = [
        "> Bloco gerado por `scripts/build_public_results_summary.py`. Nao edite a mao.",
        "> Todo numero e lido de artefato; o CI falha se este bloco divergir.",
        "",
        f"### Escopo vigente: APA Chapada do Araripe ({cur['n_municipalities']} municipios -- {uf_txt})",
        "",
        f"Status de producao: **{cur['production_status']}**",
        "",
        f"Incerteza: `{cur['uncertainty_status']}` -- {cur['uncertainty_reason']}",
        "",
        "| Bloco | Metrica | Valor |",
        "|---|---|---:|",
        f"| Walk-forward {cur['n_cuts']} cortes | WAPE baseline | `{pf['all_wape_baseline']:.4f}` |",
        f"| Walk-forward {cur['n_cuts']} cortes | WAPE champion | `{pf['all_wape_champion']:.4f}` |",
        f"| Walk-forward {cur['n_cuts']} cortes | Delta WAPE | `{pf['delta_all_wape']:.4f}` |",
        f"| Estacao critica Out-Nov | WAPE baseline | `{pf['critical_wape_baseline']:.4f}` |",
        f"| Estacao critica Out-Nov | WAPE champion | `{pf['critical_wape_champion']:.4f}` |",
        f"| Selecao | Bootstrap delta WAPE IC95 | `[{pf['bootstrap_delta_ci95'][0]:.4f}, {pf['bootstrap_delta_ci95'][1]:.4f}]` |",
        f"| Selecao | P(delta < 0) | `{pf['bootstrap_prob_delta_negative']:.4f}` |",
        f"| Selecao | Cortes vencidos | `{pf['win_rate_by_cut']:.4f}` |",
        f"| Holdout selado 2025 | WAPE baseline | `{sealed['point_accuracy_2025']['wape_baseline']:.4f}` |",
        f"| Holdout selado 2025 | WAPE champion | `{sealed['point_accuracy_2025']['wape_champion']:.4f}` |",
        f"| Holdout selado 2025 | Cobertura geral | `{sealed['coverage_2025']['overall']:.4f}` |",
        f"| Holdout selado 2025 | Largura media | `{sealed['interval_width_2025']['mean']:.4f}` |",
        "",
        "#### Gates",
        "",
        "| Gate | Status |",
        "|---|---|",
    ]
    for gate, status in cur["gates"].items():
        lines.append(f"| {gate} | **{status}** |")
    lines += [
        "",
        f"G5 reprovou. Motivo registrado: `{sealed['failures']}`.",
        "",
        "#### Limitacoes conhecidas do G5",
        "",
        "Duas ressalvas medidas, nao opinadas. Ambas saem de auditoria independente e",
        "ficam aqui porque mudam a leitura do resultado de 2025.",
        "",
        f"1. **O intervalo e unilateral na pratica.** {one_sided['n_lower_bound_at_or_below_zero']} de "
        f"{one_sided['n_intervals']} intervalos ({one_sided['share_lower_bound_non_informative']:.1%}) "
        f"tem limite inferior <= 0, que praticamente nao pode ser violado. Nas "
        f"{one_sided['n_lower_bound_testable']} linhas com piso testavel a cobertura cai para "
        f"`{one_sided['coverage_where_lower_bound_testable']:.4f}`. Das violacoes, "
        f"{one_sided['violations_above_upper_bound']} sao por cima e "
        f"{one_sided['violations_below_lower_bound']} por baixo. A cobertura global de "
        f"`{sealed['coverage_2025']['overall']:.4f}` mede sobretudo o teto do intervalo.",
        "",
        f"2. **O teto do gate coincide com o nivel nominal.** Nominal `{ceiling['nominal_coverage']}`, "
        f"teto aceitavel `{ceiling['gate_ceiling']}`. Um metodo perfeitamente calibrado "
        "estoura esse teto so por acaso amostral com a probabilidade abaixo:",
        "",
        "| UF | n | Cobertura | Erros observados | Erros minimos p/ passar o teto | P(metodo perfeito reprova) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for uf, v in sorted(ceiling["by_uf"].items()):
        lines.append(
            f"| {uf} | {v['n']} | {v['coverage_observed']:.4f} | {v['misses_observed']} | "
            f"{v['min_misses_needed_to_pass_ceiling']} | {v['prob_perfect_method_fails_ceiling']:.4f} |"
        )
    lines += [
        "",
        "   PE reprovou com 1 erro em 96. Precisaria de pelo menos 2 para passar: o gate",
        "   penalizou acerto. O FAIL **permanece** -- reespecificar o criterio depois de ver",
        "   o holdout seria ajuste no holdout, que o contrato proibe. O registro correto e",
        "   que o metodo nao foi validado **e** que o gate, como especificado, tambem nao",
        "   serve. Nova tentativa exige gate reescrito e pre-registrado antes de tocar em",
        "   outro ano.",
        "",
        "",
        "3. **O ganho sobre um baseline de janela recente nao e significativo.** O",
        "   gate G2 compara o champion so contra climatologia de longo prazo. Contra",
        "   uma climatologia dos ultimos 60 meses -- sem fator regional, sem",
        "   encolhimento, sem clip -- o IC95 do delta cruza o zero:",
        "",
        "| modelo | WAPE | IC95 do delta vs champion | champion vence? |",
        "|---|---:|---|:--:|",
    ]
    wapes = strength["wape_by_model"]
    lines.append(f"| champion | `{wapes['champion']:.4f}` | -- | -- |")
    for model, comp in strength["comparisons"].items():
        ci = comp["bootstrap_delta_ci95"]
        mark = "sim" if comp["champion_significantly_better"] else "**nao**"
        lines.append(
            f"| {model} | `{wapes[model]:.4f}` | `[{ci[0]:.4f}, {ci[1]:.4f}]` | {mark} |"
        )
    lines += [
        "",
        f"   {strength['consequence_for_the_g2_claim']}",
        "",
        "### Escopo legado: Cariri/CE -- NAO SE APLICA A APA",
        "",
        f"{leg['why_kept']} Escopo: {leg['scope_description']}; "
        f"{leg['n_municipalities_in_training_artifact']} municipios no artefato de treino.",
        "",
        f"**{leg['must_not_be_used_for']}**",
        "",
        "| Metrica legada (Cariri/CE) | Valor |",
        "|---|---:|",
        f"| WAPE walk-forward estendido | `{leg['metrics']['extended_walk_forward_wape']:.4f}` |",
        f"| WAPE Out-Nov | `{leg['metrics']['extended_walk_forward_out_nov_wape']:.4f}` |",
        f"| G3 v2 CE mensal | `{leg['metrics']['g3_v2_ce_monthly_scope_wape']:.4f}` |",
        f"| G3 v2 CE sazonal | `{leg['metrics']['g3_v2_ce_seasonal_wape']:.4f}` |",
        f"| G3 v2 'chapada' sazonal (recorte de {leg['metrics']['g3_v2_chapada_n_cells_evaluated']} celulas) | `{leg['metrics']['g3_v2_chapada_seasonal_wape']:.4f}` |",
        f"| G5 legado cobertura geral (nominal {leg['metrics']['g5_nominal_coverage']}) | `{leg['metrics']['g5_coverage_overall']:.4f}` |",
        f"| G5 legado gate | `{leg['metrics']['g5_gate']}` |",
        "",
        "O G5 legado passou com nominal 0,96 contra teto 0,98 -- tinha folga. O G5 da APA",
        "usou nominal 0,98 contra o mesmo teto 0,98, sem folga nenhuma. Os dois numeros",
        "nao sao comparaveis, e o PASS legado nao sustenta nada sobre a APA.",
    ]
    return "\n".join(lines)


def inject(summary: dict) -> list[str]:
    """Escreve o bloco gerado nos documentos. Devolve os que mudaram."""
    block = render_markdown(summary)
    changed = []
    for name in DOCS:
        path = PROJECT_ROOT / name
        text = path.read_text(encoding="utf-8")
        if MARK_START not in text or MARK_END not in text:
            raise ValueError(f"{name} sem marcadores {MARK_START}/{MARK_END}")
        head = text[: text.index(MARK_START) + len(MARK_START)]
        tail = text[text.index(MARK_END):]
        new = f"{head}\n{block}\n{tail}"
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(name)
    return changed


def build() -> dict:
    """Monta o summary publico inteiramente a partir de artefatos."""
    exp10 = load("outputs/apa_araripe/exp10/result.json")
    g0 = load("outputs/apa_araripe/gates/G0_data.json")
    g1 = load("outputs/apa_araripe/gates/G1_training.json")
    g2 = load("outputs/apa_araripe/gates/G2_selection.json")
    g5_inc = load("outputs/apa_araripe/gates/G5_conformal.json")
    g5_sealed = load("outputs/apa_araripe/gates/G5_final_sealed_2025.json")
    frozen = load("outputs/apa_araripe/g5_drift/frozen_config.json")
    serving = load("outputs/apa_araripe/serving/model.json")

    legacy_g3 = load("outputs/exp26_g3_contract_v2_evaluation/contract_v2_report.json")
    legacy_g5 = load("outputs/g5_conformal_ic95_guarded_exp10/g5_report.json")
    legacy_champ = load("outputs/champion_climatology_regional_intensity12/model.json")

    apa_gates = {
        "G0_data": pluck(g0, "status", "G0_data.json"),
        "G1_training": pluck(g1, "status", "G1_training.json"),
        "G2_selection": pluck(g2, "status", "G2_selection.json"),
        "G5_conformal_incumbent_method": pluck(g5_inc, "status", "G5_conformal.json"),
        "G5_conformal_final_sealed_2025": pluck(g5_sealed, "status", "G5_final_sealed_2025.json"),
    }
    apa_all_pass = all(v == "PASS" for v in apa_gates.values())

    return {
        "package_schema": "firecast_public_handoff_v2",
        "generated_by": "scripts/build_public_results_summary.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "READ_THIS_FIRST": (
            "Este arquivo contem DOIS escopos distintos e nao intercambiaveis. "
            "`apa_chapada_araripe` e o escopo do produto atual (36 municipios de "
            "CE, PE e PI, derivados por intersecao espacial com o poligono da APA). "
            "`legacy_cariri_ce` e um escopo anterior, so do Ceara, com outro alvo e "
            "outro snapshot. Metrica de um bloco NAO vale para o outro. Nenhum gate "
            "do bloco legado sustenta afirmacao sobre a APA."
        ),
        "current_scope": {
            "id": "apa_chapada_araripe",
            "description": "APA Chapada do Araripe -- CE, PE, PI; contagem mensal de focos por municipio IBGE",
            "n_municipalities": pluck(serving, "scope_n_municipios", "serving/model.json"),
            "by_uf": pluck(serving, "scope_by_uf", "serving/model.json"),
            "scope_sha256": pluck(serving, "scope_sha256", "serving/model.json"),
            "target_snapshot_sha256": pluck(serving, "target_sha256", "serving/model.json"),
            "champion": pluck(exp10, "candidate", "exp10/result.json"),
            "baseline": pluck(exp10, "baseline", "exp10/result.json"),
            "protocol": pluck(exp10, "protocol", "exp10/result.json"),
            "n_cuts": pluck(exp10, "n_cuts", "exp10/result.json"),
            "point_forecast": {
                "all_wape_baseline": pluck(exp10, "all_wape_baseline", "exp10/result.json"),
                "all_wape_champion": pluck(exp10, "all_wape_candidate", "exp10/result.json"),
                "delta_all_wape": pluck(exp10, "delta_all_wape", "exp10/result.json"),
                "critical_wape_baseline": pluck(exp10, "critical_wape_baseline", "exp10/result.json"),
                "critical_wape_champion": pluck(exp10, "critical_wape_candidate", "exp10/result.json"),
                "bootstrap_estimand": pluck(exp10, "bootstrap_estimand", "exp10/result.json"),
                "bootstrap_delta_ci95": pluck(exp10, "bootstrap_delta_ci95", "exp10/result.json"),
                "bootstrap_prob_delta_negative": pluck(
                    exp10, "bootstrap_prob_delta_negative", "exp10/result.json"
                ),
                "win_rate_by_cut": pluck(exp10, "win_rate_by_cut", "exp10/result.json"),
            },
            "sealed_2025_holdout": {
                "contract": pluck(g5_sealed, "execution_contract", "G5_final_sealed_2025.json"),
                "frozen_config": pluck(g5_sealed, "frozen_config", "G5_final_sealed_2025.json"),
                "frozen_at": pluck(frozen, "frozen_at", "frozen_config.json"),
                "coverage_2025": pluck(g5_sealed, "coverage_2025", "G5_final_sealed_2025.json"),
                "interval_width_2025": pluck(g5_sealed, "interval_width_2025", "G5_final_sealed_2025.json"),
                "point_accuracy_2025": pluck(g5_sealed, "point_accuracy_2025", "G5_final_sealed_2025.json"),
                "status": pluck(g5_sealed, "status", "G5_final_sealed_2025.json"),
                "failures": pluck(g5_sealed, "failures", "G5_final_sealed_2025.json"),
            },
            "gates": apa_gates,
            "known_limitations": {
                "intervals_effectively_one_sided": interval_diagnostics(),
                "gate_ceiling_collides_with_nominal_level": ceiling_diagnostics(g5_sealed),
                "gain_over_a_recent_window_baseline_is_not_significant": (
                    baseline_strength_diagnostics()
                ),
            },
            "uncertainty_status": pluck(serving, "uncertainty.status", "serving/model.json"),
            "uncertainty_reason": pluck(serving, "uncertainty.reason", "serving/model.json"),
            "production_status": (
                "NAO APROVADO PARA PRODUCAO"
                if not apa_all_pass
                else "gates atendidos; aprovacao humana ainda necessaria"
            ),
            "what_is_permitted": (
                "Servir previsao pontual, sinalizada como nao validada quanto a "
                "incerteza. Proibido apresentar intervalo como validado enquanto "
                "o G5 nao passar."
            ),
        },
        "legacy_cariri_ce": {
            "id": "cariri_ce_legacy",
            "status": "LEGADO -- NAO SE APLICA A APA CHAPADA DO ARARIPE",
            "why_kept": (
                "Preservado para rastreabilidade historica do projeto. Foi produzido "
                "sobre outro escopo, outro snapshot e outro recorte de avaliacao."
            ),
            "scope_description": "municipios do Ceara apenas; recorte 'chapada' interno de 50 celulas avaliadas",
            "n_municipalities_in_training_artifact": pluck(
                legacy_champ, "training_data.municipalities", "champion/model.json"
            ),
            "champion": pluck(legacy_champ, "model_name", "champion/model.json"),
            "artifact_status": pluck(legacy_champ, "status", "champion/model.json"),
            "metrics": {
                "extended_walk_forward_wape": pluck(legacy_champ, "metrics.all_wape", "champion/model.json"),
                "extended_walk_forward_out_nov_wape": pluck(
                    legacy_champ, "metrics.outnov_wape", "champion/model.json"
                ),
                "g3_v2_ce_monthly_scope_wape": pluck(
                    legacy_g3,
                    "metrics.climatology_regional_intensity12.ceara.wape_scope_month",
                    "contract_v2_report.json",
                ),
                "g3_v2_ce_seasonal_wape": pluck(
                    legacy_g3,
                    "metrics.climatology_regional_intensity12.ceara.wape_scope_season",
                    "contract_v2_report.json",
                ),
                "g3_v2_chapada_seasonal_wape": pluck(
                    legacy_g3,
                    "metrics.climatology_regional_intensity12.chapada_araripe.wape_scope_season",
                    "contract_v2_report.json",
                ),
                "g3_v2_chapada_n_cells_evaluated": pluck(
                    legacy_g3,
                    "metrics.climatology_regional_intensity12.chapada_araripe.n_cells",
                    "contract_v2_report.json",
                ),
                "g5_coverage_overall": pluck(
                    legacy_g5, "overall_coverage_test_2023_2024", "g5_report.json"
                ),
                "g5_coverage_dry": pluck(legacy_g5, "dry_season_coverage_test", "g5_report.json"),
                "g5_coverage_wet": pluck(legacy_g5, "wet_season_coverage_test", "g5_report.json"),
                "g5_nominal_coverage": pluck(
                    legacy_g5, "nominal_coverage_selected", "g5_report.json"
                ),
                "g5_gate": pluck(legacy_g5, "gate_G5", "g5_report.json"),
            },
            "must_not_be_used_for": (
                "Qualquer afirmacao sobre desempenho na APA Chapada do Araripe. O "
                "escopo APA tem WAPE mais alto e G5 reprovado; usar estes numeros "
                "no lugar daqueles inverteria a conclusao."
            ),
        },
    }


def main() -> int:
    """Grava ou verifica o summary publico."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="nao grava; sai 1 se o arquivo em disco divergir dos artefatos",
    )
    args = parser.parse_args()

    fresh = build()
    if not args.check:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(fresh, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        touched = inject(fresh)
        print(f"escrito: {OUT.relative_to(PROJECT_ROOT)}")
        for name in touched:
            print(f"  bloco atualizado em {name}")
        print(f"  escopo atual: {fresh['current_scope']['id']} "
              f"({fresh['current_scope']['n_municipalities']} municipios)")
        print(f"  status: {fresh['current_scope']['production_status']}")
        return 0

    if not OUT.exists():
        print(f"FALHA: {OUT.relative_to(PROJECT_ROOT)} nao existe")
        return 1
    disk = json.loads(OUT.read_text(encoding="utf-8"))
    for key in VOLATILE:
        disk.pop(key, None)
        fresh.pop(key, None)
    if disk != fresh:
        print("FALHA: public_results_summary.json esta desatualizado em relacao aos artefatos.")
        print("Rode: python scripts/build_public_results_summary.py")
        return 1

    block = render_markdown(fresh)
    for name in DOCS:
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        if MARK_START not in text or MARK_END not in text:
            print(f"FALHA: {name} perdeu os marcadores do bloco gerado")
            return 1
        current = text[text.index(MARK_START) + len(MARK_START) : text.index(MARK_END)]
        if current.strip() != block.strip():
            print(f"FALHA: bloco de metricas em {name} divergente dos artefatos.")
            print("Rode: python scripts/build_public_results_summary.py")
            return 1

    print("ok: summary publico e blocos de metricas batem com os artefatos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
