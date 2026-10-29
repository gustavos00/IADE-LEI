# resumos-pdf

Converte em PDF os resumos em Markdown que estão nas pastas `Resumidos` de cada módulo (`Faculdade/<disciplina>/<módulo>/Resumidos/*.md`). Cada PDF fica ao lado do Markdown que lhe deu origem.

Os resumos são escritos em Markdown simples, sem LaTeX: a matemática vai em Unicode (×, ², √, ‖v‖, a₁₂), e as matrizes, os mapas de Karnaugh e os cálculos longos vão em blocos de código. Por isso, a conversão só precisa de HTML e do Chrome em modo headless. Não é preciso instalar LaTeX nem outro motor de PDF.

## Instalar

Precisas de Python 3.10 ou mais recente e do Google Chrome. Corre dentro desta pasta:

```bash
python3 -m venv .venv
```
```bash
.venv/bin/pip install -r requirements.txt
```

## Usar

```bash
.venv/bin/python convert_summaries.py
```

Só converte os resumos que mudaram desde o último PDF.

| Opção | O que faz |
|---|---|
| `--pasta PASTA` | Pasta com uma subpasta por disciplina. Por omissão é `~/Faculdade` |
| `--todos` | Converte todos os resumos, mesmo os que não mudaram |

Se o Chrome não estiver em `/Applications`, indica o caminho com a variável `CHROME`. O Chrome corre com um perfil temporário, por isso não mexe no teu perfil nem abre nenhuma janela.
