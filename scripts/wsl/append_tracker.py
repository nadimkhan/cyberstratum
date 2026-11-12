"""Append a section to the work tracker.

The tracker is the running log of what was built and what it produced.
Writing it by hand in an editor is how entries drift out of date, so the
entries are appended from the same run that produced the evidence.
"""

import pathlib
import sys


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: append_tracker.py <path> <section-file>", file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    section = pathlib.Path(sys.argv[2]).read_text()

    existing = path.read_text() if path.exists() else ""
    if section.strip() and section.strip() in existing:
        print(f"already present in {path}")
        return 0

    separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    path.write_text(existing + separator + section.strip() + "\n")
    print(f"appended to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
