"""FastAPI application entrypoint for the hypervisor."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse

from autoplay.common.constants import MODPACK_FOLDER_REGEX
from autoplay.hypervisor import game_stats_db, runner_names_db, stats_ingest
from autoplay.hypervisor.config import HypervisorConfig, load_config
from autoplay.hypervisor.db import RunnerDB
from autoplay.hypervisor.routes import control as control_routes
from autoplay.hypervisor.routes import files as files_routes
from autoplay.hypervisor.routes import runners as runner_routes

logger = logging.getLogger(__name__)

_WEBAPP_DIR = Path(__file__).parent / "webapp"
_INDEX_HTML = _WEBAPP_DIR / "index.html"

_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _ensure_storage_layout(cfg: HypervisorConfig) -> None:
    cfg.storage_root.mkdir(parents=True, exist_ok=True)


def _eager_create_duckdbs(cfg: HypervisorConfig) -> None:
    """Pre-create ``stats.duckdb`` for every existing modpack directory.

    Ensures the per-modpack DuckDB (and its ``uuid_dictionary``) exists before
    any upload arrives so ingestion never races directory creation.
    """
    for modpack_dir in cfg.storage_root.iterdir():
        if not modpack_dir.is_dir():
            continue
        if not MODPACK_FOLDER_REGEX.match(modpack_dir.name):
            continue
        try:
            stats_ingest.ensure_duckdb(cfg.storage_root, modpack_dir.name)
        except Exception:  # noqa: BLE001 - best-effort eager creation
            logger.exception("Failed to pre-create stats.duckdb for %s", modpack_dir.name)


async def _stats_ingest_worker(app: FastAPI, queue: asyncio.Queue[Path]) -> None:
    """Single background consumer that ingests staged stats dbs one at a time."""
    while True:
        db_path = await queue.get()
        try:
            await files_routes.process_stats_upload(app, db_path)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never let the worker die on one file
            logger.exception("Unhandled error ingesting %s", db_path)
        finally:
            queue.task_done()


def create_app(config: HypervisorConfig | None = None) -> FastAPI:
    cfg = config or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _ensure_storage_layout(cfg)
        db_path = cfg.storage_root / "runners.db"
        if db_path.exists():
            db_path.unlink()
            logger.info("Deleted stale runners.db")
        db = RunnerDB(db_path)
        db.init_schema()
        game_stats_db.init(cfg.storage_root)
        runner_names_db.init(cfg.storage_root)
        app.state.config = cfg
        app.state.db = db

        worker_task: asyncio.Task | None = None
        if cfg.stats_mode == "sqlite":
            queue: asyncio.Queue[Path] = asyncio.Queue()
            app.state.stats_queue = queue
            _eager_create_duckdbs(cfg)
            # Re-enqueue any uploads left in ``incoming/`` from a prior run.
            incoming = files_routes._incoming_dir(cfg.storage_root)
            incoming.mkdir(parents=True, exist_ok=True)
            leftovers = sorted(p for p in incoming.glob("*.db") if p.is_file())
            for leftover in leftovers:
                queue.put_nowait(leftover)
            if leftovers:
                logger.info("Re-enqueued %d leftover stats db(s)", len(leftovers))
            worker_task = asyncio.create_task(_stats_ingest_worker(app, queue))
            logger.info("SQLite-stats ingest worker started")
        else:
            app.state.stats_queue = None
            logger.info("Legacy CSV-log mode; SQLite ingest disabled")

        logger.info("Hypervisor ready; STORAGE_ROOT=%s", cfg.storage_root.resolve())
        try:
            yield
        finally:
            if worker_task is not None:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_task

    app = FastAPI(title="Civ5 VP Autoplay Hypervisor", lifespan=lifespan)
    app.include_router(runner_routes.router)
    app.include_router(files_routes.router)
    app.include_router(control_routes.router)

    # The webapp is a single self-contained HTML file (CSS/JS embedded) and
    # is always served with no-cache headers so config-tweaks ship instantly.
    @app.get("/", include_in_schema=False)
    async def _serve_index() -> Response:
        return FileResponse(_INDEX_HTML, media_type="text/html", headers=_NO_CACHE_HEADERS)

    @app.get("/index.html", include_in_schema=False)
    async def _serve_index_alias() -> Response:
        return FileResponse(_INDEX_HTML, media_type="text/html", headers=_NO_CACHE_HEADERS)

    return app


app = create_app()
