# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# 收集完整的包
numpy_datas, numpy_binaries, numpy_hiddenimports = collect_all('numpy')
cv2_datas, cv2_binaries, cv2_hiddenimports = collect_all('cv2')
pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all('pkg_resources')
pdir_datas, pdir_binaries, pdir_hiddenimports = collect_all('platformdirs')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=numpy_binaries + cv2_binaries + pkg_binaries + pdir_binaries,
    datas=[
        ('templates', 'templates'),
        ('settings.ini', '.'),
    ] + numpy_datas + cv2_datas + pkg_datas + pdir_datas,
    hiddenimports=[
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
        'mss',
        'keyboard',
        'win32gui',
        'win32con',
        'win32api',
        'win32process',
        'jaraco',
        'jaraco.text',
        'jaraco.functools',
        'jaraco.context',
        'platformdirs',
        'more_itertools',
    ] + numpy_hiddenimports + cv2_hiddenimports + pkg_hiddenimports + pdir_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['hooks/runtime_hook.py'],
    excludes=[
        'ultralytics',
        'torch',
        'torchvision',
        'tensorflow',
        'psutil',
        'screeninfo',
        'matplotlib',
        'pandas',
        'scipy',
        'sklearn',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MapleKeeper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MapleKeeper',
)
