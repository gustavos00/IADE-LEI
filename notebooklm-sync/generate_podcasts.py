#!/usr/bin/env python3
"""Gera no Gemini Notebook um podcast (Audio Overview) por módulo de cada disciplina.

Os módulos são intercalados entre disciplinas: módulo 01 de cada uma, depois módulo 02 de
cada uma, e assim por diante. Cada podcast usa só as fontes desse módulo (incluindo os
seus Recursos da Aula Virtual), fica no caderno com o título "Podcast · <módulo>" e é
descarregado para ~/Faculdade/<disciplina>/<módulo>/.

Um podcast gasta boa parte da quota de 5 horas, por isso o script gera enquanto há quota,
pára quando acaba e, na vez seguinte, continua onde ficou.

Uso:
  python generate_podcasts.py [--listar] [--max N] [--refazer "Vetores"]
  python generate_podcasts.py --disciplina "Fundamentos da Programação"
"""

import argparse
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
from notebooklm import AudioFormat, AudioLength, AuthError, NotebookLMClient
from notebooklm.types import UsageActionKind

from sync_notebooks import NOTEBOOK_PREFIX, TITLE_SEPARATOR

DEFAULT_SUBJECTS = ["Álgebra Linear", "Análise Matemática", "Física", "Sistemas Digitais"]
PODCAST_PREFIX = "Podcast · "
LANGUAGE = "pt_PT"
# BRIEF é o formato de um só apresentador (curto por omissão); DEEP_DIVE é a conversa a dois.
AUDIO_FORMAT = AudioFormat.BRIEF
AUDIO_LENGTH = AudioLength.LONG
GENERATION_TIMEOUT_SECONDS = 1800
# Gerações já pedidas mas ainda não descarregadas; evita pedir (e pagar) a mesma duas vezes.
STATE_FILE = Path(__file__).with_name(".podcasts-pendentes.json")
# O NotebookLM entrega o áudio a uns -23 LUFS (volume de televisão); -16 é o habitual em podcasts.
TARGET_LOUDNESS = "loudnorm=I=-16:TP=-1.5:LRA=11"
# O apresentador fala depressa para quem está a aprender a matéria; atempo mantém o tom da voz.
PLAYBACK_SPEED = 0.85


def build_instructions(subject, module):
    return (
        f"Um só apresentador, em português de Portugal, a explicar a um estudante do 1.º ano de "
        f"Engenharia Informática o módulo «{module}» da disciplina {subject}, como um professor "
        "numa explicação. Com calma e sem pressa: percorre todos os conceitos das fontes, pela "
        "ordem em que aparecem, e para cada um explica o porquê e o como — de onde vem, como se "
        "calcula passo a passo e porque é que o resultado é o que é (por exemplo, como se calcula "
        "um escalar ou um produto, e porque é que uma matriz tem a dimensão 3×2 e não outra). "
        "Resolve em voz alta os exemplos e exercícios das próprias fontes e aponta os erros mais "
        "comuns. Os exemplos vêm só da matéria: nada de analogias com jogos, desporto, filmes ou o "
        "dia a dia. A primeira frase já é matéria: não cumprimentes, não anuncies o tema nem o que "
        "vais explicar, e não faças resumos no fim. Sem conversa de circunstância nem conclusões "
        "motivacionais. Usa só as fontes selecionadas."
    )


def parse_module_number(module):
    match = re.match(r"^(\d+) - ", module)

    return int(match.group(1)) if match else None


def group_sources_by_module(sources):
    modules = {}

    for source in sources:
        module = source.title.split(TITLE_SEPARATOR)[0]

        if parse_module_number(module) is not None:
            modules.setdefault(module, []).append(source.id)

    return modules


def build_queue(subject_modules, subjects):
    """[(número, disciplina, módulo, fontes)] ordenado por número de módulo e depois pela ordem das disciplinas."""
    queue = []

    for subject_index, subject in enumerate(subjects):
        for module, source_ids in subject_modules.get(subject, {}).items():
            queue.append((parse_module_number(module), subject_index, subject, module, source_ids))

    queue.sort()

    return [(subject, module, source_ids) for _, _, subject, module, source_ids in queue]


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except FileNotFoundError:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def adjust_audio(path):
    """Abranda para PLAYBACK_SPEED e normaliza o volume para TARGET_LOUDNESS, substituindo o ficheiro."""
    adjusted = path.with_name(f"{path.stem}.tmp{path.suffix}")
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(path), "-af", f"atempo={PLAYBACK_SPEED},{TARGET_LOUDNESS}",
        "-c:a", "aac", "-b:a", "192k", str(adjusted),
    ]
    subprocess.run(command, check=True)
    adjusted.replace(path)


def build_podcast_path(root, subject, module):
    return root / subject / module / f"{PODCAST_PREFIX}{module}.m4a"


async def has_audio_quota(client):
    usage = await client.settings.get_usage()

    for action in usage.actions:
        if action.kind == UsageActionKind.AUDIO_OVERVIEW:
            if not action.has_sufficient_quota:
                reset = min((window.resets_at for window in usage.windows if window.resets_at), default=None)
                print(f"\nQuota de podcasts esgotada. Volta a haver a partir de {reset:%Y-%m-%d %H:%M} UTC.")

                return False

            return True

    return True


async def archive_previous_version(client, notebook_id, task_id, title, destination):
    """Ao refazer um podcast, a versão anterior fica com "(versão anterior)" no caderno e no disco."""
    archived_title = f"{title} (versão anterior)"

    for artifact in await client.artifacts.list_audio(notebook_id):
        if artifact.title == title and artifact.id != task_id:
            await client.artifacts.rename(notebook_id, artifact.id, archived_title)

    if destination.exists():
        destination.replace(destination.with_name(f"{archived_title}{destination.suffix}"))


async def finish_podcast(client, notebook_id, task_id, title, destination):
    status = await client.artifacts.wait_for_completion(notebook_id, task_id, timeout=GENERATION_TIMEOUT_SECONDS)

    if not status.is_complete:
        print(f"   falhou: {title} ({status.error or status.status})")

        return False

    await archive_previous_version(client, notebook_id, task_id, title, destination)
    await client.artifacts.rename(notebook_id, task_id, title)
    destination.parent.mkdir(parents=True, exist_ok=True)
    await client.artifacts.download_audio(notebook_id, str(destination), artifact_id=task_id)
    adjust_audio(destination)
    print(f"   pronto: {title}  →  {destination}")

    return True


async def generate_all(root, subjects, list_only, limit, redo):
    state = load_state()

    async with NotebookLMClient.from_storage() as client:
        notebooks = {nb.title: nb for nb in await client.notebooks.list()}
        subject_modules = {}
        done_titles = {}

        for subject in subjects:
            notebook = notebooks.get(NOTEBOOK_PREFIX + subject)

            if notebook is None:
                print(f"Caderno {NOTEBOOK_PREFIX + subject} não existe. Corre primeiro o sync_notebooks.py.")
                continue

            subject_modules[subject] = group_sources_by_module(await client.sources.list(notebook.id))
            done_titles[subject] = {artifact.title for artifact in await client.artifacts.list_audio(notebook.id)}

        queue = build_queue(subject_modules, subjects)
        todo = [
            item
            for item in queue
            if PODCAST_PREFIX + item[1] not in done_titles[item[0]]
            or any(text.lower() in f"{item[0]} / {item[1]}".lower() for text in redo)
        ]
        print(f"Podcasts: {len(queue) - len(todo)} feitos, {len(todo)} por fazer.")

        # Os pedidos já em curso vêm primeiro, para --max 1 acabar o que ficou a meio em vez de pedir outro.
        todo.sort(key=lambda item: f"{item[0]} / {item[1]}" not in state)
        failed = 0

        for subject, module, source_ids in todo[:limit]:
            notebook_id = notebooks[NOTEBOOK_PREFIX + subject].id
            title = PODCAST_PREFIX + module
            key = f"{subject} / {module}"
            destination = build_podcast_path(root, subject, module)
            print(f"\n== {key}  ({len(source_ids)} fontes)")

            if list_only:
                continue

            if key not in state:
                if not await has_audio_quota(client):
                    break

                status = await client.artifacts.generate_audio(
                    notebook_id,
                    source_ids,
                    language=LANGUAGE,
                    instructions=build_instructions(subject, module),
                    audio_format=AUDIO_FORMAT,
                    audio_length=AUDIO_LENGTH,
                )

                if status.is_failed or status.is_rate_limited:
                    print(f"   o pedido foi recusado ({status.error or status.status}); paro aqui.")
                    break

                state[key] = status.task_id
                save_state(state)
                print("   a gerar (costuma demorar 5 a 15 minutos)...")
            else:
                print("   já tinha sido pedido; à espera dele...")

            is_ready = await finish_podcast(client, notebook_id, state[key], title, destination)
            del state[key]
            save_state(state)
            failed += 0 if is_ready else 1

    return failed


def parse_arguments():
    parser = argparse.ArgumentParser(description="Gera um podcast por módulo no Gemini Notebook.")
    parser.add_argument(
        "--disciplina",
        action="append",
        help="disciplina a tratar, pela ordem dada (pode repetir-se); por omissão as quatro sem Fundamentos",
    )
    parser.add_argument("--pasta", default="~/Faculdade", help="onde guardar os podcasts descarregados")
    parser.add_argument("--listar", action="store_true", help="só mostra a ordem e o que falta")
    parser.add_argument("--max", type=int, help="trata no máximo N podcasts nesta volta")
    parser.add_argument(
        "--refazer",
        action="append",
        default=[],
        help="volta a gerar os módulos cujo nome contém este texto (pode repetir-se)",
    )

    return parser.parse_args()


def main():
    arguments = parse_arguments()
    subjects = arguments.disciplina or DEFAULT_SUBJECTS

    try:
        failed = asyncio.run(generate_all(Path(arguments.pasta).expanduser(), subjects, arguments.listar, arguments.max, arguments.refazer))
    # Sem login a biblioteca não encontra o storage_state.json; com a sessão expirada dá AuthError.
    except (AuthError, FileNotFoundError):
        sys.exit("Sessão do Google em falta ou expirada. Corre: notebooklm login")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
