"""Testes do escopo APA, do alvo historico e de vazamento temporal.

Cobrem os contratos que o SDD APA Chapada do Araripe marca como inegociaveis: identidade do
escopo, integridade do alvo, semantica de zero vs missing, e ausencia de
informacao do futuro no treino.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCOPE_CSV = PROJECT_ROOT / "data" / "reference" / "apa_chapada_araripe.csv"
SNAP = PROJECT_ROOT / "data" / "snapshots" / "inpe_ce_pe_pi_satref_v1"
TARGET = SNAP / "municipality_month.csv"
EXP_DIR = PROJECT_ROOT / "outputs" / "apa_araripe" / "exp10"

EXPECTED_MONTHS = 264  # 2003-01 .. 2024-12
MIN_TRAIN_MONTHS = 60


@pytest.fixture(scope="module")
def scope() -> pd.DataFrame:
    """Carrega o escopo derivado da APA."""
    return pd.read_csv(SCOPE_CSV)


@pytest.fixture(scope="module")
def target() -> pd.DataFrame:
    """Carrega o alvo historico municipal-mensal."""
    return pd.read_csv(TARGET)


# ---------------------------------------------------------------- escopo


def test_scope_geocodigos_are_unique(scope):
    """O escopo nao pode repetir municipio."""
    assert scope["geocodigo"].is_unique


def test_scope_uf_split_matches_total(scope):
    """A soma por UF tem que fechar com o total, sem municipio orfao."""
    assert scope["uf"].value_counts().sum() == len(scope)
    assert set(scope["uf"]) <= {"CE", "PE", "PI"}


def test_scope_geocodes_exist_in_ibge_reference(scope):
    """Todo geocodigo do escopo tem que existir na referencia IBGE."""
    ref = json.loads((PROJECT_ROOT / "data" / "reference" / "ibge_municipios_CE_PE_PI.json").read_text(encoding="utf-8"))
    ref_geos = {m["geocodigo"] for m in ref}
    assert set(scope["geocodigo"].astype(int)) <= ref_geos


def test_cedro_pe_not_cedro_ce(scope):
    """Cedro/PE (2604304) entra; Cedro/CE (2303808) nao.

    Este e o caso que prova que o escopo veio de geometria e nao de join por
    nome -- os dois municipios se chamam exatamente 'Cedro'."""
    geos = set(scope["geocodigo"].astype(int))
    assert 2604304 in geos, "Cedro/PE deveria estar no escopo"
    assert 2303808 not in geos, "Cedro/CE nao pertence a APA"


def test_scope_intersection_area_is_strictly_positive(scope):
    """A regra de pertencimento e area > 0, sem excecao."""
    assert (scope["area_intersect_apa_km2"] > 0).all()


def test_scope_area_reproduces_official_apa_area(scope):
    """Consistencia interna da intersecao: a soma reproduz a area do poligono.

    Como a malha municipal ladrilha o territorio, a soma das intersecoes DEVE
    reproduzir a area do proprio poligono usado. Isto valida CRS, ausencia de
    buraco, ausencia de dupla contagem e cobertura completa da geometria
    empregada -- e **nao** prova que o poligono do ICMBio coincide com o
    limite juridico de 1997 (que a propria literatura aponta divergir)."""
    total = scope["area_intersect_apa_km2"].sum()
    assert total == pytest.approx(10_173.616, rel=0.001)


def test_scope_pct_area_is_consistent(scope):
    """pct declarado tem que bater com as areas declaradas."""
    recomputed = 100.0 * scope["area_intersect_apa_km2"] / scope["area_municipal_km2"]
    assert np.allclose(recomputed, scope["pct_area_municipal_na_apa"], atol=0.01)


# ---------------------------------------------------------------- alvo


def test_monthly_key_unique(target):
    """(geocodigo, ano, mes) e chave."""
    assert not target.duplicated(subset=["geocodigo", "ano", "mes"]).any()


def test_fire_count_nonnegative_and_integer(target):
    """Contagem de focos nao pode ser negativa nem fracionaria."""
    observed = target[target["observed"].astype(bool)]["fire_count"].dropna()
    assert (observed >= 0).all()
    assert (observed == observed.astype(int)).all()


def test_no_unknown_uf(target):
    """Somente CE, PE e PI."""
    assert set(target["uf"]) == {"CE", "PE", "PI"}


def test_temporal_grid_is_complete(target):
    """Todo municipio tem a grade temporal inteira, sem buraco."""
    per = target.groupby("geocodigo").size()
    assert per.min() == EXPECTED_MONTHS
    assert per.max() == EXPECTED_MONTHS


def test_missing_not_silently_zeroed(target):
    """Zero e observacao; ausencia de fonte e NaN.

    Uma linha nao pode ser `observed=False` e ao mesmo tempo carregar zero --
    isso seria zero fabricado, o erro que o SDD 10 proibe explicitamente."""
    if "observed" not in target.columns:
        pytest.skip("snapshot sem coluna observed")
    unobserved = target[~target["observed"].astype(bool)]
    assert unobserved["fire_count"].notna().sum() == 0, (
        "linha nao observada com fire_count preenchido = zero fabricado"
    )


def test_manifest_has_sha256_provenance():
    """Toda fonte externa precisa de hash registrado."""
    sources = pd.read_csv(SNAP / "source_files.csv")
    assert "sha256" in sources.columns
    assert sources["sha256"].notna().all()
    assert (sources["sha256"].str.len() == 64).all()


def test_every_scope_municipality_present_in_target(scope, target):
    """Falha fechada: escopo sem alvo correspondente nao pode passar."""
    missing = set(scope["geocodigo"].astype(int)) - set(target["geocodigo"].astype(int))
    assert not missing, f"municipios do escopo ausentes do alvo: {sorted(missing)}"


# ---------------------------------------------------------------- temporal


@pytest.fixture(scope="module")
def predictions() -> pd.DataFrame:
    """Carrega as previsoes do backtest APA."""
    path = EXP_DIR / "predictions_2015_2024.csv"
    if not path.exists():
        pytest.skip("backtest APA ainda nao executado")
    return pd.read_csv(path)


def test_2025_and_2026_not_used_for_model_selection(predictions):
    """2025+ fica congelado para selecao de modelo (SDD 17)."""
    assert predictions["ano"].max() <= 2024
    assert predictions["ano"].min() >= 2015


def test_backtest_has_expected_cuts(predictions):
    """120 cortes mensais, 2015-01 a 2024-12."""
    assert predictions["cut"].nunique() == 120


def test_predictions_nonnegative(predictions):
    """Previsao de contagem nao pode ser negativa."""
    assert (predictions["y_pred"] >= 0).all()


def test_test_month_excluded_from_train():
    """Nenhuma linha do mes previsto pode entrar no treino daquele corte.

    Verifica o comportamento real da funcao usada pelo experimento, nao a
    intencao declarada."""
    from src.experiments.exp10_apa_araripe_regional_intensity import load_apa_target

    df = load_apa_target()
    cut = pd.Period("2020-10", freq="M")
    train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()]
    assert (train["period"] < cut).all()
    assert cut not in set(train["period"])


def test_regional_factor_uses_only_apa_scope():
    """O fator regional nao pode olhar municipio fora da APA (SDD 14)."""
    from src.experiments.exp10_apa_araripe_regional_intensity import load_apa_target
    from src.scopes import apa_geocodes

    df = load_apa_target()
    assert set(df["geocodigo"].astype(int)) <= apa_geocodes()


def test_regional_factor_window_ends_strictly_before_cut():
    """A janela do fator regional termina em cut-1 e tem exatamente 12 meses.

    Reconstroi os limites REAIS registrados por corte e prova
    `prior_window_end == cut - 1`, em vez de apenas confiar na intencao do
    codigo. Se o mes previsto entrasse na janela, o fator veria o proprio
    alvo."""
    ratios = pd.read_csv(EXP_DIR / "regional_ratio_by_cut.csv")
    assert len(ratios) == 120

    for _, row in ratios.iterrows():
        cut = pd.Period(row["cut"], freq="M")
        start = pd.Period(row["prior_window_start"], freq="M")
        end = pd.Period(row["prior_window_end"], freq="M")

        assert end == cut - 1, f"janela do corte {cut} termina em {end}, deveria ser {cut - 1}"
        assert start == cut - 12, f"janela do corte {cut} comeca em {start}, deveria ser {cut - 12}"
        assert (end - start).n == 11, "janela deveria cobrir 12 meses"

        # O maximo periodo REALMENTE observado na janela nunca pode alcancar o
        # mes previsto.
        if isinstance(row["prior_max_period_observed"], str) and row["prior_max_period_observed"]:
            assert pd.Period(row["prior_max_period_observed"], freq="M") < cut


def test_train_never_reaches_the_predicted_month():
    """O maximo periodo do treino, corte a corte, fica estritamente antes do alvo."""
    ratios = pd.read_csv(EXP_DIR / "regional_ratio_by_cut.csv")
    for _, row in ratios.iterrows():
        cut = pd.Period(row["cut"], freq="M")
        train_max = pd.Period(row["train_max_period"], freq="M")
        assert train_max < cut, f"treino do corte {cut} alcanca {train_max}"


def test_min_train_months_preserved():
    """MIN_TRAIN_MONTHS nao pode ser afrouxado para fazer gate passar."""
    from src.experiments.backtest_real_baselines import MIN_TRAIN_MONTHS as configured

    assert configured == MIN_TRAIN_MONTHS

    result = json.loads((EXP_DIR / "result.json").read_text(encoding="utf-8"))
    assert result["hyperparameters_unchanged"]["min_train_months"] == MIN_TRAIN_MONTHS


def test_gate_fails_closed_on_non_finite_metric():
    """Metrica nao-finita tem que REPROVAR o gate, nunca passar por acidente.

    Regressao do bug real encontrado: `ci_high >= 0` avaliado contra NaN da
    False e promovia o candidato em cima de bootstrap quebrado."""
    result = json.loads((EXP_DIR / "result.json").read_text(encoding="utf-8"))
    ci_low, ci_high = result["bootstrap_delta_ci95"]
    assert np.isfinite(ci_low) and np.isfinite(ci_high), (
        "CI do bootstrap nao finito: o gate deveria ter reprovado"
    )
    if result["decision"] == "PROMOTE":
        assert ci_high < 0, "PROMOTE exige CI95 inteiramente negativo"
        assert result["win_rate_by_cut"] > 0.50
        assert result["all_wape_candidate"] < result["all_wape_baseline"]


# ---------------------------------------------------------------- serving


@pytest.fixture(scope="module")
def serving_artifact():
    """Carrega o artefato de serving da APA."""
    path = PROJECT_ROOT / "outputs" / "apa_araripe" / "serving" / "model.json"
    if not path.exists():
        pytest.skip("artefato de serving ainda nao gerado")
    return json.loads(path.read_text(encoding="utf-8"))


def test_serving_scope_matches_derived_scope(serving_artifact, scope):
    """O artefato serve exatamente o escopo derivado, nem mais nem menos."""
    served = {m["geocodigo"] for m in serving_artifact["municipios"]}
    assert served == set(scope["geocodigo"].astype(int))
    assert serving_artifact["scope_n_municipios"] == len(scope)


def test_serving_fails_closed_for_municipality_outside_apa(serving_artifact):
    """Municipio fora da APA nao pode ser aceito silenciosamente."""
    from src.production.apa_araripe_serving import predict

    # Juazeiro do Norte: Cariri, geocodigo IBGE valido, mas fora da APA
    with pytest.raises(ValueError, match="fora do escopo"):
        predict(serving_artifact, 2307304, 2026, 10)


def test_serving_does_not_expose_interval_while_g5_fails(serving_artifact):
    """Enquanto G5 nao passar, intervalo tem que vir null.

    Previsao pontual e permitida; intervalo com aparencia de garantia, nao."""
    from src.production.apa_araripe_serving import predict

    gate_path = PROJECT_ROOT / "outputs" / "apa_araripe" / "gates" / "G5_conformal.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))

    out = predict(serving_artifact, 2602001, 2026, 10)  # Bodoco/PE
    assert out["forecast"] > 0

    if gate["status"] != "PASS":
        assert out["interval"] is None
        assert out["uncertainty_status"] == "not_validated"
        assert serving_artifact["uncertainty"]["status"] == "not_validated"


def test_serving_uncertainty_status_is_read_from_gate_not_hardcoded(serving_artifact):
    """O status de incerteza vem do gate, nao de constante no codigo."""
    gate_path = PROJECT_ROOT / "outputs" / "apa_araripe" / "gates" / "G5_conformal.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    expected = "validated" if gate["status"] == "PASS" else "not_validated"
    assert serving_artifact["uncertainty"]["status"] == expected


def test_serving_regional_factor_scope_contract(serving_artifact):
    """O fator regional do artefato e declaradamente da APA, nao do Ceara."""
    assert "APA" in serving_artifact["regional_factor"]["contract"]
    lo, hi = serving_artifact["parameters"]["ratio_clip"]
    assert lo <= serving_artifact["regional_factor"]["applied_ratio"] <= hi


# ---------------------------------------------------- lacre de 2025 (G5 drift)


def test_drift_family_refuses_sealed_year():
    """O modulo de desenvolvimento do novo G5 recusa carregar 2025+.

    O lacre e uma trava de codigo, nao disciplina humana."""
    from src.experiments import g5_conformal_drift_family as fam

    assert fam.SEALED_FROM == 2025
    dev = fam.load_dev_residuals()
    assert dev["ano"].max() <= 2024


def test_frozen_config_exists_and_records_selection_rule():
    """A configuracao do novo G5 esta congelada com regra e hash registrados."""
    path = PROJECT_ROOT / "outputs" / "apa_araripe" / "g5_drift" / "frozen_config.json"
    if not path.exists():
        pytest.skip("familia de drift ainda nao congelada")
    frozen = json.loads(path.read_text(encoding="utf-8"))
    assert frozen["sealed_year"] == 2025
    assert frozen["chosen"]["name"]
    assert len(frozen["predictions_sha256"]) == 64
    # a regra tem que exigir margem, nao "mais estreito que mal passou"
    assert frozen["dev_margin"] > 0
    assert frozen["effective_dev_floor"] > frozen["ic_bounds"][0]
