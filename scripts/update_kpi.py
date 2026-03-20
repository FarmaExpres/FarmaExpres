import json
import os
import requests
from collections import defaultdict
from datetime import datetime, timezone

API = "https://api.github.com"
# Permitir ejecutar sin token (usar solicitudes no autenticadas, sujetas a límites de rate)
TOKEN = os.environ.get("GH_TOKEN")
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

CONFIG_FILE = "kpi-repos.json"
README_FILE = "README.md"
OUTPUT_JSON = "kpi-data.json"

START_MARK = "<!-- KPI:START -->"
END_MARK = "<!-- KPI:END -->"


def paginate(url, params=None):
    results = []
    while url:
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            # Añadir mensaje claro si se excede el rate limit sin token
            if r.status_code == 403 and "rate limit" in r.text.lower():
                raise RuntimeError(
                    "Rate limit alcanzado. Establece GH_TOKEN o intenta más tarde."
                ) from e
            raise
        data = r.json()
        if isinstance(data, list):
            results.extend(data)
        else:
            return data
        url = r.links.get("next", {}).get("url")
        params = None
    return results


def list_branches(full_repo):
    url = f"{API}/repos/{full_repo}/branches"
    data = paginate(url, params={"per_page": 100})
    return [b["name"] for b in data]


def list_commits(full_repo, branch):
    url = f"{API}/repos/{full_repo}/commits"
    return paginate(url, params={"sha": branch, "per_page": 100})


def normalize_author(commit):
    author = commit.get("author")
    if author and author.get("login"):
        return author["login"]

    commit_author = commit.get("commit", {}).get("author", {})
    email = (commit_author.get("email") or "").strip().lower()
    name = (commit_author.get("name") or "").strip()

    if email:
        return email
    if name:
        return name
    return "Sin identificar"


def is_bot(author_key, commit):
    """Detecta autores que son bots para excluirlos del reporte."""
    key = (author_key or "").lower()
    if "[bot]" in key:
        return True
    author = commit.get("author") or {}
    if isinstance(author, dict) and author.get("type", "").lower() == "bot":
        return True
    return False


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_report(data):
    rows = sorted(
        data["participants"].items(),
        key=lambda x: x[1]["commits"],
        reverse=True
    )

    total = sum(v["commits"] for _, v in rows)

    table = [
        "| Integrante | Commits únicos | Participación | Repos | Ramas |",
        "|---|---:|---:|---:|---:|"
    ]

    pie_lines = [
        "```mermaid",
        "pie showData",
        '    title Participación del grupo de trabajo'
    ]

    bar_names = []
    bar_values = []

    for _, info in rows:
        pct = (info["commits"] / total * 100) if total else 0
        display = info["display_name"]
        table.append(
            f"| {display} | {info['commits']} | {pct:.2f}% | {len(info['repos'])} | {len(info['branches'])} |"
        )
        pie_lines.append(f'    "{display}" : {info["commits"]}')
        bar_names.append(display)
        bar_values.append(str(info["commits"]))

    pie_lines.append("```")
    y_max = max([1] + [int(v) for v in bar_values])
    x_labels = ", ".join([f'"{n}"' for n in bar_names])

    bar_lines = [
        "```mermaid",
        "xychart-beta",
        '    title "Participación del grupo de trabajo"',
        f"    x-axis [{x_labels}]",
        f'    y-axis "Commits únicos" 0 --> {y_max}',
        f"    bar [{', '.join(bar_values)}]",
        "```"
    ]

    # Asignar color específico a la porción de la torta para un integrante concreto
    # Mermaid permite definir variables de tema 'pie1', 'pie2', ... que se aplican
    # a las porciones en el orden en que aparecen. Aquí buscamos a
    # "José Leonardo Vargas" y, si está presente, le damos un color más visible.
    theme_vars = {}
    target_name = "José Leonardo Vargas"
    for idx, name in enumerate(bar_names):
        if name == target_name:
            theme_vars[f"pie{idx+1}"] = "#00b3b3"  # teal / cian distintivo

    if theme_vars:
        # Insertar la directiva %%{init: {...}}%% justo después de la apertura del bloque mermaid
        # Construimos el JSON usando json.dumps para escapar correctamente las comillas.
        init_payload = json.dumps({"themeVariables": theme_vars}, ensure_ascii=False)
        pie_lines.insert(1, f"%%{{init: {init_payload}}}%%")

    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    report = f"""
## KPI de participación del grupo de trabajo

**Fórmula:**  
Participación (%) = (commits únicos del integrante / commits únicos totales del ecosistema) × 100

**Última actualización:** {updated_at}

**Cobertura del KPI:** todos los commits detectados en todas las ramas de todos los repositorios configurados, deduplicados por SHA.

### Tabla consolidada

{chr(10).join(table)}

### Gráfico de torta

{chr(10).join(pie_lines)}

### Gráfico de barras

{chr(10).join(bar_lines)}
""".strip()

    return report


def main():
    cfg = load_config()
    team = cfg.get("team", {})
    repos = cfg["repos"]
    aliases = cfg.get("aliases", {})

    seen_shas = set()
    participants = defaultdict(lambda: {
        "commits": 0,
        "repos": set(),
        "branches": set(),
        "display_name": ""
    })

    repo_summary = {}

    for full_repo in repos:
        branches = list_branches(full_repo)
        repo_summary[full_repo] = {"branches": len(branches), "commits": 0}

        for branch in branches:
            commits = list_commits(full_repo, branch)

            for commit in commits:
                sha = commit["sha"]
                if sha in seen_shas:
                    continue

                seen_shas.add(sha)
                author_key = normalize_author(commit)
                # Resolver alias (p. ej. emails o identificadores alternos)
                author_key = aliases.get(author_key, author_key)

                # Excluir bots (ej. github-actions[bot], dependabot[bot])
                if is_bot(author_key, commit):
                    continue

                participants[author_key]["commits"] += 1
                participants[author_key]["repos"].add(full_repo)
                participants[author_key]["branches"].add(f"{full_repo}:{branch}")
                participants[author_key]["display_name"] = team.get(author_key, author_key)
                repo_summary[full_repo]["commits"] += 1

    serializable = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_unique_commits": len(seen_shas),
        "participants": {
            k: {
                "display_name": v["display_name"] or k,
                "commits": v["commits"],
                "repos": sorted(v["repos"]),
                "branches": sorted(v["branches"])
            }
            for k, v in participants.items()
        },
        "repos": repo_summary
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)

    if os.path.exists(README_FILE):
        with open(README_FILE, "r", encoding="utf-8") as f:
            readme = f.read()
    else:
        readme = "# FarmaExpres\n\n"

    block = f"{START_MARK}\n{build_report(serializable)}\n{END_MARK}"

    # Remove any existing KPI block anywhere in the file, then append it at the end.
    if START_MARK in readme and END_MARK in readme:
        pre = readme.split(START_MARK)[0]
        post = readme.split(END_MARK)[1]
        readme = f"{pre}{post}"

    # Ensure the KPI block is placed at the end of the README
    readme = readme.rstrip() + "\n\n" + block + "\n"

    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(readme)


if __name__ == "__main__":
    main()