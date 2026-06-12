"""Build the econcharts ship — a self-contained Windows bundle (no Python needed).

This is the human-readable manifest of the WHOLE bundle: it freezes the app from
`econcharts.spec`, then lays the user-facing files at the bundle root, then zips it.

Run from a venv that has the deps + PyInstaller:

    python -m venv ship/venv
    ship/venv/Scripts/python -m pip install . pyinstaller
    ship/venv/Scripts/python ship/build.py

Note: build from a clean python.org venv when possible. On the anaconda-based dev
machine PyInstaller also needs `…\anaconda3\Library\bin` on PATH (for ffi-8.dll).

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
