#!/bin/bash
# One-time setup for automatic backups (run it yourself in Terminal):
#   bash ~/"Touchdesigner Designs/Hue Rig/tools/install_backup.sh"
# - backs up after every commit (git hook)
# - and every hour, plus at login (launchd agent com.ney.backup)
# Undo: launchctl bootout gui/$(id -u)/com.ney.backup; rm ~/Library/LaunchAgents/com.ney.backup.plist .git/hooks/post-commit
set -e
RIG="$(cd "$(dirname "$0")/.." && pwd)"
cat > "$RIG/.git/hooks/post-commit" <<'EOF'
#!/bin/sh
( "$(git rev-parse --show-toplevel)/tools/backup.sh" >/dev/null 2>&1 & )
EOF
chmod +x "$RIG/.git/hooks/post-commit"
PL=~/Library/LaunchAgents/com.ney.backup.plist
cat > "$PL" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.ney.backup</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$RIG/tools/backup.sh</string></array>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
</dict></plist>
EOF
launchctl bootout gui/$(id -u)/com.ney.backup 2>/dev/null || true
launchctl bootstrap gui/$(id -u) "$PL"
echo "Automatic backups are on. Log: $RIG/.git/backup.log"
