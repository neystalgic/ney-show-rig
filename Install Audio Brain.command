#!/bin/zsh -l
# Double-click once: installs Essentia (about 20 MB, from PyPI) for the Hue Hub's "audio brain",
# which hears the chords and key in your music. Safe to run again.
cd "$(dirname "$0")"
echo "Python the hub uses: $(which python3)  ($(python3 --version 2>&1))"
echo
python3 -m pip install --user --upgrade "essentia==2.1b6.dev1389"
echo
if python3 -c "import essentia.standard; import hub_brain; print('Audio brain ready:', hub_brain.available())" 2>/dev/null; then
  echo "Done. Restart the Hue Hub (Start Hue Hub.command) and the desk will show what it hears."
else
  echo "Essentia didn't load -- copy this window's text to Claude."
fi
echo
read "?Press Return to close."
