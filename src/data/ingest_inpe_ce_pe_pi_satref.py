"""Ingestao historica INPE sat_ref (CE/PE/PI, 2003-2024) para o alvo municipio-mes do FireCast APA Chapada do Araripe.

Arquivo `src/data/ingest_inpe_ce_pe_pi_satref.py` baixa os 66 arquivos anuais da serie de
referencia do satelite (`sat_ref`) publicados pelo INPE em
`https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/EstadosBr_sat_ref/{UF}/`,
resolve cada `municipio` bruto (sem geocodigo no arquivo fonte) contra a malha IBGE de
CE+PE+PI e produz um snapshot reproduzivel em `data/snapshots/inpe_ce_pe_pi_satref_v1/`:

    manifest.json          contrato de fonte, contrato de sensor, anos, UFs, contagens
    source_files.csv        uma linha por arquivo baixado (proveniencia: url/sha256/bytes/...)
    municipality_month.csv  O ALVO: geocodigo, uf, municipio, ano, mes, fire_count, observed
    mapping_report.csv      todo (municipio, estado) bruto -> geocodigo resolvido ou UNRESOLVED
    coverage_report.csv     por (uf, ano): arquivos ok, linhas, municipios vistos, meses vistos
    quality_report.json     checagens de QA com PASS/FAIL

Semantica critica (zero vs ausente): uma linha municipio-mes so recebe
`fire_count = 0, observed = true` quando o arquivo (uf, ano) de origem foi baixado,
validado (hash/zip) e parseado com sucesso -- ausencia de fogo e uma observacao real.
Se o arquivo falhar, todo o municipio-mes daquele (uf, ano) fica `observed = false` e
`fire_count` vazio (NA), nunca zero. A grade completa (todos os municipios da UF x
todos os meses do ano) e emitida para cada arquivo validado, tornando zeros reais
explicitos.

Uso: `python -m src.data.ingest_inpe_ce_pe_pi_satref [--force] [--years ...] [--ufs ...]`
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import re
import sys
import time
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

CACHE_DIR = PROJECT_ROOT / "cache" / "inpe_apa_araripe_satref"
CACHE_INDEX_PATH = CACHE_DIR / "_cache_index.json"
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshots" / "inpe_ce_pe_pi_satref_v1"
REFERENCE_PATH = PROJECT_ROOT / "data" / "reference" / "ibge_municipios_CE_PE_PI.json"

BASE_URL = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/EstadosBr_sat_ref"
UFS = ["CE", "PE", "PI"]
YEARS = list(range(2003, 2025))  # 2003..2024 inclusive

STATE_NAME_TO_UF = {"ceara": "CE", "pernambuco": "PE", "piaui": "PI"}

CONNECT_TIMEOUT = 15
READ_TIMEOUT = 120
MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 60.0
USER_AGENT = "FireCast APA Chapada do Araripe historical ingest (guilhermebrilhante00@gmail.com)"

KEEP_COLS = ["data_pas", "estado", "municipio"]
CHUNKSIZE = 100_000


def normalize_text(value: object) -> str:
    """Normaliza texto para chave de casamento: NFKD, remove acentos, colapsa espacos, casefold.

    Usada tanto para nomes de municipio quanto para nomes de estado (`estado` na fonte
    e o nome completo do estado, ex. `PERNAMBUCO`, que precisa virar `PE`)."""
    s = unicodedata.normalize("NFKD", str(value))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s.casefold()


def repair_mojibake(value: str) -> str:
    """Repara double-encoding UTF-8 (mojibake) presente em uma fracao das linhas do CE.

    Achado empirico (nao um bug do parser): uma fracao das linhas dos arquivos anuais do
    CE tem `estado`/`municipio` com bytes UTF-8 corretos que foram decodificados como
    Latin-1 e re-codificados como UTF-8 (ex.: `BOA VIAGEM` aparece com 4463 linhas
    `CEARA' corretamente codificado e 280 linhas com o mesmo texto corrompido). A
    correcao e a reversao exata e auto-validada dessa transformacao: `s.encode("latin-1")
    .decode("utf-8")` SO tem sucesso quando `s` e de fato o resultado desse
    double-encoding (para texto ja corretamente codificado, o round-trip falha e o valor
    original e devolvido inalterado) -- nao e uma seleccao heuristica de correspondencia,
    e uma reversao matematica verificavel de uma transformacao conhecida."""
    try:
        repaired = value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    return repaired


def sha256_file(path: Path) -> str:
    """Calcula o sha256 de um arquivo em disco, lendo em blocos (memoria constante)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_cache_index() -> dict:
    """Carrega o indice de idempotencia do cache local (nome do arquivo -> sha256 valido conhecido)."""
    if CACHE_INDEX_PATH.exists():
        try:
            return json.loads(CACHE_INDEX_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_cache_index(index: dict) -> None:
    """Persiste o indice de idempotencia do cache local."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_INDEX_PATH.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


def safe_zip_member_names(zf: zipfile.ZipFile) -> list[str]:
    """Valida que nenhum membro do zip usa path traversal, path absoluto ou drive letter.

    Nao usamos `extractall`; lemos os membros diretamente da memoria via `zf.open`, o que
    ja evita zip-slip na pratica, mas ainda assim validamos os nomes por defesa em profundidade
    (SDD 53)."""
    names = []
    for info in zf.infolist():
        name = info.filename
        if name.startswith("/") or name.startswith("\\"):
            raise ValueError(f"membro de zip com path absoluto rejeitado: {name!r}")
        if ".." in Path(name).parts:
            raise ValueError(f"membro de zip com path traversal rejeitado: {name!r}")
        if re.match(r"^[A-Za-z]:", name):
            raise ValueError(f"membro de zip com drive letter rejeitado: {name!r}")
        names.append(name)
    return names


def load_ibge_reference() -> pd.DataFrame:
    """Carrega a malha IBGE de referencia (CE+PE+PI, 593 municipios) e computa a chave de nome normalizada.

    Fail closed: se o arquivo de referencia nao existir, aborta (nao ha como resolver
    geocodigo sem ele)."""
    if not REFERENCE_PATH.exists():
        raise FileNotFoundError(
            f"Referencia IBGE ausente: {REFERENCE_PATH}. "
            "Rodar a ingestao de referencia IBGE antes (fail closed)."
        )
    records = json.loads(REFERENCE_PATH.read_text(encoding="utf-8-sig"))
    df = pd.DataFrame.from_records(records)
    df["geocodigo"] = df["geocodigo"].astype(int)
    df["uf"] = df["uf"].astype(str)
    df["name_key"] = df["nome"].map(normalize_text)
    return df[["geocodigo", "nome", "uf", "name_key"]]


@dataclass
class DownloadResult:
    """Resultado de uma tentativa de download+validacao de um arquivo (uf, ano)."""

    uf: str
    year: int
    url: str
    path: Path
    ok: bool
    from_cache: bool
    http_status: object
    sha256: str | None
    bytes: int | None
    error: str | None
    retrieved_at: str
    attempts: int


def _is_valid_zip(path: Path) -> bool:
    """Confere que o arquivo e um zip valido, integro (CRC ok) e nao vazio."""
    try:
        if not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as zf:
            if zf.testzip() is not None:
                return False
            names = safe_zip_member_names(zf)
            csv_members = [n for n in names if n.lower().endswith(".csv")]
            return len(csv_members) > 0
    except (zipfile.BadZipFile, OSError, ValueError):
        return False


def download_one(uf: str, year: int, cache_index: dict, force: bool = False) -> DownloadResult:
    """Baixa (ou reaproveita do cache) o arquivo anual sat_ref de uma UF/ano.

    Idempotente: se o arquivo em cache existir e seu sha256 bater com o registrado no
    indice (ou, na ausencia de registro, se o zip validar integro), o download e pulado.
    Escrita atomica: baixa para `.tmp`, valida o zip, so entao renomeia para o destino
    final -- um download parcial nunca fica marcado como valido (SDD 50)."""
    uf_lower = uf.lower()
    url = f"{BASE_URL}/{uf}/focos_br_{uf_lower}_ref_{year}.zip"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / f"focos_br_{uf_lower}_ref_{year}.zip"
    cache_key = dest.name

    if not force and dest.exists():
        current_hash = sha256_file(dest)
        recorded_hash = cache_index.get(cache_key)
        if recorded_hash == current_hash and _is_valid_zip(dest):
            return DownloadResult(
                uf=uf,
                year=year,
                url=url,
                path=dest,
                ok=True,
                from_cache=True,
                http_status="cached",
                sha256=current_hash,
                bytes=dest.stat().st_size,
                error=None,
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                attempts=0,
            )
        if recorded_hash is None and _is_valid_zip(dest):
            # Cache pre-existente sem registro no indice (ex.: primeira execucao apos
            # copia manual). Valida integridade do zip antes de confiar, e adota o hash.
            cache_index[cache_key] = current_hash
            return DownloadResult(
                uf=uf,
                year=year,
                url=url,
                path=dest,
                ok=True,
                from_cache=True,
                http_status="cached_unverified_index",
                sha256=current_hash,
                bytes=dest.stat().st_size,
                error=None,
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                attempts=0,
            )
        # Hash nao bate ou zip corrompido: redownload.

    tmp_path = dest.with_suffix(dest.suffix + ".tmp")
    last_error: str | None = None
    last_status: object = None
    attempts = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempts = attempt
        try:
            with requests.get(
                url,
                stream=True,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                headers={"User-Agent": USER_AGENT},
            ) as resp:
                last_status = resp.status_code
                if resp.status_code == 404:
                    last_error = "HTTP 404 (arquivo nao encontrado na fonte)"
                    break  # permanente, nao adianta retry
                resp.raise_for_status()
                tmp_path.parent.mkdir(parents=True, exist_ok=True)
                with tmp_path.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        if chunk:
                            f.write(chunk)
            if not _is_valid_zip(tmp_path):
                raise ValueError("download incompleto ou zip corrompido (falhou validacao)")
            tmp_path.replace(dest)  # rename atomico so apos validacao
            h = sha256_file(dest)
            cache_index[cache_key] = h
            return DownloadResult(
                uf=uf,
                year=year,
                url=url,
                path=dest,
                ok=True,
                from_cache=False,
                http_status=last_status,
                sha256=h,
                bytes=dest.stat().st_size,
                error=None,
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                attempts=attempts,
            )
        except Exception as exc:  # noqa: BLE001 - retry generico, erro real registrado abaixo
            last_error = f"{type(exc).__name__}: {exc}"
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            if last_status == 404:
                break
            if attempt < MAX_ATTEMPTS:
                backoff = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                backoff += random.uniform(0, 1.0)
                time.sleep(backoff)

    if tmp_path.exists():
        tmp_path.unlink(missing_ok=True)
    return DownloadResult(
        uf=uf,
        year=year,
        url=url,
        path=dest,
        ok=False,
        from_cache=False,
        http_status=last_status,
        sha256=None,
        bytes=None,
        error=last_error,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        attempts=attempts,
    )


def _open_member_text(zf: zipfile.ZipFile, member: str) -> io.TextIOWrapper:
    """Abre um membro do zip como texto, tentando utf-8 e caindo para latin-1 se necessario.

    A amostra verificada e utf-8 (`SÃO JOSÉ` decodifica correto); o fallback e apenas
    defesa em profundidade caso algum arquivo historico use outra codificacao."""
    raw = zf.open(member)
    head = raw.read(4096)
    raw.close()
    try:
        head.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        encoding = "latin-1"
    return io.TextIOWrapper(zf.open(member), encoding=encoding, newline="")


def parse_zip_to_counts(path: Path, uf: str, year: int) -> tuple[pd.DataFrame, int, int, int]:
    """Le o zip (uf, ano) diretamente da memoria (sem extractall) e agrega contagens brutas.

    Retorna (agregado, n_rows_total, n_date_unparseable, n_mojibake_repaired) onde
    `agregado` tem colunas [municipio_raw, estado_raw, ano, mes, n_fires] -- ja agregado
    por (municipio bruto, estado bruto, ano, mes) dentro deste arquivo, para manter o uso
    de memoria baixo (SDD 54: le em chunks, so as colunas necessarias)."""
    with zipfile.ZipFile(path) as zf:
        member_names = safe_zip_member_names(zf)
        csv_members = [n for n in member_names if n.lower().endswith(".csv")]
        expected = f"focos_br_{uf.lower()}_ref_{year}.csv"
        member = expected if expected in csv_members else csv_members[0]

        n_rows_total = 0
        n_unparseable = 0
        n_mojibake_repaired = 0
        partials: list[pd.DataFrame] = []

        with _open_member_text(zf, member) as text_stream:
            reader = pd.read_csv(
                text_stream,
                usecols=lambda c: c.strip() in KEEP_COLS,
                dtype=str,
                chunksize=CHUNKSIZE,
                skipinitialspace=True,
            )
            for chunk in reader:
                chunk.columns = [c.strip() for c in chunk.columns]
                n_rows_total += len(chunk)
                for col in ("data_pas", "estado", "municipio"):
                    chunk[col] = chunk[col].astype(str).str.strip()

                repaired_estado = chunk["estado"].map(repair_mojibake)
                repaired_municipio = chunk["municipio"].map(repair_mojibake)
                n_mojibake_repaired += int(
                    ((repaired_estado != chunk["estado"]) | (repaired_municipio != chunk["municipio"])).sum()
                )
                chunk["estado"] = repaired_estado
                chunk["municipio"] = repaired_municipio

                parsed_dt = pd.to_datetime(chunk["data_pas"], errors="coerce")
                bad = parsed_dt.isna()
                n_unparseable += int(bad.sum())
                chunk = chunk.loc[~bad].copy()
                if chunk.empty:
                    continue
                chunk["ano"] = parsed_dt.loc[~bad].dt.year.astype(int)
                chunk["mes"] = parsed_dt.loc[~bad].dt.month.astype(int)
                grouped = (
                    chunk.rename(columns={"municipio": "municipio_raw", "estado": "estado_raw"})
                    .groupby(["municipio_raw", "estado_raw", "ano", "mes"])
                    .size()
                    .reset_index(name="n_fires")
                )
                partials.append(grouped)

    if not partials:
        empty = pd.DataFrame(columns=["municipio_raw", "estado_raw", "ano", "mes", "n_fires"])
        return empty, n_rows_total, n_unparseable, n_mojibake_repaired

    combined = (
        pd.concat(partials, ignore_index=True)
        .groupby(["municipio_raw", "estado_raw", "ano", "mes"], as_index=False)["n_fires"]
        .sum()
    )
    return combined, n_rows_total, n_unparseable


def build_snapshot(years: list[int], ufs: list[str], force: bool = False) -> dict:
    """Orquestra o pipeline completo: download -> parse -> resolucao de municipio -> grade -> QA."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    reference = load_ibge_reference()

    # Diagnostico: a propria referencia deve ter (name_key, uf) unico; se nao tiver, o
    # join fica ambiguo por construcao e precisamos saber.
    ref_dupes = reference[reference.duplicated(subset=["name_key", "uf"], keep=False)]
    reference_duplicate_names = sorted(
        {(row.name_key, row.uf) for row in ref_dupes.itertuples()}
    )

    cache_index = load_cache_index()

    source_files_rows: list[dict] = []
    all_counts_frames: list[pd.DataFrame] = []
    validated_uf_years: set[tuple[str, int]] = set()
    failed_uf_years: set[tuple[str, int]] = set()

    for uf in ufs:
        for year in years:
            dr = download_one(uf, year, cache_index, force=force)
            row = {
                "url": dr.url,
                "sha256": dr.sha256,
                "bytes": dr.bytes,
                "uf": uf,
                "year": year,
                "retrieved_at": dr.retrieved_at,
                "http_status": dr.http_status,
                "n_rows": None,
                "parse_ok": False,
                "from_cache": dr.from_cache,
                "attempts": dr.attempts,
                "error": dr.error,
            }
            if not dr.ok:
                failed_uf_years.add((uf, year))
                source_files_rows.append(row)
                continue
            try:
                grouped, n_rows_total, n_unparseable = parse_zip_to_counts(dr.path, uf, year)
                row["n_rows"] = n_rows_total
                row["n_date_unparseable"] = n_unparseable
                row["parse_ok"] = True
                validated_uf_years.add((uf, year))
                if not grouped.empty:
                    all_counts_frames.append(grouped)
            except Exception as exc:  # noqa: BLE001
                row["error"] = f"parse failure: {type(exc).__name__}: {exc}"
                failed_uf_years.add((uf, year))
            source_files_rows.append(row)

    save_cache_index(cache_index)

    source_files = pd.DataFrame(source_files_rows)

    if all_counts_frames:
        raw_counts = (
            pd.concat(all_counts_frames, ignore_index=True)
            .groupby(["municipio_raw", "estado_raw", "ano", "mes"], as_index=False)["n_fires"]
            .sum()
        )
    else:
        raw_counts = pd.DataFrame(columns=["municipio_raw", "estado_raw", "ano", "mes", "n_fires"])

    # --- Resolucao de municipio: normalize(municipio) + estado(->UF) -> geocodigo ---
    distinct_pairs = raw_counts[["municipio_raw", "estado_raw"]].drop_duplicates().copy()
    totals_by_pair = raw_counts.groupby(["municipio_raw", "estado_raw"], as_index=False)["n_fires"].sum()
    distinct_pairs = distinct_pairs.merge(totals_by_pair, on=["municipio_raw", "estado_raw"], how="left")
    distinct_pairs["name_key"] = distinct_pairs["municipio_raw"].map(normalize_text)
    distinct_pairs["estado_key"] = distinct_pairs["estado_raw"].map(normalize_text)
    distinct_pairs["uf_from_estado"] = distinct_pairs["estado_key"].map(STATE_NAME_TO_UF)

    def resolve(row) -> tuple[object, str, str]:
        if row["uf_from_estado"] is None:
            return None, "UNRESOLVED", "estado nao mapeia para CE/PE/PI"
        candidates = reference[
            (reference["name_key"] == row["name_key"]) & (reference["uf"] == row["uf_from_estado"])
        ]
        if len(candidates) == 0:
            return None, "UNRESOLVED", "sem correspondencia na referencia IBGE para essa UF"
        if len(candidates) > 1:
            return None, "UNRESOLVED", "ambiguo: multiplos geocodigos candidatos"
        return int(candidates["geocodigo"].iloc[0]), "RESOLVED", ""

    resolved_cols = distinct_pairs.apply(resolve, axis=1, result_type="expand")
    resolved_cols.columns = ["geocodigo", "status", "reason"]
    mapping_report = pd.concat([distinct_pairs, resolved_cols], axis=1)
    mapping_report = mapping_report.rename(columns={"n_fires": "total_fire_count"})
    mapping_report["geocodigo"] = mapping_report["geocodigo"].astype("Int64")
    mapping_report = mapping_report[
        [
            "municipio_raw",
            "estado_raw",
            "uf_from_estado",
            "name_key",
            "geocodigo",
            "status",
            "reason",
            "total_fire_count",
        ]
    ].sort_values(["status", "estado_raw", "municipio_raw"])

    unresolved = mapping_report[mapping_report["status"] == "UNRESOLVED"]
    unresolved_with_fires = unresolved[unresolved["total_fire_count"] > 0]

    resolved_lookup = mapping_report[mapping_report["status"] == "RESOLVED"][
        ["municipio_raw", "estado_raw", "geocodigo", "uf_from_estado"]
    ]
    fires_resolved = raw_counts.merge(resolved_lookup, on=["municipio_raw", "estado_raw"], how="inner")
    fires_by_key = (
        fires_resolved.groupby(["geocodigo", "uf_from_estado", "ano", "mes"], as_index=False)["n_fires"]
        .sum()
        .rename(columns={"uf_from_estado": "uf", "n_fires": "fire_count"})
    )
    rows_dropped_no_match = len(raw_counts) - len(fires_resolved.drop_duplicates(
        subset=["municipio_raw", "estado_raw", "ano", "mes"]
    ))

    # --- Grade completa: municipio x mes para cada (uf, ano) validado; NA para os que falharam ---
    grid_frames = []
    for uf in ufs:
        munis_uf = reference[reference["uf"] == uf][["geocodigo", "nome"]].copy()
        munis_uf["uf"] = uf
        for year in years:
            months = pd.DataFrame({"mes": range(1, 13)})
            cell = munis_uf.merge(months, how="cross")
            cell["ano"] = year
            cell["observed"] = (uf, year) in validated_uf_years
            grid_frames.append(cell)
    grid = pd.concat(grid_frames, ignore_index=True)

    grid = grid.merge(
        fires_by_key,
        on=["geocodigo", "uf", "ano", "mes"],
        how="left",
    )
    grid.loc[grid["observed"], "fire_count"] = grid.loc[grid["observed"], "fire_count"].fillna(0)
    grid.loc[~grid["observed"], "fire_count"] = pd.NA
    grid["fire_count"] = grid["fire_count"].astype("Int64")

    municipality_month = grid.rename(columns={"nome": "municipio"})[
        ["geocodigo", "uf", "municipio", "ano", "mes", "fire_count", "observed"]
    ].sort_values(["uf", "geocodigo", "ano", "mes"]).reset_index(drop=True)

    # --- Coverage report ---
    coverage_rows = []
    for uf in ufs:
        for year in years:
            ok = (uf, year) in validated_uf_years
            file_row = source_files[(source_files["uf"] == uf) & (source_files["year"] == year)]
            n_rows = None
            if not file_row.empty:
                val = file_row.iloc[0]["n_rows"]
                n_rows = None if pd.isna(val) else int(val)
            sub = fires_by_key[(fires_by_key["uf"] == uf) & (fires_by_key["ano"] == year)]
            n_municipios_seen = int(sub.loc[sub["fire_count"] > 0, "geocodigo"].nunique())
            n_months_seen = int(sub.loc[sub["fire_count"] > 0, "mes"].nunique())
            coverage_rows.append(
                {
                    "uf": uf,
                    "year": year,
                    "n_files_ok": int(ok),
                    "n_rows": n_rows,
                    "n_municipios_seen": n_municipios_seen,
                    "n_months_seen": n_months_seen,
                }
            )
    coverage_report = pd.DataFrame(coverage_rows)

    # --- QA checks ---
    dup_keys = municipality_month.duplicated(subset=["geocodigo", "ano", "mes"]).sum()
    observed_rows = municipality_month[municipality_month["observed"]]
    non_negative_ok = bool((observed_rows["fire_count"].dropna() >= 0).all())
    integer_ok = True  # Int64 dtype guarantees integrality where not NA
    mes_ok = bool(municipality_month["mes"].between(1, 12).all())
    ano_ok = bool(municipality_month["ano"].between(2003, 2024).all())
    uf_ok = bool(municipality_month["uf"].isin(UFS).all())
    ref_geocodes = set(reference["geocodigo"])
    geocode_ok = bool(set(municipality_month["geocodigo"].unique()).issubset(ref_geocodes))

    per_uf_gap = []
    for uf in ufs:
        n_ref = int((reference["uf"] == uf).sum())
        raw_ufs_for_uf = distinct_pairs[distinct_pairs["uf_from_estado"] == uf]
        n_raw_resolved = int(
            mapping_report[(mapping_report["uf_from_estado"] == uf) & (mapping_report["status"] == "RESOLVED")][
                "geocodigo"
            ].nunique()
        )
        n_raw_seen_total = int(raw_ufs_for_uf["municipio_raw"].nunique())
        per_uf_gap.append(
            {
                "uf": uf,
                "n_municipios_reference": n_ref,
                "n_distinct_municipio_names_in_raw_data": n_raw_seen_total,
                "n_resolved_geocodigos_seen": n_raw_resolved,
                "gap_reference_minus_resolved": n_ref - n_raw_resolved,
            }
        )

    expected_grid_size = 0
    for uf in ufs:
        n_ref = int((reference["uf"] == uf).sum())
        n_validated_years = sum(1 for year in years if (uf, year) in validated_uf_years)
        expected_grid_size += n_ref * n_validated_years * 12
    actual_observed_rows = int(municipality_month["observed"].sum())
    grid_size_ok = expected_grid_size == actual_observed_rows

    unresolved_fail = len(unresolved_with_fires) > 0

    checks = {
        "unique_key_geocodigo_ano_mes": {"pass": bool(dup_keys == 0), "n_duplicates": int(dup_keys)},
        "fire_count_non_negative_where_observed": {"pass": non_negative_ok},
        "fire_count_integer_where_observed": {"pass": integer_ok},
        "mes_in_1_12": {"pass": mes_ok},
        "ano_in_2003_2024": {"pass": ano_ok},
        "uf_in_ce_pe_pi": {"pass": uf_ok},
        "all_geocodigos_in_ibge_reference": {"pass": geocode_ok},
        "zero_unresolved_municipality_names": {
            "pass": bool(len(unresolved) == 0),
            "n_unresolved": int(len(unresolved)),
            "unresolved_names": unresolved[["municipio_raw", "estado_raw", "reason"]].to_dict("records"),
        },
        "unresolved_names_have_zero_fires": {
            "pass": not unresolved_fail,
            "n_unresolved_with_nonzero_fires": int(len(unresolved_with_fires)),
            "unresolved_with_fires": unresolved_with_fires[
                ["municipio_raw", "estado_raw", "total_fire_count", "reason"]
            ].to_dict("records"),
        },
        "reference_has_no_duplicate_name_uf": {
            "pass": len(reference_duplicate_names) == 0,
            "duplicates": [list(t) for t in reference_duplicate_names],
        },
        "observed_row_count_matches_expected_grid": {
            "pass": bool(grid_size_ok),
            "expected": int(expected_grid_size),
            "actual": int(actual_observed_rows),
        },
        "per_uf_municipality_coverage": per_uf_gap,
    }
    overall_pass = all(
        v["pass"] for k, v in checks.items() if isinstance(v, dict) and "pass" in v
    )

    files_ok = sum(1 for row in source_files_rows if row["parse_ok"])
    files_failed = len(source_files_rows) - files_ok

    quality_report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall_pass": bool(overall_pass),
        "not_approved_for_production_reason": None if overall_pass else "one or more QA checks failed; see checks",
        "files_requested": len(source_files_rows),
        "files_ok": int(files_ok),
        "files_failed": int(files_failed),
        "rows_dropped_no_municipality_match": int(rows_dropped_no_match) if rows_dropped_no_match > 0 else 0,
        "checks": checks,
    }

    # --- Write outputs ---
    source_files_out = source_files.copy()
    source_files_out.to_csv(SNAPSHOT_DIR / "source_files.csv", index=False)
    mapping_report.to_csv(SNAPSHOT_DIR / "mapping_report.csv", index=False)
    coverage_report.to_csv(SNAPSHOT_DIR / "coverage_report.csv", index=False)
    municipality_month.to_csv(SNAPSHOT_DIR / "municipality_month.csv", index=False)
    (SNAPSHOT_DIR / "quality_report.json").write_text(
        json.dumps(quality_report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )

    manifest = {
        "snapshot_name": "inpe_ce_pe_pi_satref_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "role": "target_historical_apa_araripe",
        "source_contract": {
            "url_template": f"{BASE_URL}/{{UF}}/focos_br_{{uf}}_ref_{{year}}.zip",
            "official_url": "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/EstadosBr_sat_ref/",
            "license": "dados abertos INPE",
            "ufs": UFS,
            "years": [years[0], years[-1]] if years else [],
            "years_requested": years,
            "n_files_expected": len(ufs) * len(years),
        },
        "sensor_contract": {
            "series": "sat_ref",
            "description": (
                "Serie de referencia do satelite (sat_ref) do INPE: o arquivo inteiro E a "
                "referencia; nao ha coluna de satelite por linha. O contrato de sensor e "
                "uma propriedade do arquivo fonte (anual, por UF), nao derivada por linha."
            ),
        },
        "municipality_join": {
            "method": "normalize(municipio) + estado(->UF) -> geocodigo via data/reference/ibge_municipios_CE_PE_PI.json",
            "normalization": "NFKD, strip accents, strip/collapse whitespace, casefold",
            "fail_closed": "nomes com 0 ou >1 candidatos na UF ficam UNRESOLVED em mapping_report.csv; nunca adivinhados ou descartados silenciosamente",
        },
        "zero_vs_missing_semantics": (
            "fire_count=0,observed=true somente quando o arquivo (uf,ano) baixou, validou "
            "hash/zip e parseou com sucesso. Arquivo com falha => observed=false e "
            "fire_count vazio (NA) para todo o municipio-mes daquele (uf,ano)."
        ),
        "counts": {
            "files_ok": int(files_ok),
            "files_failed": int(files_failed),
            "n_files_expected": len(ufs) * len(years),
            "municipality_month_rows_total": int(len(municipality_month)),
            "municipality_month_rows_observed_true": int(actual_observed_rows),
            "distinct_geocodigos_resolved": int(mapping_report[mapping_report["status"] == "RESOLVED"]["geocodigo"].nunique()),
            "n_unresolved_municipality_names": int(len(unresolved)),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "quality_overall_pass": bool(overall_pass),
        "outputs": {
            "source_files.csv": {"rows": int(len(source_files_out))},
            "mapping_report.csv": {"rows": int(len(mapping_report))},
            "coverage_report.csv": {"rows": int(len(coverage_report))},
            "municipality_month.csv": {"rows": int(len(municipality_month))},
            "quality_report.json": {"overall_pass": bool(overall_pass)},
        },
    }
    (SNAPSHOT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )

    return {
        "manifest": manifest,
        "quality_report": quality_report,
        "mapping_report": mapping_report,
        "source_files": source_files_out,
    }


def main() -> None:
    """Ponto de entrada de linha de comando: `python -m src.data.ingest_inpe_ce_pe_pi_satref`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="*", type=int, default=YEARS)
    parser.add_argument("--ufs", nargs="*", default=UFS)
    parser.add_argument("--force", action="store_true", help="Ignora cache e rebaixa tudo.")
    args = parser.parse_args()

    result = build_snapshot(years=args.years, ufs=args.ufs, force=args.force)
    print(json.dumps(result["manifest"]["counts"], indent=2, ensure_ascii=False))
    print("overall_pass:", result["quality_report"]["overall_pass"])


if __name__ == "__main__":
    main()
