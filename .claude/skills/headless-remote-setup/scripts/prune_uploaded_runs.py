"""Empty the run folders of completed games the bridge already handed to the hypervisor.

Reads <work_dir>/uploads.jsonl (the bridge's upload ledger). Only rows with completed=true and outcome
"uploaded" or "staged" count; failed and rejected games, and runs the ledger never recorded (games killed
mid-play, c5h's "-rN" earlier attempts), are left alone.

Each folder keeps c5h's status.json: c5h decides from it whether a job is done whenever it (re)starts a
batch, and replays (and the bridge re-uploads) any game without one. A folder an older bridge deleted
outright gets a minimal status.json back for the same reason. Each also keeps its report.html (~1 MB), as
the bridge's own pruning does. Dry run unless --delete is given.

    python prune_uploaded_runs.py <work_dir> [--delete]
"""

import json
import shutil
import sys
from pathlib import Path


KEEP = ("status.json", "report.html")  # the bridge's harvest.KEPT_ON_PRUNE


def folder_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def kept_size(p: Path) -> int:
    return sum((p / name).stat().st_size for name in KEEP if (p / name).is_file())


work_dir, delete = Path(sys.argv[1]), "--delete" in sys.argv[2:]
empty, restore = [], []
for line in (work_dir / "uploads.jsonl").read_text(encoding="utf-8").splitlines():
    try:
        row = json.loads(line)
    except ValueError:
        continue
    run = Path(row.get("runDir") or "")
    if not (row.get("completed") and row.get("outcome") in ("uploaded", "staged") and run.name):
        continue
    if not run.is_dir():
        restore.append((run, row))
    elif any(p.name not in KEEP for p in run.iterdir()):
        empty.append(run)

size = sum(folder_size(p) - kept_size(p) for p in empty)
print(f"{len(empty)} uploaded run folders to empty ({size / 2**30:.2f} GB), "
      f"{len(restore)} deleted ones to restore status.json in" + ("" if delete else " (dry run)"))
if delete:
    failed = 0
    for run in empty:
        for child in run.iterdir():
            if child.name in KEEP:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        failed += any(p.name not in KEEP for p in run.iterdir())
    for run, row in restore:
        run.mkdir(parents=True, exist_ok=True)
        status = {"state": "completed", "endTurn": row.get("endTurn"), "restoredFrom": "uploads.jsonl"}
        (run / "status.json").write_text(json.dumps(status, indent=1) + "\n", encoding="utf-8")
    print(f"emptied {len(empty) - failed} (could not fully empty {failed}), restored {len(restore)}")
runs = work_dir / "runs"
left = sum(folder_size(b) for b in runs.iterdir() if b.is_dir()) if runs.is_dir() else 0
print(f"runs/ now holds {left / 2**30:.2f} GB")
