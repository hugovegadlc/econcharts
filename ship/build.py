"""Build the econcharts ship — a self-contained Windows bundle (no Python needed).

This is the human-readable manifest of the WHOLE bundle: it freezes the app from
`econcharts.spec`, then lays the user-facing files at the bundle root, then zips it.

Run from the project .venv (python.org Python, which carries PyInstaller via
the dev extras):

    .venv/Scripts/python ship/build.py

PyInstaller bundles only what the app imports, so the dev tools in .venv
(pytest, pytest-mpl) stay out of the exe. An earlier version of this note said
to build from a separate ship/venv and to put Anaconda's Library/bin on PATH;
both predate the move off Anaconda and no longer apply.

Result:
    ship/dist/econcharts/        the bundle
      econcharts.exe             the CLI (Agg backend, no GUI)
      _internal/                 the frozen Python + deps + themes/ + pptx template
      examples/                  gallery.yaml + datos.xlsx  (edit these)
      manual.html                the full user manual
      run.bat                    double-click → build the example
    ~/econcharts_ship.zip        the same, zipped for transfer
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIP = ROOT / "ship"
DIST = SHIP / "dist" / "econcharts"

# Files placed at the bundle ROOT (beside the exe), not frozen into _internal.
EXAMPLES = ["gallery.yaml", "datos.xlsx"]
DOCS = ["manual.html"]

RUN_BAT = (
    "@echo off\r\n"
    "REM econcharts - render the example batch. Double-click to run.\r\n"
    "REM Figures + a PowerPoint deck land in examples\\_gallery\\.\r\n"
    "REM Edit examples\\gallery.yaml (and drop your own .xlsx in examples\\) to make your own.\r\n"
    "REM See manual.html for the full guide.\r\n"
    'cd /d "%~dp0"\r\n'
    "econcharts.exe build examples\\gallery.yaml\r\n"
    "echo.\r\n"
    "pause\r\n"
)


def main() -> None:
    # 1. Freeze the app from the checked-in spec.
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm",
         "--distpath", str(SHIP / "dist"), "--workpath", str(SHIP / "build"),
         str(SHIP / "econcharts.spec")],
        check=True,
    )

    # 2. User-facing files at the bundle root.
    (DIST / "examples").mkdir(parents=True, exist_ok=True)
    for f in EXAMPLES:
        shutil.copy(ROOT / "examples" / f, DIST / "examples" / f)
    for f in DOCS:
        shutil.copy(ROOT / f, DIST / f)
    (DIST / "run.bat").write_text(RUN_BAT, encoding="ascii")

    # 3. Zip the bundle for transfer.
    out = Path.home() / "econcharts_ship.zip"
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(DIST.rglob("*")):
            z.write(p, p.relative_to(DIST))

    print(f"\nbundle: {DIST}")
    print(f"zip:    {out}  ({out.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
