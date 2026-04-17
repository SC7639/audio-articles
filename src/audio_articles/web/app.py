from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from audio_articles.core.config import get_settings

from .routes import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Audio Articles",
        description="Convert web articles into concise MP3 audiobooks.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(router)

    static_dir = Path(__file__).parent / "static"
    settings = get_settings()
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/library", include_in_schema=False)
    async def library_page():
        return FileResponse(static_dir / "library.html")

    app.mount("/output", StaticFiles(directory=str(output_dir)), name="output")
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
