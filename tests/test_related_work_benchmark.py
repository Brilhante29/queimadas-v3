"""Testes publicos do FireCast para tests/test_related_work_benchmark.py.

Validam contratos, metricas, grafo XAI, dados e comportamento fail-closed para que a entrega possa ser conferida por terceiros."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_related_work_benchmark_has_defensible_claim_boundaries():
    """Verifica o comportamento `test related work benchmark has defensible claim boundaries`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    benchmark_path = ROOT / "outputs" / "research_frontier_benchmark.json"
    doc_path = ROOT / "docs" / "RELATED_WORK_COMPETITIVE_POSITION.md"

    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))

    assert benchmark["schema_version"] == "firecast_related_work_benchmark_v1"
    assert len(benchmark["papers"]) >= 8
    assert "LLM improves prediction" in benchmark["non_claims"]
    assert "daily point localization superiority" in benchmark["non_claims"]
    assert "mechanically verified LLM-XAI" in benchmark["defensible_firecast_wins"]

    for paper in benchmark["papers"]:
        assert paper["url"].startswith("https://")
        assert paper["task"]
        assert paper["headline_metric"]
        assert paper["firecast_position"]

    doc = doc_path.read_text(encoding="utf-8")
    assert "Claims to avoid" in doc
    assert "Do not compare FireCast WAPE directly to AUROC/AP/IoU" in doc
