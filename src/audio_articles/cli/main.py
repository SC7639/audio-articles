from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from audio_articles.core.exceptions import AudioArticlesError
from audio_articles.core.models import ArticleInput
from audio_articles.core.pipeline import run, run_from_file, save_audio

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
) -> None:
    """
    Convert an article (URL, file, or inline text) to an MP3 audiobook.

    Examples:

      audio-articles convert --url https://example.com/article

      audio-articles convert --file article.txt --output out.mp3

      audio-articles convert --url https://example.com/article --script-only
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

    try:
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as progress:
            if file:
                progress.add_task("Reading file and extracting article…")
                if not file.exists():
                    console.print(f"[red]Error:[/red] File not found: {file}")
                    raise typer.Exit(1)
                result = run_from_file(file, title=title)
            else:
                progress.add_task("Fetching article, summarizing, and synthesizing audio…")
                article_input = ArticleInput(url=url, text=text, title=title)
                result = run(article_input)
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
