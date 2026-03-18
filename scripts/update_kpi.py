import json
import os
import requests
from collections import defaultdict
from datetime import datetime, timezone

API = "https://api.github.com"
TOKEN = os.environ["GH_TOKEN"]
HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28"
}

CONFIG_FILE = "kpi-repos.json"
README_FILE = "README.md"
OUTPUT_JSON = "kpi-data.json"

START_MARK = "<!-- KPI:START -->"
END_MARK = "<!-- KPI:END -->"


def paginate(url, params=None):
    results = []
    while url:
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
        r.raise_for_status()
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

    if START_MARK in readme and END_MARK in readme:
        pre = readme.split(START_MARK)[0]
        post = readme.split(END_MARK)[1]
        readme = f"{pre}{block}{post}"
    else:
        readme += f"\n\n{block}\n"

    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(readme)


if __name__ == "__main__":
    main()