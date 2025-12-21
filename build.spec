# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        # 如需打包 VC++ 运行库，取消下面注释
        # ('C:/Windows/System32/msvcp140.dll', '.'),
        # ('C:/Windows/System32/vcruntime140.dll', '.'),
        # ('C:/Windows/System32/vcruntime140_1.dll', '.'),
    ],
    datas=[
        ('templates', 'templates'),  # 包含模板图片
        ('settings.ini', '.'),       # 包含设置文件
    ],
    hiddenimports=[
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
        'cv2',
        'numpy',
        'mss',
        'keyboard',
        'win32gui',
        'win32con',
        'win32api',
        'win32process',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 文件夹模式（非单文件）
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # 文件夹模式
    name='苗圃助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # 可以添加图标: icon='icon.ico'
)

# 收集所有文件到文件夹
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='苗圃助手',
)
