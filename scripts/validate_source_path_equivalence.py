"""Cruza os dois caminhos de distribuicao do INPE num ano de sobreposicao.

O problema
----------
O historico 2003-2024 vem de `EstadosBr_sat_ref/{UF}/focos_br_{uf}_ref_{ano}.zip`
(um arquivo por estado por ano). O scoring de 2025 vem de
`Brasil_sat_ref/focos_br_ref_{ano}.zip` (arquivo nacional unico). O manifest de
2025 afirma "mesmo produto do historico".

Ate aqui isso era **assercao**: nenhum ano foi baixado dos dois caminhos e
comparado. Se os caminhos divergirem, a definicao do alvo muda entre treino e
scoring, e o resultado de 2025 fica sem sentido.

O teste
-------
2024 existe nos dois caminhos. Baixa os dois, agrega por (geocodigo, mes) para
CE/PE/PI e compara celula a celula. Igualdade exata sustenta a afirmacao;
qualquer divergencia a derruba e precisa aparecer no relatorio.

Uso
---
```bash
python scripts/validate_source_path_equivalence.py          # ano 2024
python scripts/validate_source_path_equivalence.py --year 2023
```
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.ingest_inpe_ce_pe_pi_satref import (  # noqa: E402
    load_ibge_reference,
    normalize_text,
    repair_mojibake,
    safe_zip_member_names,
)

BASE = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual"
NATIONAL = BASE + "/Brasil_sat_ref/focos_br_ref_{year}.zip"
PER_UF = BASE + "/EstadosBr_sat_ref/{uf}/focos_br_{uf_low}_ref_{year}.zip"
CACHE = PROJECT_ROOT / "cache" / "source_path_equivalence"
OUT = PROJECT_ROOT / "outputs" / "apa_araripe" / "audit" / "source_path_equivalence.json"
UF_NAMES = {"CEARA": "CE", "PERNAMBUCO": "PE", "PIAUI": "PI"}
UA = {"User-Agent": "FireCast source-path equivalence check"}


def fetch(url: str, name: str) -> tuple[Path, str]:
    """Baixa com escrita atomica e devolve (caminho, sha256)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if path.exists():
        raw = path.read_bytes()
        return path, hashlib.sha256(raw).hexdigest()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=1800) as resp:
        raw = resp.read()
    if not raw or raw[:2] != b"PK":
        raise ValueError(f"nao e ZIP valido: {url}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)
    return path, hashlib.sha256(raw).hexdigest()


def read_zip_counts(path: Path, year: int, ufs: set[str] | None) -> pd.DataFrame:
    """Le um ZIP de focos e agrega para (geocodigo, mes).

    Usa exatamente as mesmas funcoes de normalizacao e a mesma referencia IBGE
    da ingestao de producao -- comparar com outro normalizador mediria o
    normalizador, nao a fonte."""
    reference = load_ibge_reference()
    ref_by_key = {(r.name_key, r.uf): int(r.geocodigo) for r in reference.itertuples()}

    frames = []
    with zipfile.ZipFile(path) as zf:
        for member in [m for m in safe_zip_member_names(zf) if m.lower().endswith(".csv")]:
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
                    if ufs is not None:
                        chunk = chunk[chunk["estado_key"].isin(ufs)]
                    if len(chunk):
                        frames.append(chunk)

    if not frames:
        return pd.DataFrame(columns=["geocodigo", "mes", "fire_count"])

    df = pd.concat(frames, ignore_index=True)
    df["uf"] = df["estado_key"].map(UF_NAMES)
    df = df[df["uf"].notna()]
    df["name_key"] = df["municipio"].map(lambda v: normalize_text(repair_mojibake(str(v))))
    df["dt"] = pd.to_datetime(df["data_pas"], errors="coerce")
    df = df[df["dt"].notna()]
    df = df[df["dt"].dt.year == year]
    df["mes"] = df["dt"].dt.month

    df["geocodigo"] = [
        ref_by_key.get((k, u)) for k, u in zip(df["name_key"], df["uf"])
    ]
    unresolved = df[df["geocodigo"].isna()]
    if len(unresolved):
        raise ValueError(
            "falha fechada: nomes nao resolvidos: "
            f"{unresolved['municipio'].drop_duplicates().tolist()[:10]}"
        )
    df["geocodigo"] = df["geocodigo"].astype(int)
    return (
        df.groupby(["geocodigo", "mes"]).size().reset_index(name="fire_count")
    )


def main() -> int:
    """Compara os dois caminhos e grava o relatorio."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2024)
    args = parser.parse_args()
    year = args.year

    nat_path, nat_sha = fetch(NATIONAL.format(year=year), f"brasil_{year}.zip")
    national = read_zip_counts(nat_path, year, ufs=set(UF_NAMES))

    per_uf_frames = []
    per_uf_sha = {}
    for uf in ("CE", "PE", "PI"):
        url = PER_UF.format(uf=uf, uf_low=uf.lower(), year=year)
        p, sha = fetch(url, f"{uf.lower()}_{year}.zip")
        per_uf_sha[uf] = sha
        per_uf_frames.append(read_zip_counts(p, year, ufs=None))
    per_uf = (
        pd.concat(per_uf_frames, ignore_index=True)
        .groupby(["geocodigo", "mes"], as_index=False)["fire_count"]
        .sum()
    )

    merged = national.merge(
        per_uf, on=["geocodigo", "mes"], how="outer", suffixes=("_national", "_per_uf")
    ).fillna({"fire_count_national": 0, "fire_count_per_uf": 0})
    merged["delta"] = merged["fire_count_national"] - merged["fire_count_per_uf"]
    mismatches = merged[merged["delta"] != 0]

    identical = len(mismatches) == 0
    report = {
        "check": "equivalencia entre caminhos de distribuicao do INPE",
        "why": (
            "O treino usa EstadosBr_sat_ref (por UF) e o scoring de 2025 usa "
            "Brasil_sat_ref (nacional). Se os caminhos divergirem, a definicao do "
            "alvo muda entre treino e scoring."
        ),
        "year_tested": year,
        "national_url": NATIONAL.format(year=year),
        "national_sha256": nat_sha,
        "per_uf_sha256": per_uf_sha,
        "cells_compared": int(len(merged)),
        "total_fires_national": int(merged["fire_count_national"].sum()),
        "total_fires_per_uf": int(merged["fire_count_per_uf"].sum()),
        "n_mismatched_cells": int(len(mismatches)),
        "max_abs_delta": int(merged["delta"].abs().max()) if len(merged) else 0,
        "identical": bool(identical),
        "verdict": (
            "SUSTENTADA: os dois caminhos entregam contagens identicas celula a "
            "celula neste ano; tratar 2025 como o mesmo produto e justificado."
            if identical
            else "REFUTADA: os caminhos divergem; o alvo de 2025 nao e comparavel "
            "ao de treino sem correcao."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if not identical:
        report["worst_mismatches"] = (
            mismatches.reindex(mismatches["delta"].abs().sort_values(ascending=False).index)
            .head(20)
            .to_dict("records")
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "year_tested", "cells_compared", "total_fires_national",
        "total_fires_per_uf", "n_mismatched_cells", "identical",
    )}, indent=2))
    return 0 if identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
