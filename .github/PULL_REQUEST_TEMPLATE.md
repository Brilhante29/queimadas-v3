## O que muda

<!-- Descreva a mudança em 1-3 frases. -->

## Por quê

<!-- Motivação / problema resolvido. -->

## Tipo

- [ ] feat (nova capacidade)
- [ ] fix (correção)
- [ ] docs
- [ ] test
- [ ] chore / infra

## Checklist

- [ ] `flake8 src tests scripts streamlit_app --select=E9,F63,F7,F82` passa
- [ ] `PYTHONPATH=. pytest tests -q` passa 100%
- [ ] Sem segredos, chaves ou dados grandes no diff
- [ ] Se mudou o modelo: incluí métrica walk-forward + comparação com baseline no protocolo congelado
- [ ] Não reduzi nenhum gate (G0–G7) para aprovar
