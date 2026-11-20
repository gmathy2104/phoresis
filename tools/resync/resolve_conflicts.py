"""Resolve the conflict blocks git merge-file left in one file.

    python resolve_conflicts.py <file> <default: ours|theirs|both> [<n>=<ours|theirs|both> ...]

Blocks are numbered from 1 in file order (see show_conflicts.py). ``ours`` is the Phoresis side,
``theirs`` the ds-hub side, ``both`` keeps Phoresis's lines then ds-hub's.
"""

import sys
from pathlib import Path

path, default = Path(sys.argv[1]), sys.argv[2]
overrides = {}
for arg in sys.argv[3:]:
    number, choice = arg.split("=")
    overrides[int(number)] = choice

out, count, side, ours, theirs = [], 0, None, [], []
for line in path.read_text(encoding="utf-8").split("\n"):
    if line.startswith("<<<<<<< phoresis"):
        side, ours, theirs = "ours", [], []
        count += 1
    elif line.startswith("=======") and side == "ours":
        side = "theirs"
    elif line.startswith(">>>>>>> ds-hub"):
        out += {"ours": ours, "theirs": theirs, "both": ours + theirs}[overrides.get(count, default)]
        side = None
    elif side == "ours":
        ours.append(line)
    elif side == "theirs":
        theirs.append(line)
    else:
        out.append(line)
path.write_text("\n".join(out), encoding="utf-8", newline="\n")
print(f"{path}: {count} block(s) resolved")
