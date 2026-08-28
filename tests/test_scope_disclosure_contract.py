"""Contrato de divulgacao: numero de um escopo nunca vale pelo outro.

Por que estes testes existem
----------------------------
Uma auditoria independente achou o pior tipo de defeito de documentacao: o
`README.md`, o `PRODUCTION_READINESS.md`, o artigo e o
`outputs/public_results_summary.json` apresentavam metricas do escopo legado
(Cariri/CE) sob o rotulo "Chapada do Araripe / CE-PE-PI", com gates marcados
PASS. O escopo APA tem WAPE mais alto e G5 reprovado. Um leitor tirava a
conclusao oposta da verdadeira, sem nenhum aviso.

Nao basta corrigir o texto: texto corrigido a mao volta a divergir na proxima
mudanca. Estes testes travam a propriedade.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMMARY = PROJECT_ROOT / "outputs" / "public_results_summary.json"
GENERATED_DOCS = ("README.md", "PRODUCTION_READINESS.md")
LEGACY_HEADING = "### Escopo legado: Cariri/CE -- NAO SE APLICA A APA"


@pytest.fixture(scope="module")
def summary() -> dict:
    """Carrega o summary publico."""
    assert SUMMARY.exists(), f"{SUMMARY} ausente -- rode o gerador"
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_summary_is_regenerable_and_current():
    """`--check` do gerador passa: nenhum numero publicado foi digitado a mao.

    Este e o teste que impede a regressao pela raiz. Se alguem editar um
    numero no README ou no summary, o gerador diverge e isso falha."""
    proc = subprocess.run(
        [sys.executable, "scripts/build_public_results_summary.py", "--check"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "documentacao divergente dos artefatos:\n"
        f"{proc.stdout}\n{proc.stderr}"
    )


def test_summary_separates_the_two_scopes(summary):
    """O summary tem os dois blocos, nomeados sem ambiguidade."""
    assert "current_scope" in summary
    assert "legacy_cariri_ce" in summary
    assert summary["current_scope"]["id"] == "apa_chapada_araripe"
    assert summary["legacy_cariri_ce"]["id"] == "cariri_ce_legacy"
    # O bloco legado precisa se declarar legado no proprio campo de status.
    assert "LEGADO" in summary["legacy_cariri_ce"]["status"]
    assert "NAO SE APLICA" in summary["legacy_cariri_ce"]["status"]


def test_no_top_level_scope_field_mixing_the_two(summary):
    """Nao existe campo de escopo unico no topo.

    A versao anterior tinha `"scope": "Chapada do Araripe / CE-PE-PI"` no topo
    e metricas do Ceara embaixo. Um unico rotulo cobrindo os dois conjuntos e
    exatamente o defeito."""
    assert "scope" not in summary, (
        "campo 'scope' no topo volta a sugerir que todas as metricas do arquivo "
        "pertencem a um escopo so"
    )
    assert "metrics" not in summary, (
        "bloco 'metrics' no topo nao tem escopo atribuido"
    )


LEGACY_VALUE_PATHS = [
    "extended_walk_forward_wape",
    "g3_v2_ce_monthly_scope_wape",
    "g3_v2_ce_seasonal_wape",
    "g3_v2_chapada_seasonal_wape",
    "g5_coverage_overall",
]


@pytest.mark.parametrize("doc", GENERATED_DOCS)
def test_legacy_numbers_appear_only_under_the_legacy_heading(doc, summary):
    """Todo numero legado impresso vem depois do cabecalho que o desqualifica.

    Percorre os valores legados reais (nao uma lista digitada) e exige que
    cada ocorrencia no documento esteja abaixo do cabecalho de legado."""
    text = (PROJECT_ROOT / doc).read_text(encoding="utf-8")
    assert LEGACY_HEADING in text, f"{doc} perdeu o cabecalho de escopo legado"
    legacy_start = text.index(LEGACY_HEADING)

    metrics = summary["legacy_cariri_ce"]["metrics"]
    for key in LEGACY_VALUE_PATHS:
        printed = f"{float(metrics[key]):.4f}"
        for match in re.finditer(re.escape(printed), text):
            assert match.start() > legacy_start, (
                f"{doc}: valor legado {key}={printed} aparece ANTES do cabecalho "
                "de escopo legado; um leitor pode ler como resultado da APA"
            )


@pytest.mark.parametrize("doc", GENERATED_DOCS)
def test_docs_state_apa_is_not_production_approved(doc, summary):
    """Nenhum documento pode afirmar aprovacao enquanto um gate da APA reprovar."""
    text = (PROJECT_ROOT / doc).read_text(encoding="utf-8")
    gates = summary["current_scope"]["gates"]
    if all(v == "PASS" for v in gates.values()):
        pytest.skip("todos os gates da APA passaram; a asserção nao se aplica")

    lowered = text.lower()
    for banned in ("approved for internal production", "aprovado para producao"):
        # "NAO APROVADO PARA PRODUCAO" contem "aprovado para producao"; por isso
        # a checagem olha a ocorrencia isolada, nao a negada.
        for m in re.finditer(re.escape(banned), lowered):
            prefix = lowered[max(0, m.start() - 6) : m.start()]
            assert "nao " in prefix or "não " in prefix, (
                f"{doc} afirma aprovacao de producao, mas os gates da APA sao {gates}"
            )


def test_article_carries_a_scope_banner():
    """O artigo declara, antes de qualquer numero, que e do escopo legado."""
    text = (PROJECT_ROOT / "docs" / "ARTIGO_FIRECAST.md").read_text(encoding="utf-8")
    head = text[:3000]
    assert "Aviso de escopo" in head, "artigo sem aviso de escopo no topo"
    assert "LEGADO" in head
    assert "36 municipios" in head or "36 municípios" in head, (
        "o aviso precisa dizer qual e o escopo que ele NAO cobre"
    )
    # O aviso tem que vir antes do primeiro numero do resumo.
    assert head.index("Aviso de escopo") < text.index("0,6430")


def test_article_is_not_mojibake():
    """O artigo publicado precisa ser UTF-8 legivel.

    Estava gravado como UTF-8 de um texto ja decodificado como cp1252, o que
    deixava todo acento ilegivel."""
    text = (PROJECT_ROOT / "docs" / "ARTIGO_FIRECAST.md").read_text(encoding="utf-8")
    for pattern in ("Ã§", "Ã£", "Ã­", "â€"):
        assert pattern not in text, f"mojibake residual no artigo: {pattern!r}"


def test_serving_uncertainty_follows_the_sealed_gate():
    """O serving le o veredito do teste selado, nao um gate antigo qualquer.

    Um PASS anterior nao pode sobrepor o FAIL do holdout selado."""
    from src.production.apa_araripe_serving import G5_GATES, uncertainty_status

    sealed = PROJECT_ROOT / "outputs" / "apa_araripe" / "gates" / "G5_final_sealed_2025.json"
    assert G5_GATES[0] == sealed, "o gate selado precisa ter precedencia"

    status, reason = uncertainty_status()
    gate = json.loads(sealed.read_text(encoding="utf-8"))
    if gate["status"] != "PASS":
        assert status == "not_validated"
        assert sealed.name in reason, "a razao precisa citar o gate que reprovou"


def test_known_limitations_are_measured_not_asserted(summary):
    """As duas ressalvas do G5 sao numeros derivados, nao texto opinativo."""
    lim = summary["current_scope"]["known_limitations"]

    one_sided = lim["intervals_effectively_one_sided"]
    assert one_sided["n_intervals"] > 0
    # A ressalva so faz sentido se a maioria dos pisos for de fato nao testavel.
    assert one_sided["share_lower_bound_non_informative"] > 0.5
    assert (
        one_sided["n_lower_bound_testable"] + one_sided["n_lower_bound_at_or_below_zero"]
        == one_sided["n_intervals"]
    )

    ceiling = lim["gate_ceiling_collides_with_nominal_level"]
    assert ceiling["ceiling_equals_nominal"] is True, (
        "se o teto deixar de coincidir com o nominal, esta ressalva precisa ser "
        "reescrita, nao mantida por inercia"
    )
    for uf, v in ceiling["by_uf"].items():
        assert 0.0 <= v["prob_perfect_method_fails_ceiling"] <= 1.0, uf


def test_gate_ceiling_defect_is_disclosed_in_docs(summary):
    """A falha de especificacao do gate esta publicada, nao so no relatorio interno.

    O FAIL do G5 e mantido. Mas publicar so o FAIL, sem dizer que o criterio
    reprova ate metodo perfeitamente calibrado, seria omitir a metade da
    informacao que muda a leitura."""
    ceiling = summary["current_scope"]["known_limitations"][
        "gate_ceiling_collides_with_nominal_level"
    ]
    worst = max(v["prob_perfect_method_fails_ceiling"] for v in ceiling["by_uf"].values())
    for doc in GENERATED_DOCS:
        text = (PROJECT_ROOT / doc).read_text(encoding="utf-8")
        assert f"{worst:.4f}" in text, (
            f"{doc} nao publica a probabilidade de um metodo perfeito reprovar "
            "no teto do gate"
        )
