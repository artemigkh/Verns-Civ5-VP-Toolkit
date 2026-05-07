import json
from pathlib import Path

nb = json.loads(Path("Report.ipynb").read_text(encoding="utf-8"))
errs = []
for i, c in enumerate(nb["cells"]):
    if c.get("cell_type") != "code":
        continue
    parts = []
    has_err = False
    for o in c.get("outputs", []):
        if o.get("output_type") == "stream":
            text = "".join(o.get("text", []))
            if "[CELL ERROR]" in text or "Traceback" in text or o.get("name") == "stderr":
                parts.append(f"[{o.get('name')}]\n{text}")
                if "[CELL ERROR]" in text or "Traceback" in text:
                    has_err = True
        elif o.get("output_type") == "error":
            parts.append(f"{o.get('ename')}: {o.get('evalue')}\n" + "\n".join(o.get("traceback", [])))
            has_err = True
    if has_err:
        errs.append((i, "\n".join(parts)))

print(f"total error cells: {len(errs)}")
for i, t in errs:
    print(f"\n========== cell index {i} ==========")
    print(t[:2000])
