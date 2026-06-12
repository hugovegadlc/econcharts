"""Frozen entry point for the econcharts ship.

Forces the Agg backend (no GUI on a locked laptop) and hands off to the CLI, so the
exe behaves exactly like `econcharts ...` on the command line.
"""

import sys

import matplotlib

matplotlib.use("Agg")

from econcharts.cli import main

if __name__ == "__main__":
    sys.exit(main())
