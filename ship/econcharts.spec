# PyInstaller manifest for the econcharts ship — the canonical record of what gets
# frozen into econcharts.exe / _internal/. Build with `python ship/build.py`, which
# also adds the user-facing files (examples/, manual.html, run.bat) at the bundle root.
#
# What's bundled here:
#   - the econcharts package + its dependency stack (numpy/pandas/scipy/matplotlib/
#     pydantic/openpyxl/python-pptx + a private Python runtime), collected automatically
#   - themes/bbva.yaml          -> _internal/themes/   (the house style, read at runtime)
#   - python-pptx's templates   -> _internal/pptx/...  (needed to write the .pptx deck)
# Excluded: GUI toolkits we never use (Agg backend only).

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve().parent          # repo root (SPECPATH = the ship/ dir)

datas = [(str(ROOT / "themes"), "themes")]
datas += collect_data_files("pptx")             # default.pptx template + friends

a = Analysis(
    [str(ROOT / "ship" / "launch.py")],
    pathex=[str(ROOT)],                          # so `econcharts` resolves from the repo
    binaries=[],
    datas=datas,
    hiddenimports=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,                       # onedir: binaries live in _internal/
    name="econcharts",
    console=True,                                # it's a CLI
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="econcharts", upx=False)
