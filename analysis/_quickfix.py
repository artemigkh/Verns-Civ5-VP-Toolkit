import json
from pathlib import Path
p = Path('Report.ipynb')
nb = json.loads(p.read_text(encoding='utf-8'))
n = 0
for c in nb['cells']:
    if c.get('cell_type') != 'code':
        continue
    s = ''.join(c['source'])
    new_s = s
    if 'count()[0]' in new_s:
        new_s = new_s.replace('count()[0]', 'count().iloc[0]')
    if 'ax2.yaxis.set_major_locator(locator)' in new_s:
        new_s = new_s.replace(
            '    ax2.yaxis.set_major_locator(locator)',
            '    # ax2.yaxis.set_major_locator(locator)  # locator/ax3 not defined',
        )
        new_s = new_s.replace(
            '    ax3.yaxis.set_major_locator(locator)',
            '    # ax3.yaxis.set_major_locator(locator)',
        )
    if new_s != s:
        c['source'] = new_s.splitlines(keepends=True)
        c['outputs'] = []
        c['execution_count'] = None
        n += 1
p.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding='utf-8')
print('patched', n)
