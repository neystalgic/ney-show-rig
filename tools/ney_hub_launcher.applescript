-- Ney Hub launcher: starts hue_hub.py so macOS can give THIS app (only) the microphone.
-- Build: osacompile -o "Ney Hub.app" this file, then add NSMicrophoneUsageDescription + LSUIElement
-- to its Info.plist and ad-hoc sign it (codesign --force --deep -s -). Rebuilding = macOS asks for the mic again.
on run
	try
		do shell script "cd " & quoted form of "/Users/michaelney/Touchdesigner Designs/Hue Rig" & " && exec /usr/bin/arch -arm64 /bin/zsh -lc 'exec python3 -u hue_hub.py >> hub_log.txt 2>&1'"
	end try
end run
