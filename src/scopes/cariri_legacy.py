"""Escopo legado "Chapada"/Cariri (29 municipios, apenas CE).

Este NAO e o escopo da APA Chapada do Araripe (ver ``apa_araripe.py``). E o
recorte historico usado pelos experimentos G4 anteriores a este SDD, obtido
por exclusao manual de 15 municipios do universo de 44 do Ceara -- nunca por
intersecao espacial com um poligono oficial da UC.

Fonte: ``data/snapshots/era5_grid_weights_chapada_v1/manifest.json`` +
``era5_cell_weights.csv`` (``excluded_geocodigos``, 44 - 15 = 29 mantidos).
O manifest documenta explicitamente: "Definicao de fronteira regional e um
julgamento razoavel, nao uma malha oficial de microrregiao IBGE."

Preservado aqui apenas para reprodutibilidade de experimentos historicos
(G4, WAPE sazonal 0,3723 etc.). NAO deve ser usado para nenhuma metrica nova
rotulada como "APA" ou "APA Chapada do Araripe" -- para isso, usar
``apa_araripe.load_apa_scope()``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = PROJECT_ROOT / "data" / "reference"
IBGE_REF_JSON = REFERENCE_DIR / "ibge_municipios_CE_PE_PI.json"
LEGACY_SNAPSHOT_CELL_WEIGHTS = (
    PROJECT_ROOT / "data" / "snapshots" / "era5_grid_weights_chapada_v1" / "era5_cell_weights.csv"
)
OUTPUT_CSV = REFERENCE_DIR / "cariri_ce_legacy.csv"

SOURCE_NOTE = (
    "data/snapshots/era5_grid_weights_chapada_v1/era5_cell_weights.csv "
    "(geocodigo unicos); exclusao documentada em manifest.json "
    "(excluded_geocodigos, 44 - 15 = 29 mantidos, uf CE apenas)"
)

# Os 29 geocodigos IBGE mantidos em era5_grid_weights_chapada_v1 (universo de
# 44 municipios do Ceara menos os 15 excluded_geocodigos do manifest). Fixado
# aqui porque e um artefato HISTORICO (snapshot de experimentos ja rodados),
# nao uma regra geoespacial re-derivavel -- ao contrario da APA, que nunca
# deve ser fixada assim (ver apa_araripe.py).
CARIRI_CE_LEGACY_GEOCODES: tuple[int, ...] = (
    2300101, 2300606, 2300804, 2301307, 2301604, 2301703, 2301802, 2301901,
    2302008, 2302503, 2302701, 2303204, 2304202, 2304301, 2305704, 2307106,
    2307205, 2307304, 2307502, 2308104, 2308302, 2308401, 2309201, 2310605,
    2311108, 2311959, 2312106, 2313252, 2313708,
)


def build_cariri_ce_legacy_csv() -> pd.DataFrame:
    """Regenera ``data/reference/cariri_ce_legacy.csv`` a partir do snapshot histórico.

    Cruza ``CARIRI_CE_LEGACY_GEOCODES`` com o nome/UF oficiais em
    ``ibge_municipios_CE_PE_PI.json`` (falha fechada se algum geocódigo não
    for encontrado) e persiste o CSV versionado. Idempotente: re-executar
    produz o mesmo arquivo byte a byte (mesma fonte, mesma ordenação).
    """
    if not IBGE_REF_JSON.exists():
        raise FileNotFoundError(f"referência IBGE ausente: {IBGE_REF_JSON}")
    ref = pd.read_json(IBGE_REF_JSON, encoding="utf-8-sig")

    wanted = set(CARIRI_CE_LEGACY_GEOCODES)
    sub = ref[ref["geocodigo"].isin(wanted)].copy()
    missing = wanted - set(sub["geocodigo"])
    if missing:
        raise ValueError(
            f"geocódigos do escopo legado Cariri/CE ausentes na referência IBGE: {sorted(missing)}"
        )
    if len(sub) != len(wanted):
        raise ValueError(
            f"esperado {len(wanted)} municípios, encontrados {len(sub)} — checar duplicatas na referência"
        )
    if not (sub["uf"] == "CE").all():
        bad = sub.loc[sub["uf"] != "CE", "geocodigo"].tolist()
        raise ValueError(f"escopo legado Cariri/CE deveria ser 100% CE, encontrado fora de CE: {bad}")

    sub = sub.rename(columns={"nome": "municipio"})
    sub["source"] = SOURCE_NOTE
    sub = sub.sort_values("geocodigo").reset_index(drop=True)
    sub = sub[["geocodigo", "municipio", "uf", "source"]]

    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    sub.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    return sub


def load_cariri_ce_legacy() -> pd.DataFrame:
    """Carrega o escopo legado Cariri/CE (29 municípios) já persistido.

    NÃO usar para métricas rotuladas "APA" — este é o recorte histórico
    pré-SDD-APA-33, não a APA Chapada do Araripe oficial.
    """
    if not OUTPUT_CSV.exists():
        raise FileNotFoundError(
            f"{OUTPUT_CSV} não existe. Rode `python -m src.scopes.cariri_legacy` para gerá-lo."
        )
    return pd.read_csv(OUTPUT_CSV, encoding="utf-8")


def cariri_ce_legacy_geocodes() -> set[int]:
    """Retorna o conjunto de geocódigos do escopo legado Cariri/CE (29, CE-only)."""
    return set(load_cariri_ce_legacy()["geocodigo"].astype(int))


if __name__ == "__main__":
    df = build_cariri_ce_legacy_csv()
    print(f"OK: {len(df)} municípios em {OUTPUT_CSV}")
    print(df.to_string(index=False))
