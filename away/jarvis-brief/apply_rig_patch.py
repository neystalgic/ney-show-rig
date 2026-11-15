"""Adds the morning briefing to rig_control.py's /body/activity (the iPhone Health Sync).

  python3 away/jarvis-brief/apply_rig_patch.py rig_control.py

After the row is stored, the reply also carries the brief (so the Shortcut can Speak it on the phone) and the Mac
says it once a day in the morning (jarvis/brief.py decides). If anything in the brief fails, the sync reply is
exactly what it was before -- the brief can never break the Health Sync.
Safe to run twice (it does nothing the second time). Backs up the file first as rig_control.py.bak-nov15-brief.
"""
import shutil, sys

ANCHOR = "            return self.reply(200, 'Health synced for %s: %s.' % (day, got or 'no numbers yet'))\n"
PATCH = """            extra = ''                                  # Nov 15: Jarvis morning briefing (jarvis/brief.py)
            try:
                if os.path.join(HERE, 'jarvis') not in sys.path:
                    sys.path.insert(0, os.path.join(HERE, 'jarvis'))
                import brief
                extra = brief.after_sync(row)
            except Exception:
                extra = ''
            return self.reply(200, 'Health synced for %s: %s.%s' % (day, got or 'no numbers yet', extra))
"""
MARK = 'Nov 15: Jarvis morning briefing'


def patch(text):
    if MARK in text:
        return text, 'already patched'
    if text.count(ANCHOR) != 1:
        raise SystemExit('STOP: the /body/activity reply line was not found exactly once -- rig_control.py changed. Nothing written.')
    return text.replace(ANCHOR, PATCH), 'patched'


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else 'rig_control.py'
    with open(path) as f:
        old = f.read()
    new, what = patch(old)
    if what == 'patched':
        shutil.copy2(path, path + '.bak-nov15-brief')
        compile(new, path, 'exec')                 # refuse to write something that doesn't parse
        with open(path, 'w') as f:
            f.write(new)
    print('rig_control.py:', what)
