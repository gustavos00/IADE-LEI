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
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
SUMMARIES_FOLDER = "Resumidos"
# Fontes do Google Fonts: o Noto cobre os índices e expoentes Unicode (aᵢⱼ, xⁿ) que a Helvetica não
# tem, e o STIX Two é uma letra feita para matemática.
FONTS_URL = (
    "https://fonts.googleapis.com/css2?family=Noto+Sans:ital,wght@0,400;0,600;0,700;1,400"
    "&family=STIX+Two+Text:ital,wght@0,400;0,600;1,400&family=Noto+Sans+Math"
    "&family=JetBrains+Mono&display=block"
)
PAGE_STYLE = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: "Noto Sans", "Noto Sans Math", sans-serif; font-size: 10.5pt;
       line-height: 1.55; color: #1a1a1a; }
h1 { font-size: 18pt; margin: 0 0 6pt; }
h2 { font-size: 14pt; margin-top: 18pt; border-bottom: 1px solid #ddd; padding-bottom: 2pt; }
h3 { font-size: 12.5pt; margin-top: 14pt; }
h4 { font-size: 11.5pt; margin-top: 10pt; margin-left: 8pt; }
h5 { font-size: 11pt; margin-top: 8pt; margin-left: 16pt; font-style: italic; }
sub, sup { font-size: 0.72em; line-height: 0; }
pre { background: #f5f5f5; padding: 8pt; border-radius: 4pt; font-size: 9pt;
      white-space: pre-wrap; page-break-inside: avoid; }
code { font-family: "JetBrains Mono", Menlo, monospace; }
table { border-collapse: collapse; margin: 8pt 0; page-break-inside: avoid; }
th, td { border: 1px solid #ccc; padding: 3pt 8pt; text-align: center; }
.math { font-family: "STIX Two Text", "Noto Sans Math", serif; font-size: 12pt; line-height: 1.7;
        white-space: pre-wrap; margin: 8pt 0 8pt 6pt; padding: 2pt 0 2pt 12pt;
        border-left: 3px solid #d7dce5; page-break-inside: avoid; }
.math.aligned { font-family: "JetBrains Mono", Menlo, monospace; font-size: 9.5pt; line-height: 1.6;
                white-space: pre; }
table.math-table { font-family: "STIX Two Text", "Noto Sans Math", serif; font-size: 12pt; }
table.math-table td { padding: 4pt 10pt; }
table.math-table tr.header td, table.math-table td.label { font-weight: 600; background: #f4f6f9; }
table.math-table td.label { white-space: nowrap; }
.matrix-line { display: flex; align-items: center; gap: 8pt; margin: 10pt 0 10pt 6pt;
               font-family: "STIX Two Text", "Noto Sans Math", serif; font-size: 12pt;
               page-break-inside: avoid; }
table.matrix { margin: 0; border-left: 1.5px solid #1a1a1a; border-right: 1.5px solid #1a1a1a;
               border-radius: 3pt; }
table.matrix td { border: none; padding: 2pt 9pt; }
"""
# Blocos sem linguagem são matemática; os blocos com linguagem (```cpp) continuam a ser código.
FENCED_BLOCK = re.compile(r"^```([\w+#-]*)[ \t]*\n(.*?)\n```[ \t]*$", re.MULTILINE | re.DOTALL)
COLUMN_GAP = re.compile(r"\s{2,}")
INLINE_SCRIPTS = [
    (re.compile(r"_\{([^}]+)\}"), r"<sub>\1</sub>"),
    (re.compile(r"(?<=[A-Za-zα-ωΑ-Ω)\]′])_([A-Za-z0-9]{1,3})(?![A-Za-z0-9_])"), r"<sub>\1</sub>"),
    (re.compile(r"\^\{([^}]+)\}"), r"<sup>\1</sup>"),
    (re.compile(r"\^\(([^()]{1,12})\)"), r"<sup>\1</sup>"),
    (re.compile(r"\^([−-]?[A-Za-z0-9]{1,3})(?![A-Za-z0-9])"), r"<sup>\1</sup>"),
]


def format_inline_math(text):
    """a_ij, a_{ij}, x^2 e x^(n+1) passam a índices e expoentes; o código entre ` ` fica igual."""
    parts = text.split("`")

    for index in range(0, len(parts), 2):
        for pattern, replacement in INLINE_SCRIPTS:
            parts[index] = pattern.sub(replacement, parts[index])

    return "`".join(parts)


def use_minus_signs(text):
    """-4 e (-1) passam a −4 e (−1): o hífen é mais curto e mais alto do que o sinal de menos."""
    return re.sub(r"(?<![\w.])-(?=[\d(a-zA-Zα-ω√])", "−", text)


def format_cell(text):
    return format_inline_math(html.escape(use_minus_signs(text.strip())))


def split_matrix_row(row):
    """Separa as células por espaços; se houver contas dentro das células, só por 2+ espaços."""
    tokens = row.split()

    if any(token in {"+", "−", "-", "·", "×", "=", "/"} for token in tokens):
        return COLUMN_GAP.split(row.strip())

    return tokens


def find_bar_columns(lines):
    """Colunas de texto onde todas as linhas têm uma barra: os lados das matrizes desenhadas com |."""
    columns = set(index for index, char in enumerate(lines[0]) if char == "|")

    for line in lines[1:]:
        columns &= {index for index, char in enumerate(line) if char == "|"}

    return sorted(columns)


def build_matrix_html(lines, bar_columns):
    """'L = | 2 0 |   U = | 1 3 |' -> o texto à volta e cada matriz entre parênteses retos, lado a lado."""
    width = max(len(line) for line in lines)
    lines = [line.ljust(width) for line in lines]
    edges = [0] + bar_columns + [width]
    parts = []

    for index in range(len(edges) - 1):
        start = edges[index] + (1 if index > 0 else 0)
        segment = [line[start : edges[index + 1]] for line in lines]

        if index % 2 == 1:
            rows = []

            for row in segment:
                cells = split_matrix_row(row)
                rows.append("<tr>" + "".join(f"<td>{format_cell(cell)}</td>" for cell in cells) + "</tr>")

            parts.append(f'<table class="matrix">{"".join(rows)}</table>')
        else:
            label = " ".join(text.strip() for text in segment if text.strip())
            parts.append(f"<span>{format_cell(label)}</span>")

    return f'<div class="matrix-line">{"".join(parts)}</div>'


def build_grid_html(rows):
    """Linhas com colunas separadas por 2+ espaços -> tabela; com 3+ colunas, a 1.ª linha é cabeçalho."""
    has_header = len(rows[0]) >= 3
    body = []

    for row_index, row in enumerate(rows):
        row_class = ' class="header"' if has_header and row_index == 0 else ""
        cells = "".join(
            f'<td{" class=\"label\"" if column == 0 else ""}>{format_cell(cell)}</td>' for column, cell in enumerate(row)
        )
        body.append(f"<tr{row_class}>{cells}</tr>")

    return f'<table class="math-table">{"".join(body)}</table>'


def build_math_block_html(content):
    lines = [line for line in content.splitlines() if line.strip()]
    bar_columns = find_bar_columns(lines) if lines else []

    if bar_columns and len(bar_columns) % 2 == 0 and all(line.count("|") == len(bar_columns) for line in lines):
        return build_matrix_html(lines, bar_columns)

    rows = [COLUMN_GAP.split(line.strip()) for line in lines]
    widths = {len(row) for row in rows}

    if len(rows) >= 2 and len(widths) == 1 and widths.pop() >= 2:
        return build_grid_html(rows)

    # Com espaços de alinhamento por dentro, só uma letra de largura fixa mantém as colunas.
    is_aligned = any(COLUMN_GAP.search(line.strip()) for line in lines) or "|" in content
    if is_aligned:
        body = "\n".join(format_inline_math(html.escape(use_minus_signs(line.rstrip()))) for line in content.splitlines())

        return f'<div class="math aligned">{body}</div>'

    css_class = "math"
    body = "<br>".join(format_cell(line) or "&nbsp;" for line in content.splitlines())

    return f'<div class="{css_class}">{body}</div>'


def strip_metadata_block(markdown_text):
    """Tira as linhas entre o título (# ...) e a primeira secção (## ...): disciplina, fonte e índice."""
    lines = markdown_text.splitlines()
    title_index = next((i for i, line in enumerate(lines) if line.startswith("# ")), None)

    if title_index is None:
        return markdown_text

    section_index = next(
        (i for i, line in enumerate(lines) if i > title_index and line.startswith("## ")), len(lines)
    )

    return "\n".join(lines[: title_index + 1] + [""] + lines[section_index:])


def render_markdown(markdown_text):
    blocks = []

    def keep_block(match):
        if match.group(1):
            return match.group(0)

        blocks.append(build_math_block_html(match.group(2)))

        return f"\n\nMATHBLOCK{len(blocks) - 1}\n\n"

    text = FENCED_BLOCK.sub(keep_block, strip_metadata_block(markdown_text))
    segments = re.split(r"(^```.*?^```[ \t]*$)", text, flags=re.MULTILINE | re.DOTALL)
    text = "".join(segment if segment.startswith("```") else format_inline_math(segment) for segment in segments)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])

    for index, block in enumerate(blocks):
        body = body.replace(f"<p>MATHBLOCK{index}</p>", block)

    return body


def build_html(markdown_text, title):
    body = render_markdown(markdown_text)

    return (
        f'<!doctype html><html lang="pt-PT"><head><meta charset="utf-8">'
        f'<title>{html.escape(title)}</title><link rel="stylesheet" href="{FONTS_URL}">'
        f"<style>{PAGE_STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )


def print_to_pdf(html_text, destination, profile_dir):
    with tempfile.NamedTemporaryFile("w", suffix=".html", encoding="utf-8", delete=False) as page:
        page.write(html_text)

    command = [
        CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
        # Dá tempo para as fontes do Google Fonts chegarem antes de imprimir.
        "--virtual-time-budget=15000",
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
