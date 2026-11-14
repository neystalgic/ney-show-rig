#!/usr/bin/env python3
"""Offline test for bak_candidates.py: builds a throwaway git repo in a temp folder.
No network, and the real Hue Rig repo is never touched."""
import datetime as dt
import os
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bak_candidates as bc  # noqa: E402


def _no_net(*a, **k):
    raise RuntimeError("network blocked in tests")


socket.socket.connect = _no_net
socket.create_connection = _no_net

TODAY = dt.date(2026, 11, 14)
failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


def run(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True, capture_output=True)


def write(repo, rel, text):
    p = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


def commit(repo, msg):
    run(repo, "add", "-A")
    run(repo, "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


with tempfile.TemporaryDirectory() as repo:
    run(repo, "init", "-q")
    write(repo, ".gitignore", "*.bak-*\n")
    write(repo, "hub.py", "v1\n")
    write(repo, "dmx/node.py", "n1\n")
    commit(repo, "one")
    write(repo, "hub.py", "v2\n")
    commit(repo, "two")
    write(repo, "hub.py", "v3\n")
    commit(repo, "three")
    # on a side branch: content only committed there
    run(repo, "checkout", "-q", "-b", "side")
    write(repo, "other.py", "side-only\n")
    commit(repo, "side")
    run(repo, "checkout", "-q", "-")

    write(repo, "hub.py.bak-oct30", "v1\n")          # old, in git -> candidate
    write(repo, "hub.py.bak-nov02b", "v2\n")         # old, in git (letter suffix) -> candidate
    write(repo, "hub.py.bak-nov03", "edited, never committed\n")  # old, not in git -> keep
    write(repo, "hub.py.bak-nov12", "v1\n")          # in git but too new -> too_new
    write(repo, "hub.py.bak-nov07", "v1\n")          # exactly 7 days -> too new (strictly older)
    write(repo, "dmx/node.py.bak-oct31", "n1\n")     # subfolder candidate
    write(repo, "copy.py.bak-oct30", "side-only\n")  # same content committed under another path/branch
    write(repo, "hub.py.bak-dec20", "v3\n")          # December > November -> last year -> candidate
    write(repo, "hub.py.bak-old", "v2\n")            # no date in name -> uses file time
    old = time.mktime((2026, 10, 1, 12, 0, 0, 0, 0, -1))
    os.utime(os.path.join(repo, "hub.py.bak-old"), (old, old))
    write(repo, "hue_config.json.bak-oct30", "SECRET\n")  # secret-looking: skipped, not hashed
    write(repo, "away/x/hub.py.bak-oct30", "v1\n")   # inside away/: ignored
    before = subprocess.run(["git", "-C", repo, "status", "--porcelain", "--ignored"],
                            capture_output=True, text=True).stdout

    cand, kept, new, skipped = bc.build_report(repo, 7, TODAY)
    cp = {c["path"]: c for c in cand}
    check("old in-git backup is a candidate", "hub.py.bak-oct30" in cp)
    check("letter-suffix date read (nov02b)", "hub.py.bak-nov02b" in cp)
    check("subfolder backup found", os.path.join("dmx", "node.py.bak-oct31") in cp)
    check("content committed under other path/branch counts",
          cp.get("copy.py.bak-oct30", {}).get("git_path") == "other.py")
    check("dec in November = last year", cp.get("hub.py.bak-dec20", {}).get("date") == dt.date(2025, 12, 20))
    check("no-date name falls back to file time",
          cp.get("hub.py.bak-old", {}).get("date_from") == "file time")
    first = subprocess.run(["git", "-C", repo, "rev-list", "--max-parents=0", "HEAD"],
                           capture_output=True, text=True).stdout.strip()[:8]
    check("first commit is reported (8-char hash)", cp["hub.py.bak-oct30"]["commit"] == first)
    check("never-committed backup is kept", [k["path"] for k in kept] == ["hub.py.bak-nov03"])
    check("recent backups left alone",
          sorted(n["path"] for n in new) == ["hub.py.bak-nov07", "hub.py.bak-nov12"])
    check("secret-looking file skipped", [s["path"] for s in skipped] == ["hue_config.json.bak-oct30"])
    check("away/ folder ignored", not any(p.startswith("away") for p in cp))
    check("exactly 6 candidates", len(cand) == 6)

    text = bc.format_report(cand, kept, new, skipped, 7, TODAY)
    check("report says list only", "LIST ONLY" in text)
    check("report never contains secret content", "SECRET" not in text)
    check("report cutoff date", "dated before 2026-11-07" in text)
    after = subprocess.run(["git", "-C", repo, "status", "--porcelain", "--ignored"],
                           capture_output=True, text=True).stdout
    check("nothing moved or changed", before == after)

    # tag_date unit checks
    check("tag_date nov13c", bc.tag_date("nov13c", TODAY) == dt.date(2026, 11, 13))
    check("tag_date junk", bc.tag_date("v2", TODAY) is None)
    check("tag_date bad day", bc.tag_date("feb31", TODAY) is None)

print("\nALL PASSED" if not failures else f"\n{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
