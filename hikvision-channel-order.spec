# -*- mode: python ; coding: utf-8 -*-
# Lean onefile GUI build: stdlib + tkinter only.

block_cipher = None

# Keep the bundle small: drop test / packaging / unused stdlib heavyweights.
excludes = [
    "pytest",
    "unittest",
    "pydoc",
    "doctest",
    "pdb",
    "difflib",
    "numpy",
    "pandas",
    "PIL",
    "Pillow",
    "matplotlib",
    "scipy",
    "IPython",
    "jupyter",
    "setuptools",
    "pkg_resources",
    "distutils",
    "email.mime",
    "xmlrpc",
    "multiprocessing.popen_spawn_posix",
]

a = Analysis(
    ["channel_gui.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=["channel_core"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="HikvisionChannelOrder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
