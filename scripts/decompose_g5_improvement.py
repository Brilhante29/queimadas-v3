"""Separa o efeito de alpha do efeito do metodo na melhora do G5.

O problema
----------
`g5_final_sealed_result.md` colocava lado a lado a cobertura do G5 anterior
(0,8762) e a do G5 final (0,9537) e atribuia o salto a janela deslizante de 48
meses. Mas tres coisas mudaram ao mesmo tempo:

| | G5 anterior | G5 final |
|---|---|---|
| metodo | `expanding_mondrian` | `rolling_mondrian_48` |
| alpha | 0,05 (nominal 0,95) | 0,02 (nominal 0,98) |
| janela de avaliacao | 2023-2024 | 2025 |

Alargar o nominal em 3 pontos aumenta a cobertura por construcao. Atribuir o
ganho a janela deslizante sem manter alpha fixo nao se sustenta.

A decomposicao
--------------
`candidate_selection.csv` ja avaliou os 28 candidatos -- todo metodo em todo
alpha -- nos mesmos 4 folds de desenvolvimento. Da para isolar cada efeito sem
ajustar nada e **sem tocar em 2025**:

```text
efeito de alpha   = metodo fixo, alpha 0,05 -> 0,02
efeito do metodo  = alpha fixo, expanding -> rolling_48
```

O ano de avaliacao (2023-2024 contra 2025) **nao** e separavel: exigiria
rodar outras configuracoes sobre o holdout selado, que e exatamente o que o
contrato de execucao unica proibe. Isso fica declarado, nao estimado.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = PROJECT_ROOT / "outputs" / "apa_araripe" / "g5_drift" / "candidate_selection.csv"
FROZEN = PROJECT_ROOT / "outputs" / "apa_araripe" / "g5_drift" / "frozen_config.json"
INCUMBENT_GATE = PROJECT_ROOT / "outputs" / "apa_araripe" / "gates" / "G5_conformal.json"
OUT = PROJECT_ROOT / "outputs" / "apa_araripe" / "audit" / "g5_improvement_decomposition.json"

METRICS = ("mean_fold_coverage", "min_fold_coverage", "min_fold_uf_coverage")


def pick(df: pd.DataFrame, name: str, alpha: float) -> pd.Series:
    """Seleciona uma configuracao exata, exigindo que ela exista."""
    hit = df[(df["name"] == name) & (df["alpha"].round(4) == round(alpha, 4))]
    if len(hit) != 1:
        raise KeyError(f"configuracao ({name}, alpha={alpha}) tem {len(hit)} linhas, esperava 1")
    return hit.iloc[0]


def main() -> int:
    """Calcula e grava a decomposicao."""
    df = pd.read_csv(CANDIDATES)
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    incumbent_gate = json.loads(INCUMBENT_GATE.read_text(encoding="utf-8"))

    chosen_name = frozen["chosen"]["name"]
    chosen_alpha = float(frozen["chosen"]["alpha"])
    incumbent_name = "expanding_mondrian"
    incumbent_alpha = float(incumbent_gate["alpha_selected"])

    base = pick(df, incumbent_name, incumbent_alpha)          # metodo velho, alpha velho
    alpha_only = pick(df, incumbent_name, chosen_alpha)       # metodo velho, alpha novo
    method_only = pick(df, chosen_name, incumbent_alpha)      # metodo novo, alpha velho
    both = pick(df, chosen_name, chosen_alpha)                # metodo novo, alpha novo

    effects = {}
    for metric in METRICS:
        b, a, m, t = (float(x[metric]) for x in (base, alpha_only, method_only, both))
        d_alpha = a - b
        d_method = m - b
        d_total = t - b
        effects[metric] = {
            "baseline_old_method_old_alpha": round(b, 4),
            "old_method_new_alpha": round(a, 4),
            "new_method_old_alpha": round(m, 4),
            "new_method_new_alpha": round(t, 4),
            "effect_of_alpha_alone": round(d_alpha, 4),
            "effect_of_method_alone": round(d_method, 4),
            "total_effect": round(d_total, 4),
            "share_attributable_to_alpha": (
                round(d_alpha / d_total, 4) if abs(d_total) > 1e-12 else None
            ),
            "share_attributable_to_method": (
                round(d_method / d_total, 4) if abs(d_total) > 1e-12 else None
            ),
            # Os dois efeitos nao sao aditivos: aplicar alpha e metodo juntos
            # rende menos que a soma dos dois isolados, porque ambos empurram a
            # cobertura para o mesmo teto. Sem este termo as duas fracoes
            # somam mais de 100% e parecem erro de conta.
            "interaction": round(d_total - d_alpha - d_method, 4),
        }

    headline = effects["mean_fold_coverage"]
    alpha_dominates = abs(headline["effect_of_alpha_alone"]) > abs(
        headline["effect_of_method_alone"]
    )

    report = {
        "check": "decomposicao da melhora do G5: alpha x metodo",
        "why": (
            "A comparacao publicada antes mudava metodo, alpha e ano de avaliacao "
            "ao mesmo tempo, e atribuia o ganho inteiro a janela deslizante."
        ),
        "evaluated_on": "os 4 folds de desenvolvimento (2021-2024), nunca em 2025",
        "configurations": {
            "old_method": incumbent_name,
            "old_alpha": incumbent_alpha,
            "new_method": chosen_name,
            "new_alpha": chosen_alpha,
        },
        "effects": effects,
        "alpha_dominates_method": bool(alpha_dominates),
        "conclusion": (
            "O alargamento de alpha (0,05 -> 0,02, nominal 0,95 -> 0,98) responde por "
            f"{headline['share_attributable_to_alpha']:.0%} da melhora de cobertura media "
            f"entre folds; a troca de janela responde por "
            f"{headline['share_attributable_to_method']:.0%}. Atribuir a correcao a "
            "janela deslizante, como o texto anterior fazia, nao se sustenta: o efeito "
            "dominante e ter alargado o nivel nominal. As duas fracoes somam mais de "
            "100% porque os efeitos nao sao aditivos -- o termo de interacao e "
            "negativo, ja que alpha e metodo empurram a cobertura contra o mesmo teto."
            if alpha_dominates
            else "A troca de metodo domina o efeito de alpha; a atribuicao anterior "
            "se sustenta."
        ),
        "what_remains_unseparable": (
            "O efeito do ano de avaliacao (2023-2024 contra 2025) nao e estimavel: "
            "exigiria rodar outras configuracoes sobre o holdout selado, que o "
            "contrato de execucao unica proibe. Fica declarado como confundimento "
            "residual, nao estimado."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("cobertura media entre folds (dados de desenvolvimento):")
    h = headline
    print(f"  {incumbent_name} @ a={incumbent_alpha}  -> {h['baseline_old_method_old_alpha']}")
    print(f"  {incumbent_name} @ a={chosen_alpha}  -> {h['old_method_new_alpha']}   (so alpha: {h['effect_of_alpha_alone']:+.4f})")
    print(f"  {chosen_name} @ a={incumbent_alpha} -> {h['new_method_old_alpha']}   (so metodo: {h['effect_of_method_alone']:+.4f})")
    print(f"  {chosen_name} @ a={chosen_alpha} -> {h['new_method_new_alpha']}   (total: {h['total_effect']:+.4f})")
    print(f"\nalpha responde por {h['share_attributable_to_alpha']:.0%}, metodo por {h['share_attributable_to_method']:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
