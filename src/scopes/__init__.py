"""Escopos municipais versionados do FireCast.

Este pacote guarda definicoes de escopo geografico como artefatos reproduziveis
(CSV versionado + codigo de derivacao), nunca como listas soltas hardcoded em
notebooks ou scripts de treino.

Escopos disponiveis:

- ``apa_araripe``: escopo oficial da APA Chapada do Araripe, derivado por
  intersecao espacial versionada entre o poligono ICMBio da UC e a malha
  municipal IBGE (CE/PE/PI). N nao e fixado a priori; e o resultado da
  intersecao. Ver ``apa_araripe.py`` e
  ``outputs/apa_araripe/audit/scope_derivation_report.md``.
- ``cariri_legacy``: escopo legado "Chapada"/Cariri (29 municipios, apenas
  CE), usado pelos experimentos G4 anteriores a este SDD. Preservado apenas
  para reproducibilidade historica -- NAO deve ser usado para novas metricas
  da APA.
"""

from __future__ import annotations

from .apa_araripe import apa_geocodes, load_apa_scope
from .cariri_legacy import cariri_ce_legacy_geocodes, load_cariri_ce_legacy

__all__ = [
    "load_apa_scope",
    "apa_geocodes",
    "load_cariri_ce_legacy",
    "cariri_ce_legacy_geocodes",
]
