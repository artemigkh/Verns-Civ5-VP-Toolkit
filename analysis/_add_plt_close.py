import json
from pathlib import Path

p = Path("Report.ipynb")
nb = json.loads(p.read_text(encoding="utf-8"))

OLD = "    _tb.print_exc()"
NEW = (
    "    _tb.print_exc()\n"
    "    try:\n"
    "        import matplotlib.pyplot as _plt\n"
    "        _plt.close('all')\n"
    "    except Exception:\n"
    "        pass"
)

n = 0
for c in nb["cells"]:
    if c.get("cell_type") != "code":
        continue
    s = "".join(c["source"])
    if OLD in s and "_plt.close('all')" not in s:
        s2 = s.replace(OLD, NEW)
        c["source"] = s2.splitlines(keepends=True)
        c["outputs"] = []
        c["execution_count"] = None
        n += 1

p.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print("patched", n)
