import subprocess
import sys
from pathlib import Path

def run(cmd):
    print('>',' '.join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
    return r.returncode

root = Path(__file__).resolve().parent
feat_msg = '''feat(kpi): detectar repositorios automáticamente y añadir desglose por rama

- Escanea archivos del repo (.md, .json, .yml, .py, etc.) para encontrar enlaces a GitHub y construir la lista normalizada owner/repo.
- Normaliza URLs (.git, barras finales, SSH) y elimina duplicados.
- Intenta variantes comunes (guion ↔ guion_bajo) al resolver ramas.
- Añade desglose por rama: repos[repo]["by_branch"] y participants[user]["by_branch"].
- Añade filtro opcional branch_filter_regex en kpi-repos.json.
- Deduplicación global por SHA y conteo por rama; errores por repo no abortan.
- Mejora --dry-run y logging. Recomendado usar KPI_GH_TOKEN para CI.
'''
ci_msg = '''ci(workflow): incluir kpi-repos.json en el commit del workflow update-kpi

- Actualiza .github/workflows/update-kpi.yml para agregar kpi-repos.json al área staged antes de commitear, permitiendo que los repos descubiertos automáticamente sean persistidos por la Action.
'''

# Write temporary files
(feat_file := root / '.git-commit-feat.txt').write_text(feat_msg, encoding='utf-8')
(ci_file := root / '.git-commit-ci.txt').write_text(ci_msg, encoding='utf-8')

# Commit feature changes (script)
run(['git','add','scripts/update_kpi.py'])
code = run(['git','commit','-F', str(feat_file)])
if code != 0:
    print('No feature commit created or no changes to commit')

# Commit CI change (workflow)
run(['git','add','.github/workflows/update-kpi.yml'])
code2 = run(['git','commit','-F', str(ci_file)])
if code2 != 0:
    print('No CI commit created or no changes to commit')

# Push
ret = run(['git','push'])
if ret != 0:
    print('Push failed; check remote/auth')

# cleanup
try:
    feat_file.unlink()
    ci_file.unlink()
except Exception:
    pass
