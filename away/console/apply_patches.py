# apply_patches.py -- guarded install of the Rig Console (away loop W2, Nov 17).  Michael runs this; the loop never does.
#   1. copies console_route.py + console.html next to rig_control.py (backs up any older copy first)
#   2. adds 3 lines to rig_control.py's Handler, just before the /show/set route:
#          /console and /console.json -> console_route.handle(...)   (after the usual token check = same login as /health)
#   3. backs up rig_control.py first (rig_control.py.bak-2026-11-17-console) and checks the result compiles.
# STOP (nothing touched) if the anchor line moved or appears twice.  Safe to run twice (it sees it's already in).
import os, py_compile, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
STAMP = '2026-11-17-console'   # own name: spot-power's install also makes a .bak-2026-11-17
FILES = ('console_route.py', 'console.html')
ANCHOR = "        if path == 'show/set':"
MARK = 'console_route.handle('
BLOCK = ("        if path in ('console', 'console.json'):         # Nov 17: Rig Console page (away/console/DEPLOY.txt)\n"
         "            import console_route\n"
         "            return console_route.handle(self, path, HERE, TOKEN, STATE)\n")


def backup(path):
    b = '%s.bak-%s' % (path, STAMP)
    if os.path.exists(path) and not os.path.exists(b):
        shutil.copy2(path, b)
    return b


def main(root=REPO, src=HERE):
    rc = os.path.join(root, 'rig_control.py')
    with open(rc) as f:
        text = f.read()
    patched = MARK in text
    if not patched and text.count(ANCHOR) != 1:
        print('STOP: the /show/set line in rig_control.py moved (found %d) -- nothing changed. Ask Claude to re-anchor.'
              % text.count(ANCHOR))
        return 2
    for name in FILES:                                  # all checks before any write
        if not os.path.exists(os.path.join(src, name)):
            print('STOP: %s missing in %s -- nothing changed.' % (name, src))
            return 2
    for name in FILES:
        s, d = os.path.join(src, name), os.path.join(root, name)
        if os.path.exists(d):
            with open(s, 'rb') as a, open(d, 'rb') as b:
                if a.read() == b.read():
                    print('same already: %s' % name)
                    continue
            backup(d)
        shutil.copy2(s, d)
        print('copied: %s' % name)
    if patched:
        print('rig_control.py already has the console route.')
    else:
        backup(rc)
        new = text.replace(ANCHOR, BLOCK + ANCHOR, 1)
        with open(rc, 'w') as f:
            f.write(new)
        try:
            py_compile.compile(rc, doraise=True)
        except py_compile.PyCompileError as e:
            with open(rc, 'w') as f:                    # put it back exactly as it was
                f.write(text)
            print('STOP: patched rig_control.py did not compile, restored the original: %s' % e)
            return 2
        print('patched: rig_control.py (/console + /console.json), backup %s' % os.path.basename(backup(rc)))
    print('OK -- reload rig_control (no hub restart), then open /console on the phone.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
