"""Create macOS icon resolutions from the checked-in design using system tools."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parent.parent
assets = root / 'assets'
with tempfile.TemporaryDirectory() as temporary:
    iconset = Path(temporary) / 'AppIcon.iconset'
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            suffix = '@2x' if scale == 2 else ''
            destination = iconset / f'icon_{size}x{size}{suffix}.png'
            subprocess.run(['sips', '-z', str(size * scale), str(size * scale),
                            str(assets / 'AppIcon.png'), '--out', str(destination)],
                           check=True, capture_output=True)
    subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(assets / 'AppIcon.icns')], check=True)
