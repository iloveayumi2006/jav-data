"""Local web application and startup readiness checks."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from sqlalchemy import inspect, text

from jav_data import __version__
from jav_data.config import Settings
from jav_data.database import make_engine
from jav_data.discovery import Discovery
from jav_data.discovery import router as discovery_router
from jav_data.downloads import DownloadWorker
from jav_data.jobs import ScrapeWorker
from jav_data.library import router as library_router
from jav_data.library_sync import LibraryActivity
from jav_data.movies import router
from jav_data.nfo import router as nfo_router
from jav_data.scrape_api import router as scrape_router
from jav_data.storage import router as storage_router


def create_app(settings: Settings | None = None, browser_factory=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        current = settings or Settings.load()
        current.prepare()
        engine = make_engine(current)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                if not inspect(connection).has_table("alembic_version"):
                    raise RuntimeError("Database needs migration: run alembic upgrade head")
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
                if revision != "0007_removable_libraries":
                    raise RuntimeError("Database needs migration: run alembic upgrade head")
            app.state.settings = current
            app.state.engine = engine
            app.state.library_lock = LibraryActivity()
            app.state.worker = ScrapeWorker(
                current, engine, browser_factory, app.state.library_lock
            )
            app.state.worker.start()
            app.state.discovery = Discovery(current, app.state.worker)
            app.state.downloader = DownloadWorker(current, engine, app.state.library_lock)
            app.state.downloader.start()
            yield
        finally:
            if hasattr(app.state, "discovery"):
                app.state.discovery.stop()
            if hasattr(app.state, "worker"):
                app.state.worker.stop()
            if hasattr(app.state, "downloader"):
                app.state.downloader.stop()
            engine.dispose()

    app = FastAPI(title="jav-data", version=__version__, lifespan=lifespan)
    app.include_router(router)
    app.include_router(nfo_router)
    app.include_router(scrape_router)
    app.include_router(library_router)
    app.include_router(discovery_router)
    app.include_router(storage_router)

    @app.get("/health")
    def health(request: Request):
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"app": "jav-data", "status": "ok", "database": "ok", "version": __version__}

    return app
