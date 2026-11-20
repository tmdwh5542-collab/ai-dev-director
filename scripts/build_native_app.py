"""Build only the Windows GUI shell; keep backend Python available for verification jobs."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def build():
    if os.name != 'nt':
        raise RuntimeError('Windows EXE는 Windows에서 빌드해야 합니다.')
    from PIL import Image, ImageDraw
    work = ROOT / 'build' / 'native'
    work.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, 255, 255), radius=56, fill='#101719')
    draw.rounded_rectangle((65, 58, 202, 198), radius=58, fill='#86efc5')
    draw.rectangle((65, 58, 121, 198), fill='#86efc5')
    draw.rounded_rectangle((103, 92, 164, 164), radius=28, fill='#101719')
    draw.ellipse((190, 41, 216, 67), fill='#e5fff3')
    icon = work / 'director.ico'
    image.save(icon, sizes=[(16, 16), (32, 32), (48, 48), (128, 128), (256, 256)])
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
        '--name', 'AI-DEV-DIRECTOR', '--icon', str(icon),
        '--distpath', str(ROOT / 'native'), '--workpath', str(work / 'pyinstaller'),
        '--specpath', str(work), '--add-data', str(ROOT / 'assets') + os.pathsep + 'assets',
        '--hidden-import', 'PySide6.QtSvg', str(ROOT / 'native_app.py'),
    ], cwd=str(ROOT), check=True)
    executable = ROOT / 'native' / 'AI-DEV-DIRECTOR' / 'AI-DEV-DIRECTOR.exe'
    if not executable.is_file():
        raise RuntimeError('전용 앱 실행 파일이 생성되지 않았습니다.')
    return executable


if __name__ == '__main__':
    print(build())
