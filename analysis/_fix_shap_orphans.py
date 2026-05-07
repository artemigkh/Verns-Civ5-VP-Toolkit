"""Post-fix: when comment_shap commented a line that opened a multi-line call,
its argument lines were left dangling and cause IndentationError.  Walk the
already-wrapped notebook and comment out those orphaned continuation lines."""
import json
import re
from pathlib import Path

NB = Path(__file__).with_name("Report.ipynb")
nb = json.loads(NB.read_text(encoding="utf-8"))

SHAP_TAG = "# [SHAP-DISABLED]"


def fix(src: str) -> str:
    lines = src.splitlines()
    out = list(lines)
    i = 0
    while i < len(out):
        line = out[i]
        if SHAP_TAG in line:
            # depth from this commented logical line
            stripped_payload = line.split(SHAP_TAG, 1)[1]
            depth = stripped_payload.count("(") - stripped_payload.count(")")
            depth += stripped_payload.count("[") - stripped_payload.count("]")
            depth += stripped_payload.count("{") - stripped_payload.count("}")
            j = i + 1
            while depth > 0 and j < len(out):
                nxt = out[j]
                if SHAP_TAG in nxt:
                    payload = nxt.split(SHAP_TAG, 1)[1]
                else:
                    indent = re.match(r"^(\s*)", nxt).group(1)
                    out[j] = f"{indent}{SHAP_TAG} {nxt.lstrip()}"
                    payload = nxt
                depth += payload.count("(") - payload.count(")")
                depth += payload.count("[") - payload.count("]")
                depth += payload.count("{") - payload.count("}")
                j += 1
            i = j
        else:
            i += 1
    return "\n".join(out)


changed = 0
for c in nb["cells"]:
    if c.get("cell_type") != "code":
        continue
    src = "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
    new = fix(src)
    if new != src:
        c["source"] = new.splitlines(keepends=True)
        c["outputs"] = []
        c["execution_count"] = None
        changed += 1

NB.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print("fixed cells:", changed)
