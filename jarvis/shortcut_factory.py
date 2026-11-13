#!/usr/bin/env python3
"""Builds ALL the rig's Siri Shortcuts (Nov 12, token rotation): every one talks to the Pi's front door
(http://192.168.1.80:7041), which passes to the Mac or covers when it sleeps. The token travels in an X-Token
header inside each shortcut -- never in a link. Pages (Rig Health, Movie Hub) log in with a one-time code.
Signed with macOS's own `shortcuts sign`, then opened one by one so Michael clicks "Add Shortcut".
Files land in bridge/shortcuts/ (never committed)."""
import os, plistlib, subprocess, sys, time, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
BASE = 'http://192.168.1.80:7041'
OUT = os.path.join(RIG, 'bridge', 'shortcuts')

# name: (kind, path)   kinds: jarvis | speak | silent | page
SET = [
    ('Jarvis', 'jarvis', '/ask'),
    ('Light Show', 'speak', '/show'), ('Safe Show', 'speak', '/showsafe'),
    ('Movie Night', 'speak', '/movienight'), ('Movie Stars', 'speak', '/movieuv'), ('Movie Mode', 'speak', '/movie'),
    ('Play Pause', 'silent', '/m/key?k=space'), ('Intermission', 'silent', '/m/lights?l=intermission'),
    ('Back to the Movie', 'silent', '/m/lights?l=resume'), ('Lights Up', 'silent', '/m/lights?l=up'),
    ('Purple', 'speak', '/purple'), ('Rainbow Fade', 'speak', '/rainbow'), ('Goodnight', 'speak', '/night'),
    ('Lights Off', 'speak', '/off'), ('Guest Mode', 'speak', '/guest_on'),
    ('Rig Health', 'page', '/health'), ('Movie Hub', 'page', '/hub'),
]


def _u():
    return str(uuid.uuid4()).upper()


def text(s):
    return {'Value': {'string': s, 'attachmentsByRange': {}}, 'WFSerializationType': 'WFTextTokenString'}


def tok_text(prefix, uid, name, suffix='', as_text=False):
    att = {'OutputUUID': uid, 'Type': 'ActionOutput', 'OutputName': name}
    if as_text:
        att['Aggrandizements'] = [{'Type': 'WFCoercionVariableAggrandizement', 'CoercionItemClass': 'WFStringContentItem'}]
    return {'Value': {'string': prefix + '￼' + suffix, 'attachmentsByRange': {'{%d, 1}' % len(prefix): att}},
            'WFSerializationType': 'WFTextTokenString'}


def headers(token):
    return {'Value': {'WFDictionaryFieldValueItems': [{'WFItemType': 0, 'WFKey': text('X-Token'), 'WFValue': text(token)}]},
            'WFSerializationType': 'WFDictionaryFieldValue'}


def fetch(uid, url, token, method='GET', json_items=None):
    p = {'UUID': uid, 'WFURL': url, 'WFHTTPMethod': method, 'ShowHeaders': True, 'WFHTTPHeaders': headers(token)}
    if json_items is not None:
        p.update(WFHTTPBodyType='JSON', WFJSONValues={'Value': {'WFDictionaryFieldValueItems': json_items},
                                                      'WFSerializationType': 'WFDictionaryFieldValue'})
    return {'WFWorkflowActionIdentifier': 'is.workflow.actions.downloadurl', 'WFWorkflowActionParameters': p}


def actions(kind, path, token):
    if kind == 'jarvis':
        u1, u2, u3 = _u(), _u(), _u()
        return [{'WFWorkflowActionIdentifier': 'is.workflow.actions.dictatetext',
                 'WFWorkflowActionParameters': {'UUID': u1, 'WFDictateTextStopListening': 'After Pause'}},
                fetch(u2, BASE + path, token, 'POST', [{'WFItemType': 0, 'WFKey': text('text'),
                                                        'WFValue': tok_text('', u1, 'Dictated Text')}]),
                {'WFWorkflowActionIdentifier': 'is.workflow.actions.speaktext',
                 'WFWorkflowActionParameters': {'UUID': u3, 'WFText': tok_text('', u2, 'Contents of URL', as_text=True)}}]
    if kind in ('speak', 'silent'):
        u1 = _u()
        a = [fetch(u1, BASE + path, token)]
        if kind == 'speak':
            a.append({'WFWorkflowActionIdentifier': 'is.workflow.actions.speaktext',
                      'WFWorkflowActionParameters': {'UUID': _u(), 'WFText': tok_text('', u1, 'Contents of URL', as_text=True)}})
        return a
    if kind == 'page':                                   # one-time login code -> open the page (no token in the link)
        u1 = _u()
        return [fetch(u1, BASE + '/login', token, 'POST', []),
                {'WFWorkflowActionIdentifier': 'is.workflow.actions.openurl',
                 'WFWorkflowActionParameters': {'UUID': _u(), 'WFInput': tok_text(BASE + '/go?c=', u1, 'Contents of URL',
                                                                                  '&to=' + path, as_text=True)}}]
    raise ValueError(kind)


def workflow(kind, path, token):
    return {'WFWorkflowActions': actions(kind, path, token), 'WFWorkflowClientVersion': '2605.0.5',
            'WFWorkflowMinimumClientVersion': 900, 'WFWorkflowMinimumClientVersionString': '900',
            'WFWorkflowIcon': {'WFWorkflowIconStartColor': 2071128575, 'WFWorkflowIconGlyphNumber': 59511},
            'WFWorkflowImportQuestions': [], 'WFWorkflowInputContentItemClasses': [], 'WFWorkflowTypes': [],
            'WFWorkflowOutputContentItemClasses': [], 'WFWorkflowHasShortcutInputVariables': False,
            'WFQuickActionSurfaces': [], 'WFWorkflowHasOutputFallback': False}


def build_all(open_them=True, only=None):
    with open(os.path.join(RIG, 'rig_control.token')) as f:
        token = f.read().strip()
    os.makedirs(OUT, exist_ok=True)
    made, failed = [], []
    for name, kind, path in SET:
        if only and name not in only:
            continue
        raw = os.path.join(OUT, '%s-unsigned.shortcut' % name)
        signed = os.path.join(OUT, '%s.shortcut' % name)
        with open(raw, 'wb') as f:
            plistlib.dump(workflow(kind, path, token), f, fmt=plistlib.FMT_BINARY)
        if os.path.exists(signed):
            os.replace(signed, signed + '.old')
        r = subprocess.run(['/usr/bin/shortcuts', 'sign', '--mode', 'anyone', '--input', raw, '--output', signed],
                           capture_output=True, text=True)
        if r.returncode or not os.path.exists(signed):
            failed.append('%s: %s' % (name, (r.stderr or r.stdout).strip()[:80]))
            continue
        made.append(name)
        if open_them:
            subprocess.run(['/usr/bin/open', signed])
            time.sleep(2.5)                              # one import dialog at a time
    token = None
    return made, failed


if __name__ == '__main__':
    m, f = build_all(open_them='--no-open' not in sys.argv)
    print('made: %s' % ', '.join(m))
    if f:
        print('FAILED: %s' % '; '.join(f))
