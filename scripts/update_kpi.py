import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import requests
import re

API = "https://api.github.com"

START_MARK = "<!-- KPI:START -->"
END_MARK = "<!-- KPI:END -->"


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s %(levelname)s: %(message)s", level=level
    )


def paginate(url, headers, params=None):
    results = []
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            if r.status_code == 403 and "rate limit" in (r.text or "").lower():
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


def list_branches(api, full_repo, headers):
    url = f"{api}/repos/{full_repo}/branches"
    data = paginate(url, headers=headers, params={"per_page": 100})
    return [b["name"] for b in data]


def list_commits(api, full_repo, branch, headers):
    url = f"{api}/repos/{full_repo}/commits"
    return paginate(url, headers=headers, params={"sha": branch, "per_page": 100})


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
    key = (author_key or "").lower()
    if "[bot]" in key:
        return True
    author = commit.get("author") or {}
    if isinstance(author, dict) and author.get("type", "").lower() == "bot":
        return True
    return False


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def resolve_repo_branches(api, full_repo, headers):
    """Intentar obtener ramas del repo. Si falla, probar variantes comunes.

    Devuelve la lista de branches o lanza la excepción original si no se puede.
    """
    try:
        return list_branches(api, full_repo, headers)
    except Exception:
        # Probar reemplazando _ por - y viceversa
        alt = None
        if "_" in full_repo:
            alt = full_repo.replace("_", "-")
        elif "-" in full_repo:
            alt = full_repo.replace("-", "_")

        if alt:
            try:
                branches = list_branches(api, alt, headers)
                logging.info("Resolví %s a %s", full_repo, alt)
                return branches
            except Exception:
                pass
        # Re-lanzar la excepción original
        raise


def discover_repos_from_files(root_dir="."):
    """Buscar enlaces a repositorios GitHub en archivos de texto del árbol de trabajo.

    Devuelve una lista de strings en formato 'owner/repo' encontrados. Maneja URLs
    con sufijo `.git`, con rutas adicionales y con formatos SSH (github.com:owner/repo).
    """
    # Captura owner y repo aun cuando la URL tenga ruta adicional o termine en .git
    pattern = re.compile(r"github\.com[:/]+([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.IGNORECASE)
    exts = (".md", ".txt", ".rst", ".json", ".yml", ".yaml", ".py")
    found = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for fname in filenames:
            if not fname.lower().endswith(exts):
                continue
            path = os.path.join(dirpath, fname)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except Exception:
                continue

            for owner, repo in pattern.findall(text):
                # Normalizar: quitar sufijo .git si existe y strip de barras
                repo = repo.rstrip("/\n\r\t")
                if repo.lower().endswith(".git"):
                    repo = repo[:-4]
                repo_key = f"{owner}/{repo}"
                repo_key_norm = repo_key.strip()
                if repo_key_norm and repo_key_norm not in found:
                    found.append(repo_key_norm)

    return found


def build_report(data):
    rows = sorted(
        data["participants"].items(), key=lambda x: x[1]["commits"], reverse=True
    )

    total = sum(v["commits"] for _, v in rows)

    table = [
        "| Integrante | Commits únicos | Participación | Repos | Ramas |",
        "|---|---:|---:|---:|---:|",
    ]

    pie_lines = [
        "```mermaid",
        "pie showData",
        '    title Participación del grupo de trabajo',
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
        "```",
    ]

    theme_vars = {}
    # Paleta de colores más visibles para las porciones (evita tonos oscuros)
    palette = ["#ff6f61", "#3498db", "#f1c40f", "#1abc9c", "#e67e22", "#9b59b6"]
    for idx, name in enumerate(bar_names):
        theme_vars[f"pie{idx+1}"] = palette[idx % len(palette)]

    if theme_vars:
        import json as _json

        # Añadir variables para hacer las etiquetas más visibles
        label_vars = {
            "pieLabelColor": "#000000",
            "pieLabelFontSize": "24px",
            "pieLabelFontWeight": "700"
        }
        merged = {**theme_vars, **label_vars}
        init_payload = _json.dumps({"themeVariables": merged}, ensure_ascii=False)
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


def run(cfg_path, output_json, readme_file, token, dry_run=False):
    cfg = load_config(cfg_path)
    team = cfg.get("team", {})
    repos = cfg["repos"]
    aliases = cfg.get("aliases", {})

    # Intentar descubrir automáticamente repositorios añadidos como enlaces
    try:
        discovered = discover_repos_from_files(os.getcwd())
        if discovered:
            logging.info("Repositorios descubiertos en archivos: %s", discovered)
            # agregar los descubiertos que no estén ya en la configuración, manteniendo el orden
            new_repos = [r for r in discovered if r not in repos]
            if new_repos:
                repos = repos + new_repos
                # Persistir la configuración actualizada para que sea automático la próxima vez
                try:
                    cfg_obj = load_config(cfg_path)
                    cfg_obj.setdefault("repos", repos)
                    save_config(cfg_path, cfg_obj)
                    logging.info("Guardada configuración actualizada en %s", cfg_path)
                except Exception:
                    logging.debug("No se pudo guardar kpi-repos.json automáticamente", exc_info=True)
    except Exception:
        logging.debug("No se pudieron descubrir repositorios automáticos", exc_info=True)

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    seen_shas = set()
    participants = defaultdict(lambda: {
        "commits": 0,
        "repos": set(),
        "branches": set(),
        "display_name": "",
    })

    repo_summary = {}

    for full_repo in repos:
        try:
            logging.info("Listing branches for %s", full_repo)
            branches = resolve_repo_branches(API, full_repo, headers)
            repo_summary[full_repo] = {"branches": len(branches), "commits": 0}

            for branch in branches:
                logging.debug("Listing commits for %s@%s", full_repo, branch)
                commits = list_commits(API, full_repo, branch, headers)
                
                for commit in commits:
                    sha = commit["sha"]
                    if sha in seen_shas:
                        continue

                    seen_shas.add(sha)
                    author_key = normalize_author(commit)
                    author_key = aliases.get(author_key, author_key)

                    if is_bot(author_key, commit):
                        continue

                    participants[author_key]["commits"] += 1
                    participants[author_key]["repos"].add(full_repo)
                    participants[author_key]["branches"].add(f"{full_repo}:{branch}")
                    participants[author_key]["display_name"] = team.get(author_key, author_key)
                    repo_summary[full_repo]["commits"] += 1
        except Exception as e:
            logging.exception("Error procesando %s: %s", full_repo, e)
            # continuar con el siguiente repo en caso de error
            continue
    # end for repos

    serializable = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_unique_commits": len(seen_shas),
        "participants": {
            k: {
                "display_name": v["display_name"] or k,
                "commits": v["commits"],
                "repos": sorted(v["repos"]),
                "branches": sorted(v["branches"]),
            }
            for k, v in participants.items()
        },
        "repos": repo_summary,
    }

    if not dry_run:
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)
        logging.info("Wrote %s", output_json)
    else:
        logging.info("Dry run: not writing %s", output_json)

    report = build_report(serializable)

    if not dry_run and readme_file and os.path.exists(readme_file):
        with open(readme_file, "r", encoding="utf-8") as f:
            readme = f.read()
    else:
        readme = "# FarmaExpres\n\n"

    block = f"{START_MARK}\n{report}\n{END_MARK}"

    if START_MARK in readme and END_MARK in readme:
        pre = readme.split(START_MARK)[0]
        post = readme.split(END_MARK)[1]
        readme = f"{pre}{post}"

    readme = readme.rstrip() + "\n\n" + block + "\n"

    if not dry_run and readme_file:
        with open(readme_file, "w", encoding="utf-8") as f:
            f.write(readme)
        logging.info("Updated %s", readme_file)
    else:
        logging.info("Dry run: not updating README")


def parse_args(argv):
    p = argparse.ArgumentParser(description="Genera KPIs de commits y actualiza README")
    p.add_argument("--config", default="kpi-repos.json", help="Ruta al archivo de configuración JSON")
    p.add_argument("--output", default="kpi-data.json", help="Archivo JSON de salida")
    p.add_argument("--readme", default="README.md", help="Archivo README a actualizar")
    p.add_argument("--token", default=os.environ.get("GH_TOKEN"), help="Token de GitHub (o usar GH_TOKEN env)")
    p.add_argument("--dry-run", action="store_true", help="No escribir archivos, solo simular")
    p.add_argument("--no-readme", action="store_true", help="No actualizar README.md")
    p.add_argument("--verbose", action="store_true", help="Modo verboso (debug)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    setup_logging(args.verbose)
    try:
        readme = None if args.no_readme else args.readme
        run(args.config, args.output, readme, args.token, dry_run=args.dry_run)
    except Exception as e:
        logging.exception("Error ejecutando update_kpi: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
