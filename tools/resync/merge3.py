"""Three-way merge of gel_analyzer files: Phoresis (ours) x ds-hub at extraction (base) x ds-hub now (theirs).

    python m3.py survey <rel> [...]  one line per file: new / same / merge / conflict (writes nothing)
    python m3.py check <rel> [...]   compare the merge with the file now in the Phoresis working tree
    python m3.py write <rel> [...]   write the merge (conflict markers included) into the working tree

<rel> is a path under gel_analyzer/, or a directory (every text file below it at the pinned ds-hub commit).
Python files: base and theirs get the hub->Phoresis import substitutions and Phoresis's ruff fix + format
first, so only real changes are merged. Other text files are merged as they are. "ours" is read from the
Phoresis commit OURS_REF, "theirs" from the pinned ds-hub commit (its working tree may be pulled meanwhile).
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

HUB = Path(r"C:\Users\gmath\PycharmProjects\PythonProject\ds-hub-django")
PHO = Path(r"C:\Users\gmath\PycharmProjects\PythonProject\phoresis")
BASE_REF = "f9e815cbed6ba7f8979a611152d00de53a3e59ec"  # ds-hub, last commit before the 2026-05-03 extraction
THEIRS_REF = "73a54255b9db77557a07309d17c1ae9f93450265"  # ds-hub, pinned
OURS_REF = "682b27e"  # Phoresis v1.1.1, before this resync
RUFF = str(PHO / ".venv" / "Scripts" / "ruff.exe")
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".md", ".svg", ".txt"}
NL = chr(10)

SUBS = [
    (r"from base\.logging_config import", "from phoresis_core.logging_config import"),
    (r"from base\.celery_utils import", "from phoresis_core.celery_utils import"),
]


def git_show(repo, ref, path):
    done = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{path}"], capture_output=True)
    return done.stdout.decode("utf-8", errors="replace") if done.returncode == 0 else None


def unix(text):
    return text.lstrip(chr(0xFEFF)).replace(chr(13) + NL, NL)


def normalise(text, work, name, is_python):
    text = unix(text)
    if not is_python:
        # Phoresis mounts the app at the site root; the hub under /gel-analyzer/.
        return text.replace("/gel-analyzer/", "/")
    for pattern, replacement in SUBS:
        text = re.sub(pattern, replacement, text)
    target = work / name
    target.write_text(text, encoding="utf-8", newline=NL)
    config = ["--config", str(PHO / "pyproject.toml")]
    subprocess.run([RUFF, "check", *config, "--fix", "--unsafe-fixes", "--quiet", str(target)], capture_output=True)
    subprocess.run([RUFF, "format", *config, "--quiet", str(target)], capture_output=True)
    return target.read_text(encoding="utf-8")


def merge(rel, work):
    """(merged text, conflicts, note)."""
    is_python = rel.endswith(".py")
    theirs_raw = git_show(HUB, THEIRS_REF, f"gel_analyzer/{rel}")
    base_raw = git_show(HUB, BASE_REF, f"gel_analyzer/{rel}")
    ours = git_show(PHO, OURS_REF, f"src/gel_analyzer/{rel}")
    if theirs_raw is None:
        return ours, 0, "gone from ds-hub (kept ours)"
    theirs = normalise(theirs_raw, work, "theirs.py", is_python)
    if ours is None:
        note = "new in ds-hub" if base_raw is None else "deleted in Phoresis, changed in ds-hub"
        return theirs, 0, note
    ours = unix(ours)
    if base_raw is None:
        if ours == theirs:
            return ours, 0, "added on both sides, identical"
        base, note = "", "added on both sides (no base)"
    else:
        base, note = normalise(base_raw, work, "base.py", is_python), ""
        if base == ours:
            return theirs, 0, "unchanged in Phoresis (took ds-hub)"
        if base == theirs:
            return ours, 0, "unchanged in ds-hub (kept ours)"
    (work / "ours.py").write_text(ours, encoding="utf-8", newline=NL)
    (work / "base.py").write_text(base, encoding="utf-8", newline=NL)
    (work / "theirs.py").write_text(theirs, encoding="utf-8", newline=NL)
    done = subprocess.run(
        ["git", "merge-file", "-p", "-L", "phoresis", "-L", "base", "-L", "ds-hub", "ours.py", "base.py", "theirs.py"],
        cwd=work,
        capture_output=True,
    )
    return done.stdout.decode("utf-8", errors="replace"), max(done.returncode, 0), note


def expand(args):
    out = []
    for arg in args:
        listed = (
            subprocess.run(
                ["git", "-C", str(HUB), "ls-tree", "-r", "--name-only", THEIRS_REF, "--", f"gel_analyzer/{arg}"],
                capture_output=True,
            )
            .stdout.decode("utf-8")
            .splitlines()
        )
        files = [f[len("gel_analyzer/") :] for f in listed if f and Path(f).suffix.lower() in TEXT_SUFFIXES]
        out += sorted(files) if files else [arg]
    return out


def read_current(path):
    return unix(path.read_text(encoding="utf-8", errors="replace")) if path.exists() else None


def main():
    mode, rels = sys.argv[1], expand(sys.argv[2:])
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for rel in rels:
            merged, conflicts, note = merge(rel, work)
            current_path = PHO / "src" / "gel_analyzer" / rel
            current = read_current(current_path)
            if mode == "survey":
                if current is None:
                    state = "new"
                elif current == merged:
                    state = "same"
                else:
                    state = "conflict" if conflicts else "merge"
                print(f"{state:<9}{conflicts:>3}  {rel}  {note}")
            elif mode == "write":
                current_path.parent.mkdir(parents=True, exist_ok=True)
                current_path.write_text(merged, encoding="utf-8", newline=NL)
                print(f"{'CONFLICT x' + str(conflicts) if conflicts else 'ok':<14} {rel}  {note}")
            elif current is None:
                print(f"ABSENT         {rel}  {note}")
            elif current == merged:
                print(f"same           {rel}  {note}")
            else:
                (work / "current.py").write_text(current, encoding="utf-8", newline=NL)
                (work / "merged.py").write_text(merged, encoding="utf-8", newline=NL)
                diff = subprocess.run(
                    ["git", "diff", "--no-index", "-U1", "--", "current.py", "merged.py"], cwd=work, capture_output=True
                ).stdout.decode("utf-8", errors="replace")
                body = NL.join(diff.splitlines()[4:])
                print(f"DIFFERS conflicts={conflicts:<3} {rel}  {note}{NL}{body}{NL}")


main()
