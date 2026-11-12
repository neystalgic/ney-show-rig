#!/usr/bin/env python3
"""Builds the "Jarvis" Siri Shortcut (Dictate -> ask the rig -> speak the answer), signs it with
macOS's own `shortcuts sign`, and opens it so you can click Add Shortcut. iCloud syncs it to the
iPhone and Watch. The rig token goes INSIDE the shortcut only; the files land in bridge/ (never committed)."""
import os, plistlib, subprocess, sys, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
NAME = sys.argv[1] if len(sys.argv) > 1 else 'Jarvis'
HOST = 'Michaels-MacBook-Pro-2.local'


def tok(uid, name, as_text=False):
    att = {'OutputUUID': uid, 'Type': 'ActionOutput', 'OutputName': name}
    if as_text:
        att['Aggrandizements'] = [{'Type': 'WFCoercionVariableAggrandizement', 'CoercionItemClass': 'WFStringContentItem'}]
    return {'Value': {'string': '￼', 'attachmentsByRange': {'{0, 1}': att}}, 'WFSerializationType': 'WFTextTokenString'}


def text(s):
    return {'Value': {'string': s, 'attachmentsByRange': {}}, 'WFSerializationType': 'WFTextTokenString'}


def build(token):
    u1, u2, u3 = (str(uuid.uuid4()).upper() for _ in range(3))
    actions = [
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.dictatetext',
         'WFWorkflowActionParameters': {'UUID': u1, 'WFDictateTextStopListening': 'After Pause'}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.downloadurl',
         'WFWorkflowActionParameters': {
             'UUID': u2, 'WFURL': 'http://%s:7040/ask?token=%s' % (HOST, token), 'WFHTTPMethod': 'POST',
             'WFHTTPBodyType': 'JSON', 'ShowHeaders': False,
             'WFJSONValues': {'Value': {'WFDictionaryFieldValueItems': [
                 {'WFItemType': 0, 'WFKey': text('text'), 'WFValue': tok(u1, 'Dictated Text')}]},
                 'WFSerializationType': 'WFDictionaryFieldValue'}}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.speaktext',
         'WFWorkflowActionParameters': {'UUID': u3, 'WFText': tok(u2, 'Contents of URL', as_text=True)}},
    ]
    return {'WFWorkflowActions': actions, 'WFWorkflowClientVersion': '2605.0.5',
            'WFWorkflowMinimumClientVersion': 900, 'WFWorkflowMinimumClientVersionString': '900',
            'WFWorkflowIcon': {'WFWorkflowIconStartColor': 2071128575, 'WFWorkflowIconGlyphNumber': 59511},
            'WFWorkflowImportQuestions': [], 'WFWorkflowInputContentItemClasses': [], 'WFWorkflowTypes': [],
            'WFWorkflowOutputContentItemClasses': [], 'WFWorkflowHasShortcutInputVariables': False,
            'WFQuickActionSurfaces': [], 'WFWorkflowHasOutputFallback': False}


def main():
    with open(os.path.join(RIG, 'rig_control.token')) as f:
        token = f.read().strip()
    out_dir = os.path.join(RIG, 'bridge')
    os.makedirs(out_dir, exist_ok=True)
    raw = os.path.join(out_dir, '%s-unsigned.shortcut' % NAME)
    signed = os.path.join(out_dir, '%s.shortcut' % NAME)
    with open(raw, 'wb') as f:
        plistlib.dump(build(token), f, fmt=plistlib.FMT_BINARY)
    r = subprocess.run(['/usr/bin/shortcuts', 'sign', '--mode', 'anyone', '--input', raw, '--output', signed],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(signed):
        print('Signing failed:', (r.stderr or r.stdout).strip()[:300])
        sys.exit(1)
    subprocess.run(['/usr/bin/open', signed])
    print('Opened "%s". Click "Add Shortcut". Then say: Hey Siri, %s' % (NAME, NAME))


if __name__ == '__main__':
    main()
