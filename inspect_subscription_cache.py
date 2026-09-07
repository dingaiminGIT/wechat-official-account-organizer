"""Extract account metadata from the owner's local subscription feed cache.

This is NOT a complete/current follow list. No account operations, network,
screenshots, database writes, or process-memory reads. Outputs only public
account IDs/names; cache encryption material stays in memory.

Static evidence in WeChat 4.1.11 ARM64:
SavePermanentData handler 0x1e79b78 -> GetMMKVInstance 0x1dcadc0.
The latter scopes resource URLs by project and hashes scope + '_' + username.
The cache key construction at 0x1dcb500 uses a 16-bit portion of an integer
followed by '_psw'. Validate candidates against a complete small cache record;
do not inspect login credentials to retrieve that integer.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.decrepit.ciphers.modes import CFB

from inspect_runtime_config import block, varint

BASE = Path.home() / 'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files'


def snapshot(path):
    crc_path = path.with_name(path.name + '.crc')
    meta = crc_path.read_bytes()
    raw = path.read_bytes()
    if crc_path.read_bytes() != meta:
        raise ValueError('Cache changed during read; retry')
    if len(meta) < 32 or struct.unpack_from('<I', meta, 4)[0] != 4:
        raise ValueError('Unsupported cache format')
    length = struct.unpack_from('<I', meta, 28)[0]
    payload = raw[4:4 + length]
    if length != len(payload) or zlib.crc32(payload) != struct.unpack_from('<I', meta)[0]:
        raise ValueError('Cache checksum mismatch')
    return payload, meta[12:28]


def entries(data):
    _, pos = varint(data, 0)
    result = {}
    while pos < len(data):
        name, pos = block(data, pos)
        if not 0 < len(name) < 4096:
            raise ValueError('Invalid cache key length')
        name = name.decode('utf-8')
        if any(ord(c) < 32 for c in name):
            raise ValueError('Invalid cache key characters')
        value, pos = block(data, pos)
        if value:
            result[name] = value
        else:
            result.pop(name, None)
    return result


def decrypt(payload, iv, key):
    decoder = Cipher(algorithms.AES(key), CFB(iv)).decryptor()
    return decoder.update(payload) + decoder.finalize()


def scope_file(profile, scope):
    username = profile.name.rsplit('_', 1)[0]
    name = hashlib.md5((scope + '_' + username).encode()).hexdigest()
    return profile / 'business/xweb/mmkv' / name


def extract(profile):
    profile = profile.resolve()
    if not profile.is_relative_to(BASE.resolve()) or profile.parent != BASE.resolve():
        raise ValueError('Expected an own local WeChat profile directory')
    reference = scope_file(profile, 'weixin://resourceid/SubscriptionProfile')
    target = scope_file(profile, 'weixin://resourceid/SubscriptionDisorder')
    # Only these two official-account namespaces are read.
    payload, iv = snapshot(reference)
    if not 0 < len(payload) <= 65536:
        raise ValueError('No suitable small reference cache; this method is unavailable')
    matches = []
    for portion in range(65536):
        candidate = (str(portion) + '_psw').encode().ljust(16, b'\0')
        try:
            parsed = entries(decrypt(payload, iv, candidate))
            if parsed and 'websearch:h5versionforliteapp' in parsed:
                matches.append(candidate)
        except (ValueError, UnicodeDecodeError):
            pass
    if len(matches) != 1:
        raise ValueError('No unique validated cache decoder; unsupported profile/build')
    payload, iv = snapshot(target)
    decoded = entries(decrypt(payload, iv, matches[0]))
    value = decoded.get('__disorderPage_cacheMsgKey')
    if value is None:
        raise ValueError('Subscription feed cache is absent')
    encoded, end = block(value, 0)
    if end != len(value):
        raise ValueError('Unexpected cache value encoding')
    groups = json.loads(encoded)
    if not isinstance(groups, list):
        raise ValueError('Unexpected feed cache shape')
    accounts = {}
    for row in groups:
        if not isinstance(row, dict):
            continue
        account_id, name = row.get('name'), row.get('showName')
        if not isinstance(account_id, str) or not account_id or not isinstance(name, str):
            continue
        accounts[account_id] = {'id': account_id, 'name': name, 'following_verified': False}
    return {
        'source': 'subscription_feed_cache', 'readonly': True,
        'inspected_at': datetime.now(timezone.utc).isoformat(),
        'cache_modified_at': datetime.fromtimestamp(target.stat().st_mtime, timezone.utc).isoformat(),
        'complete_follow_list': False, 'following_verified': False,
        'selectable_for_unfollow': False, 'message_groups': len(groups),
        'accounts': sorted(accounts.values(), key=lambda x: (x['name'], x['id'])),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='Private local JSON output')
    args = parser.parse_args()
    if args.profile is None:
        profiles = [p for p in BASE.glob('wxid_*') if (p / 'business/xweb/mmkv').is_dir()]
        if len(profiles) != 1:
            parser.error('Multiple/no local profiles; explicitly choose --profile')
        args.profile = profiles[0]
    report = extract(args.profile)
    if args.output.resolve().is_relative_to(BASE.resolve()):
        parser.error('Output must be outside WeChat storage')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Permission is established before account metadata is written.
    import os
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(report, out, ensure_ascii=False, indent=2)
    print(json.dumps({'accounts': len(report['accounts']), 'message_groups': report['message_groups'],
                      'complete_follow_list': False, 'following_verified': False}, ensure_ascii=False))
