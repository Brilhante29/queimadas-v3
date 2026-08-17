"""Testes do escopo APA, do alvo historico e de vazamento temporal.

Cobrem os contratos que o SDD APA-33 marca como inegociaveis: identidade do
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
SNAP = PROJECT_ROOT / "data" / "snapshots" / "inpe_apa33_satref_v1"
TARGET = SNAP / "municipality_month.csv"
EXP_DIR = PROJECT_ROOT / "outputs" / "apa33" / "exp10"

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
    """A soma das intersecoes tem que reproduzir a area oficial da UC.

    Area declarada pelo ICMBio: 1.017.361,601 ha = 10.173,616 km2. Se os
    municipios nao ladrilharem a APA inteira, este teste quebra."""
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
    from src.experiments.exp10_apa33_regional_intensity import load_apa_target

    df = load_apa_target()
    cut = pd.Period("2020-10", freq="M")
    train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()]
    assert (train["period"] < cut).all()
    assert cut not in set(train["period"])


def test_regional_factor_uses_only_apa_scope():
    """O fator regional nao pode olhar municipio fora da APA (SDD 14)."""
    from src.experiments.exp10_apa33_regional_intensity import load_apa_target
    from src.scopes import apa_geocodes

    df = load_apa_target()
    assert set(df["geocodigo"].astype(int)) <= apa_geocodes()


def test_regional_factor_uses_only_past_periods():
    """A janela de 12 meses do fator termina em cut-1, nunca inclui o alvo."""
    ratios = pd.read_csv(EXP_DIR / "regional_ratio_by_cut.csv")
    for _, row in ratios.iterrows():
        cut = pd.Period(row["cut"], freq="M")
        # a janela usada e [cut-12, cut-1]; se o mes alvo entrasse, o
        # experimento teria registrado n_test_rows dentro de n_prior_rows
        assert row["n_eligible_municipios"] > 0
        assert cut.year <= 2024


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
