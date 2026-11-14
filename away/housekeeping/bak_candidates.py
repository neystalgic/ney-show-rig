#!/usr/bin/env python3
"""Housekeeping: list old .bak-* files whose exact content is already saved in git.

What it does (read-only -- it never moves, edits or deletes anything):
  1. Finds every "<file>.bak-<date>" in the repo (skips .git, away/ and anything secret-looking).
  2. Works out how old each backup is: the date in its name (e.g. "nov03b" -> Nov 3),
     or the file's modified time if the name has no readable date.
  3. Hashes the backup the same way git would and checks whether that exact content
     was ever committed (any branch, any path). If yes, the backup adds nothing git
     doesn't already have, so it is a "candidate" to tidy away.
  4. Writes a plain-text report (candidates.txt) next to this script, plus
     candidates_paths.txt (one path per line) for the optional move step.

Usage:  python3 away/housekeeping/bak_candidates.py [--days 7] [--out FILE] [--repo DIR]
"""
import argparse
import datetime as dt
import os
import re
import subprocess

MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1)}
BAK_RE = re.compile(r"^(?P<orig>.+)\.bak-(?P<tag>[A-Za-z0-9_-]+)$")
TAG_DATE_RE = re.compile(r"^(?P<mon>[a-z]{3})(?P<day>\d{1,2})[a-z]?$", re.I)
SKIP_DIRS = {".git", "away", "__pycache__", "node_modules", "_to_delete"}
SECRET_WORDS = ("hue_config", "token", "secret", "password", "ney_secrets")


def git(repo, *args):
    """Run a read-only git command and return its text output."""
    return subprocess.run(["git", "-C", repo] + list(args), check=True,
                          capture_output=True, text=True).stdout


def tag_date(tag, today):
    """'nov03b' -> date(2026, 11, 3). A month later than today means last year. None if unreadable."""
    m = TAG_DATE_RE.match(tag)
    if not m or m.group("mon").lower() not in MONTHS:
        return None
    month, day = MONTHS[m.group("mon").lower()], int(m.group("day"))
    year = today.year if month <= today.month else today.year - 1
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def find_baks(repo):
    """Yield repo-relative paths of every *.bak-* file outside skipped folders."""
    for root, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if BAK_RE.match(name):
                yield os.path.relpath(os.path.join(root, name), repo)


def blob_history(repo):
    """Map every blob sha ever committed -> (short commit, date, path) of its FIRST appearance."""
    out = git(repo, "log", "--all", "--reverse", "--root", "--raw", "--no-abbrev",
              "--no-renames", "--format=C %h %ad", "--date=short")
    seen, commit = {}, ("?", "?")
    for line in out.splitlines():
        if line.startswith("C "):
            _, short, date = line.split(" ", 2)
            commit = (short, date)
        elif line.startswith(":"):
            meta, path = line.split("\t", 1)
            sha = meta.split()[3]
            if set(sha) != {"0"} and sha not in seen:
                seen[sha] = (commit[0][:8], commit[1], path)
    return seen


def hash_like_git(repo, rel_bak, rel_orig):
    """Hash the backup as if it were the original file (same git filters/attributes)."""
    return git(repo, "hash-object", "--path=" + rel_orig, rel_bak).strip()


def build_report(repo, days=7, today=None):
    """Return (candidates, kept, too_new, skipped) lists of dicts."""
    today = today or dt.date.today()
    history = blob_history(repo)
    candidates, kept, too_new, skipped = [], [], [], []
    for rel in find_baks(repo):
        if any(w in rel.lower() for w in SECRET_WORDS):
            skipped.append({"path": rel})
            continue
        m = BAK_RE.match(os.path.basename(rel))
        rel_orig = os.path.join(os.path.dirname(rel), m.group("orig"))
        when = tag_date(m.group("tag"), today)
        source = "name"
        if when is None:
            when = dt.date.fromtimestamp(os.path.getmtime(os.path.join(repo, rel)))
            source = "file time"
        item = {"path": rel, "date": when, "date_from": source, "age": (today - when).days,
                "size": os.path.getsize(os.path.join(repo, rel))}
        if item["age"] <= days:
            too_new.append(item)
            continue
        sha = hash_like_git(repo, rel, rel_orig)
        if sha in history:
            item["commit"], item["commit_date"], item["git_path"] = history[sha]
            candidates.append(item)
        else:
            kept.append(item)
    return candidates, kept, too_new, skipped


def format_report(candidates, kept, too_new, skipped, days, today):
    """Plain-English text report."""
    lines = [
        "HOUSEKEEPING -- old .bak-* files already saved in git (LIST ONLY: nothing was moved)",
        "=" * 82,
        f"Made {today.isoformat()} by away/housekeeping/bak_candidates.py. Older than {days} days =",
        f"dated before {(today - dt.timedelta(days=days)).isoformat()}. 'In git' = the backup's exact",
        "content was committed at some point, so git can always give it back.",
        "",
        f"CANDIDATES ({len(candidates)} files, {sum(c['size'] for c in candidates) / 1024:.0f} KB) -- safe to move to _to_delete/:",
    ]
    for c in candidates:
        same = "" if c["git_path"] == c["path"].rsplit(".bak-", 1)[0] else f" as {c['git_path']}"
        lines.append(f"  {c['path']}  | {c['date']} ({c['date_from']}) | in git: {c['commit']} "
                     f"{c['commit_date']}{same}")
    lines += ["", f"KEEP -- old but NOT in git ({len(kept)}): these hold the only copy of that version:"]
    lines += [f"  {k['path']}  | {k['date']} ({k['date_from']})" for k in kept] or ["  (none)"]
    lines += ["", f"TOO NEW to judge yet ({len(too_new)}, {days} days or younger): left alone."]
    if skipped:
        lines += ["", f"SKIPPED (secret-looking names, never opened): {len(skipped)}"]
        lines += [f"  {s['path']}" for s in skipped]
    return "\n".join(lines) + "\n"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.abspath(os.path.join(here, "..", "..")))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default=os.path.join(here, "candidates.txt"))
    a = ap.parse_args()
    today = dt.date.today()
    parts = build_report(a.repo, a.days, today)
    with open(a.out, "w") as f:
        f.write(format_report(*parts, a.days, today))
    # One path per line, for the optional move-to-_to_delete step in DEPLOY.txt.
    with open(os.path.splitext(a.out)[0] + "_paths.txt", "w") as f:
        f.write("".join(c["path"] + "\n" for c in parts[0]))
    print(f"{len(parts[0])} candidates, {len(parts[1])} keep, {len(parts[2])} too new -> {a.out}")


if __name__ == "__main__":
    main()
