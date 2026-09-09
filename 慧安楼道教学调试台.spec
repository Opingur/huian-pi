# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [
    ('teaching_console/assets/huian_logo.png', '.'),
    # Seed the packaged display with the router-free Pi hotspot endpoint.
    ('teacher_remote.json', 'huian_teaching_data'),
    # Authorized for trusted offline demonstration PCs: lets local vision relay
    # alarms to the Pi, which retains sole UART control of the ESP32.
    ('showcase_bridge.json', 'huian_teaching_data'),
    # Keep source files beside the EXE so the source-map and open-source tools work.
    ('teaching_console', 'teaching_console'),
    ('teaching_examples', 'teaching_examples'),
    ('rpi_app', 'rpi_app'),
    ('esp32_firmware', 'esp32_firmware'),
    ('models', 'models'),
    ('test_data', 'test_data'),
    ('展示端正式视频素材', '展示端正式视频素材'),
    ('validation/README.md', 'validation'),
    ('validation/templates', 'validation/templates'),
    ('validation/scripts', 'validation/scripts'),
    ('training', 'training'),
]
binaries = []
hiddenimports = ['ultralytics.trackers.byte_tracker']
tmp_ret = collect_all('ultralytics')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('serial')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['teaching_console/main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='慧眼疏流安全检测系统',
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
    icon=['teaching_console/assets/huian_logo.ico'],
    contents_directory='.',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='慧眼疏流安全检测系统',
)
