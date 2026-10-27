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
- `autoplay\scripts\run_headless.bat` — starts a headless bridge: games played in civ5-headless, several at once,
  each worker slot shown as a runner (see "Headless Bridge" in `autoplay_design.md`)

Open <http://localhost:5000/> to see the dashboard.

## Layout

- `autoplay/common/` — shared pydantic models and constants
- `autoplay/hypervisor/` — FastAPI server that collects logs and manages runners
- `autoplay/runner/` — FastAPI server that launches Civ5 and streams logs to the hypervisor
- `autoplay/headless/` — FastAPI server that plays c5h queues in civ5-headless and reports them like runners
