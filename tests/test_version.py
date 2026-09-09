"""The version the package REPORTS must be the version the project declares.

`econcharts.__version__` is `importlib.metadata.version("econcharts")` — it reads
the metadata of the INSTALLED distribution, not `pyproject.toml`. Bumping the
version therefore does nothing to what `econcharts --version` says until the
package is reinstalled, and nothing anywhere complains.

It drifted for five releases exactly that way: a stale `econcharts-0.3.0.dist-info`
sat in site-packages from an editable install done at v0.3.0, so the CLI answered
`econcharts 0.3.0` while the project was at 0.8.3. It went unnoticed because a
repo-root `econcharts.egg-info/` — a gitignored build artifact — shadowed it for
`import econcharts`, and deleting that artifact was what exposed it.

The fix when this fails is `pip install -e .`, not editing anything.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import econcharts

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_reported_version_matches_pyproject():
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert econcharts.__version__ == declared, (
        f"pyproject declares {declared} but the installed distribution reports "
        f"{econcharts.__version__} - run `pip install -e .` to refresh the metadata "
        f"the CLI's --version reads"
    )
