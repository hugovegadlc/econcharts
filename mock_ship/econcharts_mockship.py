"""Mock ship: a self-contained execution test for a locked-down work laptop.

Frozen with PyInstaller into a single .exe (no Python, no install needed), this
exercises the exact heavy stack econcharts would ship with — numpy / pandas /
matplotlib — and renders a tiny chart, proving the frozen scientific stack both
*runs* (unsigned exe permitted) and *works* on the target machine.
"""

from __future__ import annotations

import os
import platform
import sys


def main() -> None:
    print("=" * 56)
    print("  econcharts — mock ship / execution test")
    print("=" * 56)
    print(f"  Python    : {sys.version.split()[0]}")
    print(f"  Platform  : {platform.platform()}")
    print(f"  Frozen    : {getattr(sys, 'frozen', False)}")
    print(f"  Exe path  : {sys.executable}")
    print("-" * 56)

    try:
        import matplotlib
        import numpy
        import pandas

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        print(f"  numpy     : {numpy.__version__}")
        print(f"  pandas    : {pandas.__version__}")
        print(f"  matplotlib: {matplotlib.__version__}")

        fig, ax = plt.subplots(figsize=(4.0, 3.0))
        ax.plot([1, 2, 3, 4, 5], [1, 4, 2, 5, 3], color="#001391", linewidth=2)
        ax.set_title("mock ship OK")
        out = os.path.join(os.path.expanduser("~"), "econcharts_mockship_test.png")
        fig.savefig(out, dpi=120)

        print("-" * 56)
        print(f"  Rendered a test chart -> {out}")
        print("  SUCCESS: the frozen stack runs on this machine.")
    except Exception as e:  # noqa: BLE001 — this is a diagnostic harness
        print("-" * 56)
        print(f"  FAILED while importing/rendering: {e!r}")

    print("=" * 56)
    try:
        input("Press Enter to close... ")
    except EOFError:
        pass


if __name__ == "__main__":
    main()
