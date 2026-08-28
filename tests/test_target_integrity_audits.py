"""Integridade do alvo: semantica de zero, caminho de fonte, quebra estrutural.

Estes testes cobrem os achados de auditoria independente que diziam respeito a
**definicao do alvo**, nao a documentacao. Cada um deles substitui uma
afirmacao por uma medicao.

Nota sobre vacuidade
--------------------
`test_missing_not_silently_zeroed` (no outro arquivo) filtra `observed == False`,
conjunto vazio neste snapshot, e portanto passa sem exercitar nada. Ele nao foi
removido -- continua valido como invariante -- mas o caminho de risco de
verdade e coberto aqui, com dados sinteticos, em
`test_ingestion_fails_closed_on_unresolvable_municipality`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUDIT = PROJECT_ROOT / "outputs" / "apa_araripe" / "audit"
SNAP = PROJECT_ROOT / "data" / "snapshots" / "inpe_ce_pe_pi_satref_v1"
SCOPE_CSV = PROJECT_ROOT / "data" / "reference" / "apa_chapada_araripe.csv"


def load_audit(name: str) -> dict:
    """Carrega um artefato de auditoria exigindo que ele exista."""
    path = AUDIT / name
    if not path.exists():
        pytest.skip(f"auditoria {name} ainda nao gerada")
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# I5 -- semantica de zero
# --------------------------------------------------------------------------


def test_never_emitted_municipalities_are_enumerated_and_outside_apa():
    """Municipios sem nenhuma deteccao sao conhecidos e nao afetam a APA.

    Nao e defeito ter municipio com zero deteccao em 22 anos -- ilha oceanica e
    area urbana densa produzem exatamente isso. E defeito **nao saber quais
    sao**: um join quebrado apareceria como salto nessa contagem."""
    audit = load_audit("zero_semantics_audit.json")
    never = audit["municipalities_never_emitted_by_source"]

    target = pd.read_csv(SNAP / "municipality_month.csv")
    totals = target.groupby("geocodigo")["fire_count"].sum()
    measured = int((totals == 0).sum())
    assert measured == never["count"], (
        f"a auditoria diz {never['count']} municipios sem deteccao, o snapshot "
        f"tem {measured} -- a auditoria esta desatualizada"
    )

    scope = set(pd.read_csv(SCOPE_CSV)["geocodigo"].astype(int))
    listed = {m["geocodigo"] for m in never["list"]}
    assert not (listed & scope), (
        "municipio sem nenhuma deteccao dentro do escopo APA: todo resultado da "
        "APA passaria a depender de linhas indistinguiveis de dado ausente"
    )


def test_snapshot_records_zero_unresolved_names():
    """A ingestao registra que nenhum nome ficou por resolver.

    Este e o fato que impede um erro de join de virar zero silencioso."""
    manifest = json.loads((SNAP / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["n_unresolved_municipality_names"] == 0


def test_grid_minus_source_equals_the_never_emitted_set():
    """Amarra as duas contagens que descrevem o mesmo fato.

    A grade cobre todos os municipios da referencia IBGE; a fonte resolveu
    menos. A diferenca tem que ser exatamente o conjunto de municipios sem
    nenhuma deteccao -- se nao for, ha uma terceira causa de zero que ninguem
    esta contando."""
    manifest = json.loads((SNAP / "manifest.json").read_text(encoding="utf-8"))
    audit = load_audit("zero_semantics_audit.json")

    target = pd.read_csv(SNAP / "municipality_month.csv")
    in_grid = int(target["geocodigo"].nunique())
    resolved_from_source = int(manifest["counts"]["distinct_geocodigos_resolved"])
    never = audit["municipalities_never_emitted_by_source"]["count"]

    assert in_grid - resolved_from_source == never, (
        f"grade tem {in_grid} municipios, a fonte resolveu {resolved_from_source}, "
        f"diferenca {in_grid - resolved_from_source}, mas a auditoria lista {never} "
        "sem deteccao -- as contagens descrevem o mesmo fato e precisam fechar"
    )


def test_ingestion_fails_closed_on_unresolvable_municipality(monkeypatch):
    """Caminho de risco real: nome que a referencia nao conhece aborta a ingestao.

    Este e o teste que faltava. Roda offline, usando o ZIP de 2025 ja em cache,
    com a referencia IBGE truncada de proposito para forcar nomes nao
    resolvidos. Se a ingestao respondesse com zero em vez de erro, seria zero
    fabricado -- e o teste falharia."""
    from src.data import ingest_inpe_2025_scoring as mod

    cached = PROJECT_ROOT / "cache" / "inpe_2025_scoring" / "focos_br_ref_2025.zip"
    if not cached.exists():
        pytest.skip("ZIP de 2025 nao esta em cache; teste evita rede")

    real_reference = mod.load_ibge_reference()
    # Mantem so os municipios do Piaui: os focos de CE e PE passam a nao ter
    # correspondencia na referencia.
    truncated = real_reference[real_reference["uf"] == "PI"]
    assert len(truncated) < len(real_reference), "truncagem nao surtiu efeito"

    monkeypatch.setattr(mod, "load_ibge_reference", lambda: truncated)

    with pytest.raises(ValueError, match="nao resolvidos"):
        mod.build()


# --------------------------------------------------------------------------
# I7 -- equivalencia entre caminhos de distribuicao
# --------------------------------------------------------------------------


def test_distribution_paths_agree_on_overlap_year():
    """Treino e scoring vem de caminhos diferentes; num ano comum eles batem.

    O historico usa `EstadosBr_sat_ref/{UF}/`, o scoring de 2025 usa
    `Brasil_sat_ref/`. Se divergissem, a definicao do alvo mudaria entre treino
    e scoring e o resultado de 2025 nao significaria nada."""
    audit = load_audit("source_path_equivalence.json")
    assert audit["identical"] is True, (
        f"caminhos divergem em {audit['n_mismatched_cells']} celulas "
        f"(delta maximo {audit['max_abs_delta']})"
    )
    assert audit["cells_compared"] > 0
    assert audit["total_fires_national"] == audit["total_fires_per_uf"]


# --------------------------------------------------------------------------
# I6 -- quebra estrutural / homogeneidade de sensor
# --------------------------------------------------------------------------


def test_structural_break_screen_exists_and_is_honest():
    """O rastreio existe e declara o que nao consegue provar.

    A homogeneidade do satelite de referencia nao e verificavel a partir dos
    arquivos: eles nao tem coluna de satelite. Publicar o rastreio sem essa
    ressalva transformaria 'nao detectei' em 'nao existe'."""
    audit = load_audit("structural_break_screen.json")
    assert "what_this_cannot_do" in audit
    assert "nao prova" in audit["what_this_cannot_do"]
    assert audit["series"], "nenhuma serie rastreada"


def test_regional_factor_windows_do_not_straddle_a_detected_break():
    """Se ha quebra, nenhuma janela do fator regional pode cruza-la.

    O fator regional e razao observado/esperado nos 12 meses anteriores ao
    corte. Uma janela a cavalo da quebra misturaria dois regimes de medicao e
    contaminaria a correcao."""
    audit = load_audit("structural_break_screen.json")
    impact = audit.get("model_impact")
    assert impact is not None, "o rastreio precisa avaliar o impacto no modelo"

    if impact["latest_significant_break_year"] is None:
        pytest.skip("nenhuma quebra significativa detectada")

    assert impact["all_regional_windows_are_post_break"] is True, (
        f"janela do fator regional comeca em "
        f"{impact['regional_factor_earliest_window_start']}, antes ou sobre a "
        f"quebra de {impact['latest_significant_break_year']}"
    )


def test_structural_break_residual_risk_is_disclosed():
    """A climatologia atravessa a quebra, e isso precisa estar escrito.

    O fator regional corrige o nivel no agregado; a climatologia municipal, nao.
    Omitir isso deixaria a impressao de que a quebra foi neutralizada."""
    audit = load_audit("structural_break_screen.json")
    residual = audit["model_impact"]["residual_risk"]
    assert "climatologia" in residual.lower()
    assert "congelado" in residual.lower(), (
        "o risco residual precisa dizer por que nao foi corrigido agora"
    )


# --------------------------------------------------------------------------
# I3 / I4 -- honestidade do registro do G5 selado
# --------------------------------------------------------------------------

SEALED_DOC = AUDIT / "g5_final_sealed_result.md"


def sealed_doc() -> str:
    """Le o registro do teste selado."""
    if not SEALED_DOC.exists():
        pytest.skip("registro do G5 selado ausente")
    return SEALED_DOC.read_text(encoding="utf-8")


def test_sealed_record_does_not_repeat_refuted_claims():
    """As tres frases refutadas pela auditoria nao podem voltar.

    Cada uma afirmava mais do que o experimento sustenta. Ficam listadas na
    secao de correcoes do documento, mas nao como afirmacao corrente."""
    text = sealed_doc()
    corrections_at = text.find("## Correções aplicadas")
    assert corrections_at > 0, "o documento perdeu a secao de correcoes"
    body = text[:corrections_at]

    refuted = (
        "A subcobertura sistemática acabou",
        "O mecanismo de deslocamento temporal foi tratado com sucesso",
        "resolveu o problema que derrubou a versão anterior",
    )
    for phrase in refuted:
        assert phrase not in body, (
            f"afirmacao refutada voltou ao corpo do documento: {phrase!r}"
        )


def test_sealed_record_discloses_the_critical_slice_below_floor():
    """A fatia out-nov abaixo do piso precisa estar visivel, nao entre parenteses.

    E o valor operacionalmente mais importante e o gate nao o avalia."""
    text = sealed_doc()
    gate = json.loads(
        (PROJECT_ROOT / "outputs" / "apa_araripe" / "gates" / "G5_final_sealed_2025.json")
        .read_text(encoding="utf-8")
    )
    critical = float(gate["coverage_2025"]["critical_out_nov"])
    floor = float(gate["ic_bounds"][0])
    if critical >= floor:
        pytest.skip("fatia critica dentro do piso; a asserção nao se aplica")

    assert f"{critical:.4f}".replace(".", ",") in text, (
        "o valor da fatia critica precisa aparecer no registro"
    )
    assert "abaixo do piso" in text, (
        "o registro precisa dizer explicitamente que a fatia critica esta abaixo "
        "do piso, nao apenas mostrar o numero"
    )


def test_sealed_record_carries_the_alpha_method_decomposition():
    """Os numeros da decomposicao no texto batem com o artefato."""
    text = sealed_doc()
    audit = load_audit("g5_improvement_decomposition.json")
    eff = audit["effects"]["mean_fold_coverage"]

    for value in (eff["effect_of_alpha_alone"], eff["effect_of_method_alone"]):
        printed = f"{abs(value):.4f}".replace(".", ",")
        assert printed in text, (
            f"o registro nao publica o efeito isolado {value:+.4f}"
        )
    assert audit["alpha_dominates_method"] is True, (
        "se o metodo passar a dominar, o texto de correcao precisa ser reescrito"
    )


def test_next_round_requires_rewriting_the_gate_first():
    """O caminho registrado exige gate novo antes de novo holdout.

    Sem isso, a proxima rodada repetiria o mesmo criterio defeituoso."""
    text = sealed_doc()
    assert "Reescrever o gate antes de qualquer coisa" in text
    assert "2025 está queimado" in text
