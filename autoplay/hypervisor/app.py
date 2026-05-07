"""FastAPI application entrypoint for the hypervisor."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse

from autoplay.hypervisor.config import HypervisorConfig, load_config
from autoplay.hypervisor.db import RunnerDB
from autoplay.hypervisor.routes import control as control_routes
from autoplay.hypervisor.routes import files as files_routes
from autoplay.hypervisor.routes import runners as runner_routes
from autoplay.hypervisor import runner_names_db, game_stats_db

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
        logger.info("Hypervisor ready; STORAGE_ROOT=%s", cfg.storage_root.resolve())
        yield

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
