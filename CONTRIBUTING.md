# Contribuindo com o FireCast

Obrigado pelo interesse. O FireCast é um projeto de ML de produção para prever
focos mensais de queimadas por município (Chapada do Araripe / CE-PE-PI). As
regras abaixo existem para manter a qualidade científica e evitar leakage.

## Princípios inegociáveis

- **Dados reais e validação temporal** para qualquer afirmação de qualidade.
- **Nunca usar o mês alvo** em features históricas (anti-leakage).
- **Registrar experimentos negativos** — resultado ruim também é evidência.
- **Nunca reduzir gates (G0–G7)** para obter aprovação.
- **Segredos ficam no ambiente** (ex.: `FIRMS_MAP_KEY`), nunca no repositório.

## Ambiente local

```bash
python -m venv .venv
# Linux/macOS:  source .venv/bin/activate
# Windows:      .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # preencha as chaves necessárias
```

As bases completas (~1.2 GB) não ficam no git — baixe pelo
[GitHub Release](../../releases) mais recente. O repositório já traz o
subconjunto mínimo (`data/snapshots/inpe_local_v2/`, `data/reference/`) que faz
a suíte de testes passar sem download.

## Antes de abrir um Pull Request

1. **Lint** (bloqueante só em erro real de sintaxe/nome):
   ```bash
   flake8 src tests scripts streamlit_app --select=E9,F63,F7,F82
   ```
2. **Testes** (devem passar 100%):
   ```bash
   PYTHONPATH=. pytest tests -q
   ```
3. Descreva **o que mudou e por quê**. Mudança de modelo exige métrica
   walk-forward e comparação com o baseline no protocolo congelado.

## Estilo

- Python 3.10+.
- Mensagens de commit no formato [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `test:`, `chore:`…).
- Um PR por assunto. PRs pequenos são revisados mais rápido.

## Segurança

Encontrou uma vulnerabilidade? Veja [SECURITY.md](SECURITY.md) — não abra issue
pública para isso.
