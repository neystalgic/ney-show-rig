#!/bin/bash
# =============================================================================
# NEY RIG BACKUP  (runs hourly via launchd + after every commit)
#  1. Snapshots ALL current work (saved or not) onto the branch "autosave".
#     Your real branch (main) and your staging area are never touched.
#     .gitignore still applies, so hue_config.json / rig_control.token never leave the Mac.
#  2. Pushes main + autosave to the Pi (always on) and to GitHub (once you've signed in).
#  Log: .git/backup.log
# =============================================================================
cd "$(dirname "$0")/.." || exit 1
export GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=8'
LOG=.git/backup.log
exec 9>.git/backup.lock; flock -n 9 2>/dev/null || true      # (macOS has no flock; harmless)
ts() { date '+%Y-%m-%d %H:%M:%S'; }

TMPIDX=$(mktemp)
cp .git/index "$TMPIDX" 2>/dev/null
GIT_INDEX_FILE="$TMPIDX" git add -A >/dev/null 2>&1
TREE=$(GIT_INDEX_FILE="$TMPIDX" git write-tree)
rm -f "$TMPIDX"
if [ "$TREE" != "$(git rev-parse 'HEAD^{tree}')" ]; then
  C=$(echo "autosave $(ts)" | git commit-tree "$TREE" -p HEAD)
  git update-ref refs/heads/autosave "$C"
else
  git update-ref refs/heads/autosave HEAD
fi

for R in pi origin; do
  if git push -q "$R" main +autosave >>"$LOG" 2>&1; then echo "$(ts) backed up to $R" >>"$LOG"
  else echo "$(ts) could not reach $R (backup will retry next hour)" >>"$LOG"; fi
done
tail -n 400 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
