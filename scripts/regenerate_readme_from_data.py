import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime


def load_module_from_path(path):
    spec = importlib.util.spec_from_file_location("update_kpi_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None):
    p = argparse.ArgumentParser(description="Regenerar README usando kpi-data.json sin llamar a la API")
    p.add_argument("--input", default="kpi-data.json", help="Archivo JSON de KPI generado previamente")
    p.add_argument("--readme", default="README.md", help="Archivo README a actualizar")
    args = p.parse_args(argv or sys.argv[1:])

    if not os.path.exists(args.input):
        print(f"Error: no existe {args.input}")
        sys.exit(2)

    # Cargar el módulo principal para reutilizar build_report y marcas
    mod_path = os.path.join(os.path.dirname(__file__), "update_kpi.py")
    if not os.path.exists(mod_path):
        print(f"Error: no se encontró {mod_path}")
        sys.exit(2)

    mod = load_module_from_path(mod_path)

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Asegurar que la estructura mínima esté presente
    if "participants" not in data:
        print("Error: el JSON no contiene 'participants'. Abortando.")
        sys.exit(2)

    report = mod.build_report(data)

    start = getattr(mod, "START_MARK", "<!-- KPI:START -->")
    end = getattr(mod, "END_MARK", "<!-- KPI:END -->")

    if os.path.exists(args.readme):
        with open(args.readme, "r", encoding="utf-8") as f:
            readme = f.read()
    else:
        readme = "# FarmaExpres\n\n"

    block = f"{start}\n{report}\n{end}"

    if start in readme and end in readme:
        pre = readme.split(start)[0]
        post = readme.split(end)[1]
        new_readme = f"{pre}{post}"
    else:
        new_readme = readme.rstrip() + "\n\n"

    new_readme = new_readme.rstrip() + "\n\n" + block + "\n"

    with open(args.readme, "w", encoding="utf-8") as f:
        f.write(new_readme)

    print(f"README actualizado a partir de {args.input} en {datetime.utcnow().isoformat()}Z")


if __name__ == "__main__":
    main()
