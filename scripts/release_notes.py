"""Release notes from the milestone log.

Prints the most recent milestone section of docs/milestones.md — the
release convention is one release per big milestone, so the latest section
IS the changelog. Pass a milestone id (e.g. M28) to select an older one,
or --count N to include the last N sections.

    python scripts/release_notes.py            # latest milestone
    python scripts/release_notes.py M28        # a specific one
    python scripts/release_notes.py --count 2  # the last two
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MILESTONES = Path(__file__).resolve().parent.parent / "docs" / "milestones.md"


def sections(text: str) -> list[tuple[str, str]]:
    """(milestone id, full section text) for every '## M<n> — ...' heading."""
    out: list[tuple[str, str]] = []
    matches = list(re.finditer(r"^## (M\d+)[^\n]*$", text, flags=re.MULTILINE))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((match.group(1), text[match.start():end].rstrip() + "\n"))
    return out


def main(argv: list[str]) -> int:
    all_sections = sections(MILESTONES.read_text())
    if not all_sections:
        print("no milestone sections found", file=sys.stderr)
        return 1

    if argv and argv[0] == "--count":
        picked = [body for _, body in all_sections[-int(argv[1]):]]
    elif argv:
        wanted = argv[0].upper()
        matching = [body for mid, body in all_sections if mid == wanted]
        if not matching:
            print(f"no milestone {wanted} in {MILESTONES}", file=sys.stderr)
            return 1
        picked = matching
    else:
        picked = [all_sections[-1][1]]

    print("\n".join(picked))
    print(
        "---\n\n"
        "Download the bundle for your platform below, unzip, and follow "
        "GETTING-STARTED.txt inside (Docker Desktop + Python 3.11 are the "
        "only prerequisites — the control panel ships prebuilt). "
        "Full milestone history: docs/milestones.md."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
