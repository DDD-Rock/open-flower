# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# 只收集必要的包（numpy和cv2是核心依赖）
numpy_datas, numpy_binaries, numpy_hiddenimports = collect_all('numpy')
cv2_datas, cv2_binaries, cv2_hiddenimports = collect_all('cv2')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=numpy_binaries + cv2_binaries,
    datas=[
        ('templates', 'templates'),
        ('settings.ini', '.'),
    ] + numpy_datas + cv2_datas,
    hiddenimports=[
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
        'mss',
        'keyboard',
        'win32gui',
        'win32con',
        'win32api',
        'win32process',
    ] + numpy_hiddenimports + cv2_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['hooks/runtime_hook.py'],
    excludes=[
        # 未使用的大型包
        'ultralytics',
        'torch',
        'torchvision',
        'tensorflow',
        'matplotlib',
        'pandas',
        'scipy',
        'sklearn',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'PIL',
        'Pillow',
        'psutil',
        'screeninfo',
        # 未使用的依赖
        'pkg_resources',
        'setuptools',
        'jaraco',
        'platformdirs',
        'more_itertools',
        # numpy 测试和文档（很大但不需要）
        'numpy.tests',
        'numpy.doc',
        'numpy.f2py',
        'numpy.distutils',
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
