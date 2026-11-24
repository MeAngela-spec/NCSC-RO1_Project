# Build on Windows x64 with Python 3.12.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parent
datas = [(str(root / name), name) for name in ('assets', 'templates', 'samples')]
datas += [(str(root / name), '.') for name in ('index.html', 'printing.html', 'print-with-word.ps1',
    'START-HERE.txt', 'DESKTOP-GUIDE.md', 'THIRD-PARTY-NOTICES.md')]
datas += [(str(root / 'build/bundle-info.json'), '.'),
          (str(root / 'build/libreoffice'), 'libreoffice')]
license_file = Path(sys.base_prefix) / 'LICENSE.txt'
if license_file.exists():
    datas.append((str(license_file), 'licenses/python'))
binaries, hiddenimports = [], []
for package in ('docx', 'openpyxl', 'pdfplumber', 'pdfminer', 'olefile', 'pypdfium2', 'pypdfium2_raw'):
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden
for distribution in ('python-docx', 'openpyxl', 'pdfplumber', 'olefile', 'pypdfium2',
                     'Pillow', 'lxml', 'cryptography', 'cffi'):
    datas += copy_metadata(distribution, recursive=True)
a = Analysis([str(root / 'desktop.py')], pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[], excludes=['pytest'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='NCSCRO1', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    icon=str(root / 'assets/ncsc.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='NCSCRO1')
