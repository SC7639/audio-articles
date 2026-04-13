from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from audio_articles.core.exceptions import AudioArticlesError
from audio_articles.core.models import ArticleInput, QATurn
from audio_articles.core.pipeline import run, run_full, run_full_from_file, save_audio

app = typer.Typer(
    name="audio-articles",
    help="Convert web articles into concise MP3 audiobooks.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()

VoiceOption = Annotated[
    str | None,
    typer.Option(
        "--voice",
        "-v",
        help="TTS voice: alloy | echo | fable | onyx | nova | shimmer",
    ),
]


@app.command()
def convert(
    url: Annotated[str | None, typer.Option("--url", "-u", help="URL of the article to fetch.")] = None,
    file: Annotated[Path | None, typer.Option("--file", "-f", help="Path to a plain-text file.")] = None,
    text: Annotated[str | None, typer.Option("--text", "-t", help="Raw article text (inline).")] = None,
    title: Annotated[str | None, typer.Option("--title", help="Override the article title.")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output MP3 file path.")] = None,
    output_dir: Annotated[str | None, typer.Option("--output-dir", help="Directory to save the output MP3.")] = None,
    voice: VoiceOption = None,
    script_only: Annotated[bool, typer.Option("--script-only", help="Print the script without generating audio.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print the script after conversion.")] = False,
    interactive: Annotated[bool, typer.Option("--interactive", "-i", help="After converting, enter interactive Q&A mode.")] = False,
) -> None:
    """
    Convert an article (URL, file, or inline text) to an MP3 audiobook.

    Examples:

      audio-articles convert --url https://example.com/article

      audio-articles convert --file article.txt --output out.mp3

      audio-articles convert --url https://example.com/article --script-only

      audio-articles convert --url https://example.com/article --interactive
    """
    # Validate that exactly one source is provided
    sources = [x for x in [url, file, text] if x is not None]
    if len(sources) == 0:
        console.print("[red]Error:[/red] Provide one of --url, --file, or --text.")
        raise typer.Exit(1)
    if len(sources) > 1:
        console.print("[red]Error:[/red] Provide only one of --url, --file, or --text.")
        raise typer.Exit(1)

    # Apply voice override before pipeline runs
    if voice:
        from audio_articles.core.config import get_settings
        s = get_settings()
        object.__setattr__(s, "tts_voice", voice)

    extraction = None
    try:
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as progress:
            if file:
                progress.add_task("Reading file and extracting article…")
                if not file.exists():
                    console.print(f"[red]Error:[/red] File not found: {file}")
                    raise typer.Exit(1)
                if interactive or script_only:
                    result, extraction = run_full_from_file(file, title=title)
                else:
                    from audio_articles.core.pipeline import run_from_file
                    result = run_from_file(file, title=title)
            else:
                progress.add_task("Fetching article, summarizing, and synthesizing audio…")
                article_input = ArticleInput(url=url, text=text, title=title)
                if interactive or script_only:
                    result, extraction = run_full(article_input)
                else:
                    result = run(article_input)
                    extraction = None
    except AudioArticlesError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if script_only:
        console.print(result.script)
        return

    if verbose:
        console.print("\n[bold]Script:[/bold]")
        console.print(result.script)
        console.print()

    # Save the audio
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(result.audio_bytes)
        saved = output
    else:
        saved = save_audio(result, output_dir=output_dir)

    console.print(f"[green]Saved:[/green] {saved}")
    console.print(f"[dim]Title:[/dim]  {result.title}")
    console.print(f"[dim]Words:[/dim]  {len(result.script.split())}")

    if interactive and extraction:
        _qa_repl(extraction)


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="Question to ask about the article.")],
    url: Annotated[str | None, typer.Option("--url", "-u", help="URL of the article.")] = None,
    file: Annotated[Path | None, typer.Option("--file", "-f", help="Path to a plain-text file.")] = None,
    text: Annotated[str | None, typer.Option("--text", "-t", help="Raw article text (inline).")] = None,
    title: Annotated[str | None, typer.Option("--title", help="Override the article title.")] = None,
) -> None:
    """
    Ask a one-off question about an article.

    Examples:

      audio-articles ask "What is the main argument?" --url https://example.com/article

      audio-articles ask "Who is quoted in this piece?" --file article.txt
    """
    sources = [x for x in [url, file, text] if x is not None]
    if len(sources) == 0:
        console.print("[red]Error:[/red] Provide one of --url, --file, or --text.")
        raise typer.Exit(1)
    if len(sources) > 1:
        console.print("[red]Error:[/red] Provide only one of --url, --file, or --text.")
        raise typer.Exit(1)

    from audio_articles.core.fetcher import extract_from_file, extract_from_text, fetch_and_extract
    from audio_articles.core.qa import ask as qa_ask

    try:
        with Progress(SpinnerColumn(), TextColumn("Fetching article…"), transient=True) as progress:
            progress.add_task("")
            if file:
                if not file.exists():
                    console.print(f"[red]Error:[/red] File not found: {file}")
                    raise typer.Exit(1)
                extraction = extract_from_file(file, title=title)
            elif url:
                extraction = fetch_and_extract(url)
                if title:
                    extraction = extraction.model_copy(update={"title": title})
            else:
                extraction = extract_from_text(text or "", title=title or "Article")

        with Progress(SpinnerColumn(), TextColumn("Thinking…"), transient=True) as progress:
            progress.add_task("")
            answer = qa_ask(question, extraction)
    except AudioArticlesError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    console.print(answer)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _qa_repl(extraction) -> None:
    """Interactive Q&A loop for a given ExtractionResult."""
    from audio_articles.core.qa import ask as qa_ask

    history: list[QATurn] = []

    console.print(
        "\n[bold]Article Q&A[/bold] — ask questions about the article. "
        "Type [dim]exit[/dim] or press Ctrl+C to quit.\n"
    )

    while True:
        try:
            question = console.input("[bold cyan]Question:[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nBye!")
            break

        if not question or question.lower() in ("exit", "quit", "q"):
            break

        try:
            with Progress(SpinnerColumn(), TextColumn("Thinking…"), transient=True) as progress:
                progress.add_task("")
                answer = qa_ask(question, extraction, history=history)
        except AudioArticlesError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            continue

        console.print(f"\n[bold]Answer:[/bold] {answer}\n")
        history.append(QATurn(question=question, answer=answer))
