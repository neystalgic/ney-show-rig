-- Ney Jarvis launcher: starts jarvis/listen.py ("Hey Jarvis") so macOS gives THIS app (only) the microphone.
-- Built by rig_control task build_jarvis_app (osacompile + Info.plist mic note + ad-hoc codesign), like Ney Hub.app.
on run
	try
		do shell script "cd " & quoted form of "/Users/michaelney/Touchdesigner Designs/Hue Rig" & " && exec /usr/bin/arch -arm64 /bin/zsh -lc 'exec python3 -u jarvis/listen.py >> /tmp/jarvis_listen.out 2>&1'"
	end try
end run
