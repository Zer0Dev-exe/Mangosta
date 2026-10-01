"""Compila mangosta en un único ejecutable con PyInstaller.

    pip install ".[build]"
    python scripts/build.py              # -> dist/mangosta(.exe)
    python scripts/build.py --name X     # nombre del fichero de salida

Lo usa también el workflow de release, así que local y CI compilan igual.
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# PyInstaller no detecta solo estos módulos/ficheros:
COLLECT = [
    "--collect-all", "textual",          # CSS y widgets que Textual carga dinámicamente
    "--collect-data", "mangosta",        # src/mangosta/assets (logo y logotipo)
    "--collect-submodules", "mangosta",
    "--collect-submodules", "dns",       # dnspython: necesario para mongodb+srv://
    "--collect-submodules", "pymongo",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="mangosta", help="nombre del ejecutable (sin extensión)")
    args = parser.parse_args()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile",
        "--name", args.name,
        *COLLECT,
    ]
    if sys.platform == "win32":
        cmd += ["--icon", str(ROOT / "docs" / "mangosta.ico")]
    cmd.append(str(ROOT / "src" / "mangosta" / "__main__.py"))

    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
