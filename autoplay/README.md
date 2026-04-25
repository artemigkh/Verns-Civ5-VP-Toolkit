# Autoplay

Civ 5 Vox Populi autoplay hypervisor and runner.

## Setup

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.12.

```
cd autoplay
uv sync
```

## Running

From the repo root:

- `autoplay\scripts\run_hypervisor.bat` — starts the hypervisor on port 5000
- `autoplay\scripts\run_runner.bat` — starts a runner that registers with the hypervisor

Open <http://localhost:5000/> to see the dashboard.

## Layout

- `autoplay/common/` — shared pydantic models and constants
- `autoplay/hypervisor/` — FastAPI server that collects logs and manages runners
- `autoplay/runner/` — FastAPI server that launches Civ5 and streams logs to the hypervisor
