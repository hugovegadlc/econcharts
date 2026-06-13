"""`econcharts` command line.

  econcharts build <batch.yaml> [--only id1,id2] [-o DIR] [--force]
  econcharts render <spec.yaml> -o <out.png> [--size NAME] [--backend NAME]

`build` renders a batch document fail-soft (one bad chart doesn't stop the rest) and,
if any target files already exist, asks ONCE before overwriting. `render` is the
single-chart shortcut. Exit code is non-zero if anything failed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


def main(argv: Optional[list[str]] = None) -> int:
    from econcharts import __version__

    parser = argparse.ArgumentParser(prog="econcharts", description="Render economic charts from specs.")
    parser.add_argument("--version", action="version", version=f"econcharts {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    b = sub.add_parser("build", help="render a batch document to a folder of figures")
    b.add_argument("batch", help="path to the batch YAML")
    b.add_argument("--only", help="comma-separated chart ids to render (overrides header `render`)")
    b.add_argument("-o", "--output", help="output directory (overrides the batch `output_dir`)")
    b.add_argument("-f", "--force", action="store_true", help="overwrite existing figures without asking")

    r = sub.add_parser("render", help="render a single chart spec to one file")
    r.add_argument("spec", help="path to the chart spec YAML")
    r.add_argument("-o", "--output", required=True, help="output file (backend inferred from suffix)")
    r.add_argument("--size", help="named export size (e.g. slides_full)")
    r.add_argument("--backend", help="png | svg | pdf (default: from the output suffix)")

    args = parser.parse_args(argv)
    if args.cmd == "build":
        return _build(args)
    if args.cmd == "render":
        return _render(args)
    parser.print_help()
    return 1


def _build(args) -> int:
    from econcharts.batch import Batch, run_jobs
    from econcharts.errors import EconchartsError

    try:
        batch = Batch.from_yaml(args.batch)
    except (EconchartsError, OSError) as e:
        print(f"econcharts: {e}", file=sys.stderr)
        return 2

    only = [s.strip() for s in args.only.split(",")] if args.only else None
    jobs = batch.jobs(only=only)
    if args.output:
        out = Path(args.output)
        for j in jobs:
            j.output_path = out / j.output_path.name
    if not jobs:
        print("econcharts: no charts selected.")
        return 0

    existing = [j for j in jobs if j.output_path.exists()]
    if existing and not args.force:
        where = jobs[0].output_path.parent
        print(f"{len(existing)} of {len(jobs)} figure(s) already exist in {where}.")
        try:
            answer = input("Overwrite them? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("Aborted; nothing written.")
            return 1

    results = run_jobs(jobs, batch.resolved_data_root())
    failed = [r for r in results if not r.ok]
    for r in results:
        if r.ok:
            print(f"  [ ok ] {r.id} -> {r.output_path.name}")
        else:
            print(f"  [FAIL] {r.id}: {r.error.splitlines()[0]}", file=sys.stderr)

    # Assemble the successful PNGs into a deck named after the batch (2 per slide,
    # each placed at its true export size). Use the physical mm from the render.
    deck_items = [(r.output_path, r.size_mm) for r, j in zip(results, jobs)
                  if r.ok and r.output_path.suffix.lower() == ".png"]
    if deck_items:
        from econcharts.deck import build_deck
        deck = build_deck(deck_items, deck_items[0][0].parent / f"{Path(args.batch).stem}.pptx")
        print(f"  deck  -> {deck.name}")

    print(f"\n{len(results) - len(failed)} ok, {len(failed)} failed.")
    return 1 if failed else 0


def _render(args) -> int:
    import matplotlib.pyplot as plt

    from econcharts.errors import EconchartsError
    from econcharts.render import render, save
    from econcharts.spec import Spec

    spec_path = Path(args.spec)
    try:
        spec = Spec.from_yaml(spec_path)
        kwargs = {"data_root": spec_path.resolve().parent}
        if args.size:
            kwargs["size"] = args.size
        fig = render(spec, **kwargs)
        save(fig, args.output, backend=args.backend)
        plt.close(fig)
    except (EconchartsError, OSError) as e:
        print(f"econcharts: {e}", file=sys.stderr)
        return 1
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
