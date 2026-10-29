#!/usr/bin/env python3
"""Converte os resumos em Markdown (Faculdade/**/Resumidos/*.md) em PDF, ao lado de cada um.

Usa o Chrome em modo headless para imprimir o HTML, por isso não precisa de LaTeX nem de
outro motor de PDF. Só converte os resumos que mudaram desde o último PDF.

Uso:
  python convert_summaries.py [--pasta ~/Faculdade] [--todos]
"""

import argparse
import html
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
SUMMARIES_FOLDER = "Resumidos"
PAGE_STYLE = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; font-size: 11pt;
       line-height: 1.5; color: #1a1a1a; }
h1 { font-size: 18pt; margin: 0 0 4pt; }
h1 + p em { color: #666; font-size: 9pt; }
h2 { font-size: 14pt; margin-top: 18pt; border-bottom: 1px solid #ddd; padding-bottom: 2pt; }
h3 { font-size: 12pt; margin-top: 12pt; }
pre { background: #f5f5f5; padding: 8pt; border-radius: 4pt; font-size: 9.5pt;
      white-space: pre-wrap; page-break-inside: avoid; }
code { font-family: Menlo, Consolas, monospace; }
table { border-collapse: collapse; margin: 8pt 0; page-break-inside: avoid; }
th, td { border: 1px solid #ccc; padding: 3pt 8pt; text-align: center; }
"""


def build_html(markdown_text, title):
    body = markdown.markdown(markdown_text, extensions=["tables", "fenced_code", "sane_lists"])

    return (
        f'<!doctype html><html lang="pt-PT"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title><style>{PAGE_STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )


def print_to_pdf(html_text, destination, profile_dir):
    with tempfile.NamedTemporaryFile("w", suffix=".html", encoding="utf-8", delete=False) as page:
        page.write(html_text)

    command = [
        CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
        f"--user-data-dir={profile_dir}", f"--print-to-pdf={destination}", Path(page.name).as_uri(),
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, timeout=120)
    finally:
        os.unlink(page.name)


def list_summaries(root):
    return sorted(path for path in root.rglob("*.md") if path.parent.name == SUMMARIES_FOLDER)


def is_outdated(summary, pdf):
    return not pdf.exists() or pdf.stat().st_mtime < summary.stat().st_mtime


def parse_arguments():
    parser = argparse.ArgumentParser(description="Converte os resumos em Markdown para PDF.")
    parser.add_argument("--pasta", default="~/Faculdade", help="pasta com uma subpasta por disciplina")
    parser.add_argument("--todos", action="store_true", help="converte todos, mesmo os que não mudaram")

    return parser.parse_args()


def main():
    arguments = parse_arguments()
    root = Path(arguments.pasta).expanduser()

    if not Path(CHROME).exists():
        sys.exit(f"Não encontrei o Chrome em {CHROME}. Indica outro com a variável CHROME.")

    converted = failed = 0

    # Um perfil temporário, para o Chrome headless nunca tocar no perfil do utilizador.
    with tempfile.TemporaryDirectory() as profile_dir:
        for summary in list_summaries(root):
            pdf = summary.with_suffix(".pdf")

            if not arguments.todos and not is_outdated(summary, pdf):
                continue

            try:
                print_to_pdf(build_html(summary.read_text(encoding="utf-8"), summary.stem), pdf, profile_dir)
                converted += 1
            except (subprocess.SubprocessError, OSError) as error:
                print(f"erro: {summary.relative_to(root)} ({error})")
                failed += 1

    print(f"Convertidos: {converted} · falharam: {failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
