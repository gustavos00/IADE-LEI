# canvas-pdfs

Descarrega do Canvas do IADE ([mycampus.pt](https://www.mycampus.pt)) os PDFs das disciplinas do semestre e arruma-os por disciplina e por módulo.

```
Faculdade/
  Álgebra Linear/
    01 - Vetores e Matrizes/
      Originais/
        LEI.34.01.01.IADE.PT.pdf
      Recursos da Aula Virtual/
        1 - Introdução aos vetores.pdf
      Resumidos/              (resumos de cada PDF; não vêm do Canvas)
    02 - Sistemas de Equações Lineares/
    …
  Análise Matemática/
  Física/
  Fundamentos da Programação/
  Sistemas Digitais/
```

Pode correr-se tantas vezes quantas quiseres: só descarrega o que ainda não tens. Isto dá jeito para ir buscar os materiais que os professores forem publicando ao longo do semestre.

## Como funciona

- Usa a **API oficial do Canvas**, a mesma que a aplicação móvel usa, com um token pessoal. Não precisa da tua password e não lê as páginas web.
- Só descarrega as disciplinas definidas em `SUBJECTS`, no início de [`canvas_pdfs.cpp`](canvas_pdfs.cpp). Para encontrar cada disciplina, compara o nome do Canvas sem acentos e sem distinguir maiúsculas de minúsculas. As outras áreas do Canvas ficam de fora, como a Biblioteca, as Comunidades ou o Respondus.
- Organiza os ficheiros pelos **módulos** de cada disciplina:
  - `1. VETORES E MATRIZES` passa a `01 - Vetores e Matrizes`, com os PDFs do módulo em `Originais/`;
  - `N. Recursos da Aula Virtual` vai para dentro do módulo `N`;
  - os PDFs que não estão em nenhum módulo vão para `Outros ficheiros`.
- Limpa os nomes dos ficheiros: `1_Introdução (1).pdf.pdf` passa a `1 - Introdução.pdf`. Os códigos `LEI.xx.xx.xx.IADE.PT.pdf` ficam como estão.
- Se o docente esconder a área Ficheiros, vai buscar os PDFs aos módulos.
- Escreve cada ficheiro primeiro como `.part` e só lhe dá o nome final quando o download acaba. Assim, um download interrompido nunca deixa um PDF estragado.

## Antes de começar: o token

1. Entra em [mycampus.pt](https://www.mycampus.pt) e vai a **Conta → Definições → "+ Novo token de acesso"**.
2. Copia o modelo de configuração e põe lá o token, na mesma linha do `=`:
   ```bash
   cp canvas.env.example canvas.env
   ```
   ```
   CANVAS_TOKEN=o-teu-token
   ```

O `canvas.env` está no `.gitignore` e nunca deve ser partilhado, porque o token dá acesso à tua conta. Se o token alguma vez ficar exposto, apaga-o em **Conta → Definições → Tokens de acesso aprovados** e cria um novo.

## Correr com Docker (recomendado)

Corre estes comandos dentro desta pasta. Os PDFs vão para a pasta do teu computador que montares em `/dados`, neste exemplo `~/Faculdade`.

```bash
docker build -t canvas-pdfs .
```
```bash
docker run --rm --env-file canvas.env -v ~/Faculdade:/dados canvas-pdfs
```

Só precisas de voltar a correr o `docker build` quando o código mudar. Corre o `docker run` uma vez de cada vez: dois downloads ao mesmo tempo para a mesma pasta interferem um com o outro.

## Correr sem Docker

Precisas de um compilador de C++17 e da libcurl. O macOS já traz os dois com as Command Line Tools.

```bash
clang++ -std=c++17 -O2 canvas_pdfs.cpp -lcurl -o canvas_pdfs
```
```bash
export CANVAS_TOKEN=o-teu-token
```
```bash
./canvas_pdfs --saida ~/Faculdade
```

No Linux, usa `g++` em vez de `clang++` e instala antes o pacote `libcurl4-openssl-dev`.

## Opções

Acrescentam-se no fim do comando, tanto no `docker run` como no `./canvas_pdfs`.

| Opção | O que faz |
|---|---|
| `--listar` | Mostra o que seria descarregado, sem descarregar nada |
| `--todas` | Inclui também as disciplinas de semestres anteriores |
| `--saida PASTA` | Pasta de destino. Por omissão é `./Faculdade`; no Docker é `/dados` |

| Variável | O que faz |
|---|---|
| `CANVAS_TOKEN` | O teu token pessoal. É obrigatória |
| `CANVAS_URL` | Outro endereço do Canvas. Por omissão é `https://www.mycampus.pt` |

## Mudar as disciplinas

Para mudar as disciplinas, edita a lista `SUBJECTS` em [`canvas_pdfs.cpp`](canvas_pdfs.cpp). Cada entrada tem dois campos:

- o nome da pasta, como queres vê-la;
- o texto a procurar no nome da disciplina no Canvas, em minúsculas e sem acentos.

```cpp
const Subject SUBJECTS[] = {
    {"Álgebra Linear", "algebra"},
    {"Sistemas Digitais", "sistemas digitais"},
    // ...
};
```

Depois, volta a correr o `docker build`.

## Ficheiros

| Ficheiro | Conteúdo |
|---|---|
| `canvas_pdfs.cpp` | Todo o programa num só ficheiro: cliente HTTP (libcurl), leitor de JSON, regras de nomes e download |
| `Dockerfile` | Compila numa imagem Debian e copia só o executável para uma imagem pequena |
| `canvas.env.example` | Modelo do `canvas.env` |
| `.gitignore` / `.dockerignore` | Deixam de fora o token, o executável e os PDFs |
