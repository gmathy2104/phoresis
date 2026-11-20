"""Print the conflict blocks of files, numbered, with a little context. python showconf.py <file> [...]"""

import sys
from pathlib import Path

CONTEXT = 3
for name in sys.argv[1:]:
    lines = Path(name).read_text(encoding="utf-8").split("\n")
    number, i = 0, 0
    while i < len(lines):
        if lines[i].startswith("<<<<<<< "):
            number += 1
            end = next(j for j in range(i, len(lines)) if lines[j].startswith(">>>>>>> "))
            print(f"\n######## {Path(name).name}  block {number}  (lines {i + 1}-{end + 1})")
            for j in range(max(0, i - CONTEXT), min(len(lines), end + CONTEXT + 1)):
                print(f"{j + 1:5}: {lines[j]}")
            i = end
        i += 1
