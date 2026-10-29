# IADE - LEI

Ferramentas para a Licenciatura em Engenharia Informática do IADE. São pequenos scripts que tratam das tarefas repetitivas do curso, para sobrar mais tempo para estudar.

Cada ferramenta tem a sua pasta e o seu próprio README, com instruções de instalação e de uso.

## Pastas

| Pasta | Para que serve |
|---|---|
| [`canvas-pdfs/`](canvas-pdfs/) | Descarrega do Canvas ([mycampus.pt](https://www.mycampus.pt)) os PDFs das disciplinas do semestre e organiza-os em `Faculdade/<disciplina>/<módulo>/`, com nomes de pastas e de ficheiros normalizados. Corre em Docker ou como executável C++. |
| [`notebooklm-sync/`](notebooklm-sync/) | Envia esses PDFs para o Gemini Notebook (antigo NotebookLM), com um caderno por disciplina. Cada fonte tem como título o módulo de onde vem, e o script só envia o que ainda lá não está. Usa uma biblioteca não oficial. |
