# notebooklm-sync

Envia para o **Gemini Notebook** (antigo NotebookLM) os PDFs que o [`canvas-pdfs`](../canvas-pdfs/) descarregou. Cria um caderno por disciplina, onde podes fazer perguntas sobre a matéria, gerar resumos, guias de estudo, flashcards ou podcasts. Os cadernos também aparecem na app Gemini.

```
~/Faculdade/Álgebra Linear/01 - Vetores e Matrizes/Recursos da Aula Virtual/1 - Introdução aos vetores.pdf
        ↓
Caderno "IADE LEI · Álgebra Linear"
  fonte "01 - Vetores e Matrizes › Recursos da Aula Virtual › 1 - Introdução aos vetores"
```

O Gemini Notebook não tem pastas dentro de um caderno. Por isso, o caminho do módulo vai no título de cada fonte, e as fontes ficam pela ordem dos módulos.

Pode correr-se sempre que o `canvas-pdfs` trouxer ficheiros novos: só envia as fontes que ainda não estão no caderno, comparando pelo título.

O título é dado numa segunda volta, depois do envio. Se o título pedido for dado logo no envio, o NotebookLM quase sempre fica com o nome do ficheiro. Por isso, depois de enviar, o script procura as fontes que ainda têm o nome do ficheiro e muda-lhes o título.

## ⚠️ Biblioteca não oficial

Usa a [notebooklm-py](https://github.com/teng-lin/notebooklm-py), que fala com APIs internas da Google. A Google não tem uma API pública do NotebookLM para contas pessoais. Por isso:

- pode deixar de funcionar sem aviso, se a Google mudar alguma coisa. A versão está fixa em `requirements.txt`; se algo partir, experimenta atualizá-la;
- a sessão do Google fica guardada em `~/.notebooklm/`. Trata essa pasta como uma password: nunca a partilhes nem a ponhas num repositório;
- o número de fontes por caderno depende do teu plano Google. Se um envio falhar por limite, o erro aparece só nesse ficheiro e os outros continuam.

## Instalar

Precisas de Python 3.10 ou mais recente. Corre dentro desta pasta:

```bash
python3 -m venv .venv
```
```bash
.venv/bin/pip install -r requirements.txt
```

## Entrar na conta Google (uma vez)

```bash
.venv/bin/notebooklm login --browser chrome
```

Abre uma janela do Chrome onde fazes o login no Google. A sessão é guardada sozinha quando o login acaba. Com `--browser chrome` usa o Chrome que já tens instalado, porque o Chromium da biblioteca pode falhar no macOS 15 ou mais recente. Se a sessão expirar, o script avisa e voltas a correr este comando.

## Usar

```bash
.venv/bin/python sync_notebooks.py --listar
```
```bash
.venv/bin/python sync_notebooks.py
```

| Opção | O que faz |
|---|---|
| `--listar` | Mostra que cadernos criaria e que PDFs enviaria, sem mudar nada |
| `--pasta PASTA` | Pasta com uma subpasta por disciplina. Por omissão é `~/Faculdade` |

O prefixo dos cadernos (`IADE LEI · `) e o separador dos títulos (` › `) estão no início de [`sync_notebooks.py`](sync_notebooks.py).

## Fluxo completo

```bash
cd ../canvas-pdfs && docker run --rm --env-file canvas.env -v ~/Faculdade:/dados canvas-pdfs
```
```bash
cd ../notebooklm-sync && .venv/bin/python sync_notebooks.py
```

## Podcasts por módulo

O `generate_podcasts.py` gera, no caderno de cada disciplina, um áudio por módulo, feito só com as fontes desse módulo, incluindo os Recursos da Aula Virtual. Depois descarrega-o para `~/Faculdade/<disciplina>/<módulo>/Podcast · <módulo>.m4a`.

- **Estilo:** um só apresentador, em português de Portugal, a explicar com calma o como e o porquê de cada conceito. A primeira frase já é matéria, e os exemplos vêm só da matéria, sem analogias com jogos ou com o dia a dia. As instruções estão em `build_instructions()`.
- **Áudio:** depois de descarregar, o script abranda o áudio para 0,85x (`PLAYBACK_SPEED`), sem mudar o tom da voz, e normaliza o volume para -16 LUFS, o volume habitual de podcast. Para isso usa o ffmpeg incluído no pacote `imageio-ffmpeg`, por isso não é preciso instalar nada.
- **Ordem:** os módulos são intercalados entre as disciplinas: o módulo 01 de cada uma, depois o módulo 02 de cada uma, e assim por diante. Por omissão, trata Álgebra Linear, Análise Matemática, Física e Sistemas Digitais. Os Fundamentos da Programação são um lote à parte.
- **Quota:** cada podcast gasta uma boa parte da quota de 5 horas do Gemini Notebook. O script gera enquanto houver quota, para quando ela acaba e, na vez seguinte, continua onde ficou. Os pedidos já feitos ficam em `.podcasts-pendentes.json`, para nenhum ser pago duas vezes.

```bash
.venv/bin/python generate_podcasts.py --listar
```
```bash
.venv/bin/python generate_podcasts.py --max 1
```
```bash
.venv/bin/python generate_podcasts.py --disciplina "Fundamentos da Programação"
```

| Opção | O que faz |
|---|---|
| `--listar` | Mostra a ordem e o que falta gerar, sem gerar nada |
| `--max N` | Trata no máximo N podcasts nesta volta |
| `--disciplina NOME` | Trata só esta disciplina. Pode repetir-se, e a ordem dada é a ordem usada |
| `--refazer TEXTO` | Volta a gerar os módulos cujo nome contém o texto. A versão anterior fica como "(versão anterior)" |
| `--pasta PASTA` | Onde guardar os áudios. Por omissão é `~/Faculdade` |

**Limitação conhecida:** no formato de um só apresentador, o NotebookLM gera sempre um áudio curto, de 1 a 2 minutos, e ignora o pedido de duração longa.
