# =============================================================================
# MOVIE REMOTE -- the Mac side of the Movie Hub (used by rig_control.py)
#
#   open a streaming service full screen on the projector (Safari: the best picture
#   and DRM support on a Mac), and drive it from the phone: keys, a trackpad,
#   typing, volume. Keys / mouse need Accessibility permission for Python once:
#   System Settings > Privacy & Security > Accessibility > Python (on).
# =============================================================================
import ctypes
import subprocess
import time

SERVICES = {
    'netflix': ('Netflix', 'https://www.netflix.com/browse'),
    'max': ('HBO Max', 'https://www.hbomax.com/'),
    'hulu': ('Hulu', 'https://www.hulu.com/hub/home'),
    'disney': ('Disney+', 'https://www.disneyplus.com/home'),
    'prime': ('Prime Video', 'https://www.amazon.com/gp/video/storefront'),
    'youtube': ('YouTube', 'https://www.youtube.com/'),
}
KEYS = {'space': 49, 'left': 123, 'right': 124, 'down': 125, 'up': 126, 'enter': 36, 'esc': 53,
        'f': 3, 'm': 46, 'tab': 48, 'backspace': 51, 'k': 40, 'j': 38, 'l': 37}
CMD, CTRL, SHIFT = 1 << 20, 1 << 18, 1 << 17

_CG = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
_CF = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')


class CGPoint(ctypes.Structure):
    _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [('w', ctypes.c_double), ('h', ctypes.c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [('o', CGPoint), ('s', CGSize)]


_CG.CGEventCreate.restype = ctypes.c_void_p
_CG.CGEventCreate.argtypes = [ctypes.c_void_p]
_CG.CGEventGetLocation.restype = CGPoint
_CG.CGEventGetLocation.argtypes = [ctypes.c_void_p]
_CG.CGEventCreateMouseEvent.restype = ctypes.c_void_p
_CG.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
_CG.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
_CG.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
_CG.CGEventKeyboardSetUnicodeString.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_uint16)]
_CG.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
_CG.CGEventCreateScrollWheelEvent2.restype = ctypes.c_void_p
_CG.CGEventCreateScrollWheelEvent2.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32,
                                               ctypes.c_int32, ctypes.c_int32]
_CG.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
_CG.CGMainDisplayID.restype = ctypes.c_uint32
_CG.CGGetActiveDisplayList.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
_CG.CGDisplayBounds.restype = CGRect
_CG.CGDisplayBounds.argtypes = [ctypes.c_uint32]
_CG.AXIsProcessTrusted.restype = ctypes.c_bool
_CF.CFRelease.argtypes = [ctypes.c_void_p]


def trusted():
    """Has this Python been allowed to press keys / move the mouse (Accessibility)?"""
    try:
        return bool(_CG.AXIsProcessTrusted())
    except Exception:
        return False


def _post(ev):
    if ev:
        _CG.CGEventPost(0, ev)
        _CF.CFRelease(ev)


def displays():
    n = ctypes.c_uint32(0)
    ids = (ctypes.c_uint32 * 8)()
    _CG.CGGetActiveDisplayList(8, ids, ctypes.byref(n))
    out = []
    for i in range(n.value):
        r = _CG.CGDisplayBounds(ids[i])
        out.append(dict(id=ids[i], x=r.o.x, y=r.o.y, w=r.s.w, h=r.s.h, main=ids[i] == _CG.CGMainDisplayID()))
    return out


def _bounds():
    ds = displays()
    if not ds:
        return 0, 0, 1920, 1080
    return (min(d['x'] for d in ds), min(d['y'] for d in ds),
            max(d['x'] + d['w'] for d in ds), max(d['y'] + d['h'] for d in ds))


def where():
    ev = _CG.CGEventCreate(None)
    p = _CG.CGEventGetLocation(ev)
    _CF.CFRelease(ev)
    return p.x, p.y


def mouse_move(dx, dy):
    x, y = where()
    x0, y0, x1, y1 = _bounds()
    p = CGPoint(min(max(x + dx, x0), x1 - 1), min(max(y + dy, y0), y1 - 1))
    _post(_CG.CGEventCreateMouseEvent(None, 5, p, 0))           # mouse moved


def click(button='left'):
    x, y = where()
    p = CGPoint(x, y)
    down, up, b = (1, 2, 0) if button == 'left' else (3, 4, 1)
    _post(_CG.CGEventCreateMouseEvent(None, down, p, b))
    time.sleep(0.02)
    _post(_CG.CGEventCreateMouseEvent(None, up, p, b))


def scroll(dy):
    _post(_CG.CGEventCreateScrollWheelEvent2(None, 0, 1, int(dy), 0, 0))   # pixel units


def key(name, flags=0):
    code = KEYS[name]
    for down in (True, False):
        ev = _CG.CGEventCreateKeyboardEvent(None, code, down)
        if flags:
            _CG.CGEventSetFlags(ev, flags)
        _post(ev)
        time.sleep(0.01)


def type_text(text):
    for ch in text[:200]:
        raw = ch.encode('utf-16-le')
        units = [int.from_bytes(raw[i:i + 2], 'little') for i in range(0, len(raw), 2)]
        arr = (ctypes.c_uint16 * len(units))(*units)
        for down in (True, False):
            ev = _CG.CGEventCreateKeyboardEvent(None, 0, down)
            _CG.CGEventKeyboardSetUnicodeString(ev, len(units), arr)
            _post(ev)
        time.sleep(0.01)


def osa(script, lang='AppleScript', timeout=10):
    args = ['osascript'] + (['-l', 'JavaScript'] if lang == 'JavaScript' else []) + ['-e', script]
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout.strip()


def volume(delta=None, mute=None):
    if mute is not None:
        osa('set volume output muted %s' % ('true' if mute else 'false'))
    if delta is not None:
        osa('set volume output volume ((output volume of (get volume settings)) + (%d))' % int(delta))
    try:
        v = osa('output volume of (get volume settings) & "," & output muted of (get volume settings)')
        vol, muted = v.split(',')
        return dict(volume=int(vol), muted=muted.strip() == 'true')
    except Exception:
        return dict(volume=None, muted=None)


def open_service(sid):
    """Safari, the service's page, moved to the projector (if it's a second screen), full screen."""
    name, url = SERVICES[sid]
    subprocess.run(['open', '-a', 'Safari', url], timeout=10)
    time.sleep(1.2)
    ds = displays()
    proj = [d for d in ds if not d['main']]
    if proj:                                   # extended desktop: put the window on the projector first
        d = proj[0]
        osa('tell application "Safari" to set bounds of front window to {%d, %d, %d, %d}'
            % (d['x'] + 40, d['y'] + 40, d['x'] + d['w'] - 40, d['y'] + d['h'] - 40))
        time.sleep(0.3)
    osa('tell application "Safari" to activate')
    time.sleep(0.6)
    if trusted():                              # full screen: Ctrl+Cmd+F (only if it isn't already)
        fs = osa('tell application "System Events" to tell process "Safari" to get value of attribute '
                 '"AXFullScreen" of front window')
        if fs != 'true':
            key('f', CMD | CTRL)
    return name


def ask_access():
    """Show macOS's own 'allow Python to control this computer' prompt (Accessibility). Returns trusted()."""
    try:
        cf = _CF
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFDictionaryCreate.restype = ctypes.c_void_p
        cf.CFDictionaryCreate.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
                                          ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
        _CG.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
        _CG.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
        k = cf.CFStringCreateWithCString(None, b'AXTrustedCheckOptionPrompt', 0x08000100)
        t = ctypes.c_void_p.in_dll(cf, 'kCFBooleanTrue')
        keys = (ctypes.c_void_p * 1)(k)
        vals = (ctypes.c_void_p * 1)(t.value)
        kcb = ctypes.addressof(ctypes.c_byte.in_dll(cf, 'kCFTypeDictionaryKeyCallBacks'))
        vcb = ctypes.addressof(ctypes.c_byte.in_dll(cf, 'kCFTypeDictionaryValueCallBacks'))
        d = cf.CFDictionaryCreate(None, keys, vals, 1, kcb, vcb)
        return bool(_CG.AXIsProcessTrustedWithOptions(d))
    except Exception:
        subprocess.run(['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'])
        return trusted()
