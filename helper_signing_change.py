#!/usr/bin/env python3
"""Review/apply/restore the prepared, exact-build WeChatAppEx signing change.

Default is read-only. Applying to the installed app requires explicit user consent
and a separate invocation as root after WeChat exits. Never disables SIP.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile

PACKAGE = Path(__file__).resolve().parent / '.runtime/helper-signing-change'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(package, target):
    manifest = json.loads((package / 'manifest.json').read_text())
    with (target / 'Contents/Info.plist').open('rb') as handle:
        build = str(plistlib.load(handle)['CFBundleVersion'])
    if build != manifest['build']:
        raise RuntimeError('Build changed; prepare a new change package.')
    states = []
    for item in manifest['files']:
        rel = Path(item['relative_path'])
        if rel.is_absolute() or '..' in rel.parts:
            raise RuntimeError('Invalid package path')
        for kind in ('original', 'replacement'):
            if digest(package / kind / rel) != item[kind + '_sha256']:
                raise RuntimeError(f'Backup/replacement hash mismatch: {rel}')
        actual = digest(target / rel)
        state = next((kind for kind in ('original', 'replacement')
                      if actual == item[kind + '_sha256']), 'unknown')
        states.append({'path': str(rel), 'state': state})
    return manifest, states


def atomic_write(path, data, item):
    fd, name = tempfile.mkstemp(prefix='.signing-change-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), item['mode'])
            os.fchown(handle.fileno(), item['uid'], item['gid'])
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def change(package, target, action):
    manifest, states = inspect(package, target)
    if any(item['state'] == 'unknown' for item in states):
        raise RuntimeError('Unrecognized installed files; refusing to overwrite.')
    desired = 'replacement' if action == 'apply' else 'original'
    if action == 'apply' and len({s['state'] for s in states}) > 1:
        raise RuntimeError('Partial change found; restore before applying.')
    before = {i['relative_path']: (target / i['relative_path']).read_bytes()
              for i in manifest['files']}
    changed = []
    try:
        for item in manifest['files']:
            rel = item['relative_path']
            if digest(target / rel) != item[desired + '_sha256']:
                atomic_write(target / rel, (package / desired / rel).read_bytes(), item)
                changed.append(item)
        subprocess.run(['codesign', '--verify', '--strict', str(target)], check=True)
        _, after = inspect(package, target)
        if any(s['state'] != desired for s in after):
            raise RuntimeError('Post-change hash mismatch')
        return after
    except Exception:
        for item in reversed(changed):
            atomic_write(target / item['relative_path'], before[item['relative_path']], item)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='plan', choices=['plan', 'apply', 'restore'])
    args = parser.parse_args()
    manifest = json.loads((PACKAGE / 'manifest.json').read_text())
    target = Path(manifest['target_app'])
    if args.action == 'plan':
        _, states = inspect(PACKAGE, target)
    else:
        if os.geteuid() != 0:
            raise RuntimeError('Installed helper changes require an explicit administrator invocation.')
        processes = subprocess.check_output(['ps', '-axo', 'comm='], text=True)
        if any('/Applications/WeChat.app/' in line for line in processes.splitlines()):
            raise RuntimeError('WeChat processes are still running. Exit before changing files.')
        states = change(PACKAGE, target, args.action)
    print(json.dumps({'action': args.action, 'target': str(target), 'build': manifest['build'],
                      'files': states, 'restart_required_after_change': True}, indent=2))


if __name__ == '__main__':
    main()
