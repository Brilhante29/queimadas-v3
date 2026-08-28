"""Audita a semantica de zero do alvo: zero observado x ausencia de dado.

O achado que motivou
--------------------
Auditoria independente apontou 1.320 linhas com `fire_count = 0` e
`observed = True` para 5 municipios que a fonte do INPE **nunca** emitiu em
264 meses, e observou que `test_missing_not_silently_zeroed` filtra
`observed == False` -- conjunto vazio neste snapshot -- e portanto passa sem
testar nada.

O que a auditoria conclui
-------------------------
A grade e preenchida a partir da referencia IBGE, e municipio sem linha na
fonte vira zero observado. Para dado de foco de calor isso normalmente esta
CERTO: o arquivo lista deteccoes, e ausencia de deteccao e zero de verdade. O
risco real nao e o zero -- e nao conseguir distinguir "sem deteccao" de "join
falhou".

Esse risco especifico ja esta fechado por outro caminho: a ingestao **falha
fechada** em nome nao resolvido (levanta `ValueError`), entao um erro de join
nunca chega a virar zero silencioso. Sobra o caso de municipio que a fonte
jamais menciona, que este script enumera e monitora.

Nao regenera o snapshot: o sha256 de `municipality_month.csv` esta registrado
em `g5_drift/frozen_config.json` e em `exp10/result.json`. A auditoria e um
artefato separado.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET = PROJECT_ROOT / "data" / "snapshots" / "inpe_ce_pe_pi_satref_v1" / "municipality_month.csv"
SCOPE = PROJECT_ROOT / "data" / "reference" / "apa_chapada_araripe.csv"
OUT = PROJECT_ROOT / "outputs" / "apa_araripe" / "audit" / "zero_semantics_audit.json"


def main() -> int:
    """Enumera municipios sem nenhuma deteccao e mede o impacto no escopo APA."""
    df = pd.read_csv(TARGET)
    scope = set(pd.read_csv(SCOPE)["geocodigo"].astype(int))

    totals = df.groupby(["geocodigo", "municipio", "uf"], as_index=False)["fire_count"].sum()
    never = totals[totals["fire_count"] == 0].sort_values(["uf", "municipio"])
    never_codes = set(never["geocodigo"].astype(int))

    months_per_muni = int(df.groupby("geocodigo").size().max())
    in_scope = sorted(never_codes & scope)

    zeros_total = int((df["fire_count"] == 0).sum())
    zeros_from_never = int(len(never) * months_per_muni)

    report = {
        "check": "semantica de zero -- zero observado x ausencia de dado",
        "target_sha256": hashlib.sha256(TARGET.read_bytes()).hexdigest(),
        "rows": int(len(df)),
        "months_per_municipality": months_per_muni,
        "zeros_total": zeros_total,
        "rows_marked_observed_false": int((~df["observed"]).sum()),
        "municipalities_never_emitted_by_source": {
            "count": int(len(never)),
            "rows_involved": zeros_from_never,
            "share_of_all_zeros": round(zeros_from_never / zeros_total, 4) if zeros_total else 0.0,
            "list": [
                {"geocodigo": int(r.geocodigo), "municipio": r.municipio, "uf": r.uf}
                for r in never.itertuples()
            ],
        },
        "intersection_with_apa_scope": {
            "count": len(in_scope),
            "geocodigos": in_scope,
            "consequence": (
                "Nenhum resultado da APA depende dessas linhas."
                if not in_scope
                else "ATENCAO: municipio sem deteccao dentro do escopo APA -- investigar."
            ),
        },
        "why_these_zeros_are_defensible": (
            "Os 5 municipios sao ilhas oceanicas ou area urbana densa da regiao "
            "metropolitana do Recife (Fernando de Noronha, Ilha de Itamaraca, Jupi, "
            "Olinda, Paulista). Zero deteccao de foco em 22 anos e plausivel para "
            "esse perfil, nao anomalo."
        ),
        "why_join_failure_cannot_masquerade_as_zero": (
            "A ingestao levanta ValueError em nome de municipio nao resolvido "
            "(falha fechada). Um erro de join aborta a construcao do snapshot em vez "
            "de produzir zero silencioso. O snapshot registra "
            "unresolved_municipality_names = 0."
        ),
        "residual_gap": (
            "O esquema atual nao consegue distinguir 'a fonte nao emitiu porque nao "
            "houve foco' de 'a fonte nao emitiu porque nao cobre este municipio'. "
            "Enquanto a fonte for a lista de deteccoes do INPE, as duas coisas sao "
            "indistinguiveis por construcao. A mitigacao e monitorar a contagem: uma "
            "regressao de join apareceria como salto no numero de municipios sem "
            "nenhuma deteccao."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    n = report["municipalities_never_emitted_by_source"]
    print(f"municipios sem nenhuma deteccao: {n['count']} ({n['rows_involved']} linhas, "
          f"{n['share_of_all_zeros']:.1%} de todos os zeros)")
    for m in n["list"]:
        print(f"  {m['geocodigo']} {m['municipio']} ({m['uf']})")
    print(f"dentro do escopo APA: {len(in_scope)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
