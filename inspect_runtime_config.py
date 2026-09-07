"""Read-only, version-pinned inspection of WeChat's subscription resource mapping.

Reads four XWeb configuration stores. Never outputs their raw values or crypto
material, never writes WeChat files, and does not invoke any account operation.
Requires cryptography. This is research tooling, not a supported WeChat API.
"""
from pathlib import Path
import hashlib
import json
import struct
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.decrepit.ciphers.modes import CFB

FRAMEWORK = Path('/Applications/WeChat.app/Contents/MacOS/WeChatAppEx.app/Contents/Frameworks/WeChatAppEx Framework.framework/Versions/C/WeChatAppEx Framework')
ARM64_SHA256 = '0b5cbcc6015697ca83ab8d82ee9c19a7cea336d3344fc7938aa557f776b9d9f3'
ROOT = Path.home() / 'Library/Containers/com.tencent.xinWeChat/Data/Documents/app_data/radium'


def image():
    raw = FRAMEWORK.read_bytes()
    if raw[:4] != b'\xca\xfe\xba\xbe':
        raise ValueError('Unsupported framework format')
    count = struct.unpack_from('>I', raw, 4)[0]
    entries = [struct.unpack_from('>IIIII', raw, 8 + i * 20) for i in range(count)]
    _, _, start, size, _ = next(e for e in entries if e[0] == 0x100000c)
    data = raw[start:start + size]
    # The historical probe hashed from the ARM64 start through the file end.
    if hashlib.sha256(raw[start:]).hexdigest() != ARM64_SHA256:
        raise ValueError('WeChat framework changed; static offsets require revalidation')
    segments = []
    pos = 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, length = struct.unpack_from('<II', data, pos)
        if cmd == 0x19:
            vm, _, offset, file_size = struct.unpack_from('<QQQQ', data, pos + 24)
            segments.append((vm, offset, file_size))
        pos += length

    def constant(address, length):
        vm, offset, _ = next(s for s in segments if s[0] <= address < s[0] + s[2])
        return data[offset + address - vm:offset + address - vm + length]

    return constant


def varint(data, pos):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data):
            raise ValueError('Truncated varint')
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise ValueError('Oversized varint')


def block(data, pos):
    length, pos = varint(data, pos)
    end = pos + length
    if end > len(data):
        raise ValueError('Truncated MMKV entry')
    return data[pos:end], end


def read_store(path, constant):
    sidecar = path.with_name(path.name + '.crc')
    # Only accept a consistent on-disk snapshot; never read process memory.
    meta = sidecar.read_bytes()
    raw = path.read_bytes()
    if sidecar.read_bytes() != meta:
        raise ValueError('Store changed while reading; retry')
    version = struct.unpack_from('<I', meta, 4)[0]
    if version != 4:
        raise ValueError('Unsupported MMKV metadata version')
    length = struct.unpack_from('<I', meta, 28)[0]
    payload = raw[4:4 + length]
    if len(payload) != length or zlib.crc32(payload) != struct.unpack_from('<I', meta)[0]:
        raise ValueError('MMKV checksum mismatch; no data accepted')
    # Static constructors: 0x4cd1360 (global), 0x4cd2f3c (user).
    # These are app configuration constants, not login/database credentials.
    address = 0x93eeb3a if 'users' in path.relative_to(ROOT).parts else 0x93eea3b
    decryptor = Cipher(algorithms.AES(constant(address, 16)), CFB(meta[12:28])).decryptor()
    data = decryptor.update(payload) + decryptor.finalize()
    _, pos = varint(data, 0)
    items = {}
    while pos < len(data):
        name, pos = block(data, pos)
        value, pos = block(data, pos)
        name = name.decode('utf-8')
        if value:
            items[name] = value
        else:
            items.pop(name, None)
    return items


def report():
    constant = image()
    result = {'readonly': True, 'live_accounts_obtained': False, 'stores': [], 'subscription_resources': []}
    paths = [ROOT / 'mmkv' / name / name for name in ('xweb_config_storage', 'xweb_global_storage')]
    for user in sorted((ROOT / 'users').iterdir()):
        for name in ('user_config_storage', 'xweb_user_storage'):
            path = user / 'mmkv' / name / name
            if path.is_file():
                paths.append(path)
    for path in paths:
        items = read_store(path, constant)
        result['stores'].append({
            'name': path.name, 'entries': len(items), 'checksum_valid': True,
            'home_local_data_present': 'home_local_data' in items,
        })
        if path.name == 'xweb_global_storage':
            result['devtools_preference_present'] = 'global_auto_launch_devtools' in items
        if path.name != 'xweb_user_storage':
            continue
        for name, value in items.items():
            if not name.startswith('ilink_res_info_') or b'"project_name":"subscription"' not in value:
                continue
            encoded, end = block(value, 0)
            if end != len(value):
                raise ValueError('Unexpected resource record encoding')
            entry = json.loads(encoded)
            package = Path(entry['file_path'])
            if not package.resolve().is_relative_to(ROOT.resolve()):
                raise ValueError('Unexpected resource path')
            result['subscription_resources'].append({
                'project_id': entry['project_id'], 'package_version': package.parent.name,
                'package_exists': package.is_file(),
                'package_sha256': hashlib.sha256(package.read_bytes()).hexdigest() if package.is_file() else None,
            })
    return result


if __name__ == '__main__':
    print(json.dumps(report(), ensure_ascii=False, indent=2))
