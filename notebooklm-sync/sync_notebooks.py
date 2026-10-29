#!/usr/bin/env python3
"""Envia os PDFs descarregados pelo canvas-pdfs para o Gemini Notebook (NotebookLM).

Cria um caderno por disciplina ("IADE LEI · Álgebra Linear", ...) e junta-lhe como fontes
os PDFs de ~/Faculdade/<disciplina>/ que ainda lá não estão. Pode correr-se sempre que
o canvas-pdfs descarregar ficheiros novos: só envia o que falta.

Usa a biblioteca não oficial notebooklm-py; vê o README para o login.

Uso:
  python sync_notebooks.py [--pasta ~/Faculdade] [--listar]
"""

import argparse
import asyncio
import sys
from pathlib import Path

from notebooklm import AuthError, NotebookLMClient

NOTEBOOK_PREFIX = "IADE LEI · "
TITLE_SEPARATOR = " › "


def build_source_title(subject_dir, pdf_path):
    """'01 - Vetores e Matrizes/Recursos da Aula Virtual/1 - Intro.pdf' -> '01 - Vetores e Matrizes › Recursos da Aula Virtual › 1 - Intro'"""
    parts = pdf_path.relative_to(subject_dir).with_suffix("").parts

    return TITLE_SEPARATOR.join(parts)


def list_subject_pdfs(subject_dir):
    pdfs = sorted(path for path in subject_dir.rglob("*.pdf") if path.is_file())

    return [(build_source_title(subject_dir, path), path) for path in pdfs]


def list_subject_dirs(root):
    return sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith("."))


async def get_or_create_notebook(client, title, notebooks, list_only):
    for notebook in notebooks:
        if notebook.title == title:
            return notebook

    if list_only:
        return None

    return await client.notebooks.create(title)


async def sync_subject(client, subject_dir, notebooks, list_only):
    notebook_title = NOTEBOOK_PREFIX + subject_dir.name
    pdfs = list_subject_pdfs(subject_dir)
    print(f"\n== {notebook_title}  ({len(pdfs)} PDFs)")

    notebook = await get_or_create_notebook(client, notebook_title, notebooks, list_only)

    if notebook is None:
        print("   caderno novo (ainda não existe)")
        existing_titles = set()
    else:
        existing_titles = {source.title for source in await client.sources.list(notebook.id)}

    # Uma fonte acabada de enviar fica com o nome do ficheiro; o título com o módulo é dado depois.
    missing = [
        (title, path) for title, path in pdfs if title not in existing_titles and path.name not in existing_titles
    ]
    sent = failed = 0

    for title, path in missing:
        if list_only:
            print(f"   enviaria: {title}")
            continue

        try:
            await client.sources.add_file(notebook.id, path)
            print(f"   ok: {title}")
            sent += 1
        # Um ficheiro que falha (formato, limite de fontes, rede) não pára os outros.
        except Exception as error:
            print(f"   erro: {title} ({type(error).__name__}: {error})")
            failed += 1

    if notebook is not None:
        failed += await rename_to_module_titles(client, notebook, pdfs, list_only)

    print(f"   já lá estavam: {len(pdfs) - len(missing)}")

    return sent, failed


async def rename_to_module_titles(client, notebook, pdfs, list_only):
    """Dá o título com o módulo às fontes que ainda têm o nome do ficheiro.

    O título pedido no próprio envio só pega se o NotebookLM já tiver registado a fonte, e na
    prática fica quase sempre o nome do ficheiro; por isso o título é dado numa segunda volta.
    """
    by_file_name = {path.name: title for title, path in pdfs}
    failed = 0

    for source in await client.sources.list(notebook.id):
        title = by_file_name.get(source.title)

        if title is None:
            continue

        if list_only:
            print(f"   corrigiria o título: {title}")
            continue

        try:
            await client.sources.rename(notebook.id, source.id, title)
        except Exception as error:
            print(f"   erro ao dar título: {title} ({type(error).__name__}: {error})")
            failed += 1

    return failed


async def sync_all(root, list_only):
    async with NotebookLMClient.from_storage() as client:
        notebooks = await client.notebooks.list()
        total_sent = total_failed = 0

        for subject_dir in list_subject_dirs(root):
            sent, failed = await sync_subject(client, subject_dir, notebooks, list_only)
            total_sent += sent
            total_failed += failed

    if not list_only:
        print(f"\nEnviados: {total_sent} · falharam: {total_failed}")

    return total_failed


def parse_arguments():
    parser = argparse.ArgumentParser(description="Envia os PDFs das disciplinas para o Gemini Notebook.")
    parser.add_argument("--pasta", default="~/Faculdade", help="pasta com uma subpasta por disciplina")
    parser.add_argument("--listar", action="store_true", help="só mostra o que enviaria")

    return parser.parse_args()


def main():
    arguments = parse_arguments()
    root = Path(arguments.pasta).expanduser()

    if not root.is_dir():
        sys.exit(f"A pasta {root} não existe. Corre primeiro o canvas-pdfs.")

    try:
        failed = asyncio.run(sync_all(root, arguments.listar))
    # Sem login a biblioteca não encontra o storage_state.json; com a sessão expirada dá AuthError.
    except (AuthError, FileNotFoundError):
        sys.exit("Sessão do Google em falta ou expirada. Corre: notebooklm login")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
