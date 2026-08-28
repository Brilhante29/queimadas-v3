"""Ingestao de 2025 para SCORING -- snapshot separado, jamais o de treino.

Por que separado
----------------
O snapshot `inpe_ce_pe_pi_satref_v1` (2003-2024) esta com hash registrado em
`outputs/apa_araripe/g5_drift/frozen_config.json` e em
`outputs/apa_araripe/exp10/result.json`. Alterar aquele diretorio quebraria a
rastreabilidade do congelamento. 2025 entra aqui, num snapshot proprio.

Fonte
-----
2025 nao existe no arquivo por UF (`EstadosBr_sat_ref/{UF}/` vai ate 2024).
Existe no arquivo Brasil (`Brasil_sat_ref/focos_br_ref_2025.zip`), do qual
filtramos CE, PE e PI. Mesmo produto `sat_ref` -- satelite de referencia --
que o historico, para nao trocar a definicao do alvo no meio do caminho.

Semantica de zero preservada: se o arquivo baixou e validou, ausencia de foco
no mes e zero observado. Se nao validou, e missing, nunca zero.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.ingest_inpe_ce_pe_pi_satref import (  # noqa: E402
    load_ibge_reference,
    normalize_text,
    repair_mojibake,
    safe_zip_member_names,
)

URL = (
    "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/"
    "Brasil_sat_ref/focos_br_ref_2025.zip"
)
CACHE = PROJECT_ROOT / "cache" / "inpe_2025_scoring"
OUT = PROJECT_ROOT / "data" / "snapshots" / "inpe_ce_pe_pi_satref_2025_scoring"
UFS = {"CEARA": "CE", "PERNAMBUCO": "PE", "PIAUI": "PI"}
YEAR = 2025
UA = {"User-Agent": "FireCast 2025 scoring ingestion"}


def download(force: bool = False) -> tuple[Path, str, int]:
    """Executa a etapa `download` do fluxo FireCast.

    Escrita atomica (.tmp -> rename). Arquivo parcial nunca vira valido."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "focos_br_ref_2025.zip"
    if path.exists() and not force:
        raw = path.read_bytes()
        return path, hashlib.sha256(raw).hexdigest(), len(raw)

    req = urllib.request.Request(URL, headers=UA)
    with urllib.request.urlopen(req, timeout=600) as resp:
        raw = resp.read()
    if not raw or raw[:2] != b"PK":
        raise ValueError("download de 2025 nao e um ZIP valido")
    tmp = path.with_suffix(".zip.tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)
    return path, hashlib.sha256(raw).hexdigest(), len(raw)


def build() -> dict:
    """Constroi a etapa `build` do fluxo FireCast."""
    OUT.mkdir(parents=True, exist_ok=True)
    path, sha, nbytes = download()

    reference = load_ibge_reference()
    ref_by_key = {
        (r.name_key, r.uf): int(r.geocodigo) for r in reference.itertuples()
    }

    with zipfile.ZipFile(path) as zf:
        members = safe_zip_member_names(zf)
        csvs = [m for m in members if m.lower().endswith(".csv")]
        if not csvs:
            raise ValueError(f"ZIP de 2025 sem CSV: {members}")
        frames = []
        for member in csvs:
            with zf.open(member) as fh:
                for chunk in pd.read_csv(
                    io.TextIOWrapper(fh, encoding="utf-8", errors="replace"),
                    chunksize=200_000,
                    usecols=lambda c: c.strip() in {"data_pas", "estado", "municipio"},
                ):
                    chunk.columns = [c.strip() for c in chunk.columns]
                    chunk["estado_key"] = chunk["estado"].map(
                        lambda v: normalize_text(repair_mojibake(str(v))).upper()
                    )
                    chunk = chunk[chunk["estado_key"].isin(UFS)]
                    if len(chunk):
                        frames.append(chunk)

    if not frames:
        raise ValueError("nenhum foco de CE/PE/PI encontrado em 2025")
    df = pd.concat(frames, ignore_index=True)
    df["uf"] = df["estado_key"].map(UFS)
    df["municipio_raw"] = df["municipio"].map(repair_mojibake)
    df["name_key"] = df["municipio_raw"].map(normalize_text)
    df["dt"] = pd.to_datetime(df["data_pas"], errors="coerce")
    df = df[df["dt"].notna()]
    df["ano"] = df["dt"].dt.year
    df["mes"] = df["dt"].dt.month
    df = df[df["ano"] == YEAR]

    pairs = df[["name_key", "uf", "municipio_raw"]].drop_duplicates()
    pairs["geocodigo"] = [
        ref_by_key.get((k, u)) for k, u in zip(pairs["name_key"], pairs["uf"])
    ]
    unresolved = pairs[pairs["geocodigo"].isna()]
    if len(unresolved):
        raise ValueError(
            "falha fechada: nomes de municipio nao resolvidos em 2025: "
            f"{unresolved[['municipio_raw', 'uf']].to_dict('records')[:10]}"
        )
    mapping = {
        (k, u): int(g) for k, u, g in zip(pairs["name_key"], pairs["uf"], pairs["geocodigo"])
    }
    df["geocodigo"] = [mapping[(k, u)] for k, u in zip(df["name_key"], df["uf"])]

    counts = (
        df.groupby(["geocodigo", "uf", "ano", "mes"]).size().reset_index(name="fire_count")
    )

    # Grade completa: todo municipio da referencia x meses observados de 2025.
    months = sorted(counts["mes"].unique())
    grid = (
        reference.assign(key=1)
        .merge(pd.DataFrame({"mes": months, "key": 1}), on="key")
        .drop(columns="key")
    )
    grid["ano"] = YEAR
    grid = grid.rename(columns={"nome": "municipio"})[
        ["geocodigo", "uf", "municipio", "ano", "mes"]
    ]
    out = grid.merge(
        counts[["geocodigo", "ano", "mes", "fire_count"]],
        on=["geocodigo", "ano", "mes"],
        how="left",
    )
    out["fire_count"] = out["fire_count"].fillna(0).astype(int)
    out["observed"] = True  # arquivo baixou e validou -> ausencia e zero real
    out = out.sort_values(["geocodigo", "mes"]).reset_index(drop=True)
    out.to_csv(OUT / "municipality_month.csv", index=False, encoding="utf-8")

    manifest = {
        "snapshot": "inpe_ce_pe_pi_satref_2025_scoring",
        "purpose": "SCORING de 2025 -- separado do snapshot de treino, que esta hasheado no congelamento",
        "source_url": URL,
        "source_sha256": sha,
        "source_bytes": nbytes,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "sensor_contract": "sat_ref (satelite de referencia INPE), mesmo produto do historico",
        "year": YEAR,
        "months_available": [int(m) for m in months],
        "ufs": sorted(UFS.values()),
        "n_municipalities": int(out["geocodigo"].nunique()),
        "n_rows": int(len(out)),
        "total_fires": int(out["fire_count"].sum()),
        "zero_semantics": "arquivo validado -> ausencia de foco no mes e zero observado",
        "unresolved_municipality_names": 0,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    m = build()
    print(json.dumps(
        {k: m[k] for k in (
            "source_sha256", "months_available", "n_municipalities",
            "n_rows", "total_fires", "unresolved_municipality_names",
        )},
        indent=2, ensure_ascii=False,
    ))
