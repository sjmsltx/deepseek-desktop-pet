# -*- mode: python ; coding: utf-8 -*-
"""DeepSeekPet 打包 spec

⚠️ 为什么有 SKIP 清单（2026-09-21 实测教训）：
    `collect_all('PySide6')` 会把整份 PySide6 都收进来，包括本应用**完全用不到**的
    Qt WebEngine（Qt6WebEngineCore.dll 195 MB + qtwebengine resources 72+44 MB）、ICU（约 45 MB）、
    QML（约 18 MB）、Qt3D / QtDesigner / QtCharts / QtMultimedia(ffmpeg) 等 →
    包体从 ~210 MB 直接涨到 445.6 MB（打包自检通过，但用户下载成本翻倍）。
    本应用是纯 widgets + OpenGL 的桌面程序，所以下面按清单排除，并要求打包后**包内体积 ≈ 210 MB** 作为回归基线。
"""
from PyInstaller.utils.hooks import collect_all

# 用不到的 Qt 模块（excludes 让 PyInstaller 不分析它们的 Python 绑定与插件）
SKIP_MODULES = [
    'QtWebEngineCore', 'QtWebEngineWidgets', 'QtWebEngineQuick',
    'QtQml', 'QtQmlModels', 'QtQmlCompiler', 'QtQuick', 'QtQuick3D', 'QtQuickControls2', 'QtQuickTest',
    'Qt3DCore', 'Qt3DRender', 'Qt3DAnimation', 'Qt3DExtras', 'Qt3DInput', 'Qt3DLogic', 'Qt3DQuick',
    'QtDesigner', 'QtDesignerComponents', 'QtCharts', 'QtGraphs', 'QtGraphsWidgets', 'QtDataVisualization',
    'QtMultimedia', 'QtMultimediaWidgets', 'QtPdf', 'QtPdfWidgets', 'QtSql', 'QtTest', 'QtBluetooth',
    'QtNfc', 'QtSerialPort', 'QtSerialBus', 'QtSensors', 'QtRemoteObjects', 'QtScxml', 'QtSpatialAudio',
    'QtWebSockets', 'QtWebChannel', 'QtWebView', 'QtLocation', 'QtPositioning', 'QtHelp', 'QtUiTools',
    'QtAsyncio', 'QtAxContainer', 'QtHttpServer', 'QtNetworkAuth', 'QtTextToSpeech', 'QtCanvasPainter',
]
excludes = ['PySide6.' + m for m in SKIP_MODULES]

# collect_all 之后按路径片段过滤掉用不到的重量级件
SKIP_PATH_PARTS = (
    '/PySide6/qml/', 'PySide6/qml',
    '/QtWebEngine', 'Qt6WebEngine',
    'resources/qtwebengine', 'translations/qtwebengine',
    'icudt', 'icuin', 'icuuc',
    'Qt6Quick', 'Qt6Qml', 'Qt63D', 'Qt6Designer', 'Qt6Charts', 'Qt6Graphs', 'Qt6DataVisualization',
    'Qt6Multimedia', 'Qt6Pdf', 'Qt6Sql', 'Qt6Test', 'Qt6Bluetooth', 'Qt6Nfc', 'Qt6SerialPort',
    'Qt6SerialBus', 'Qt6Sensors', 'Qt6RemoteObjects', 'Qt6Scxml', 'Qt6SpatialAudio', 'Qt6Location',
    'Qt6Positioning', 'Qt6Help', 'Qt6UiTools', 'Qt6WebSockets', 'Qt6WebChannel', 'Qt6WebView',
    'Qt6NetworkAuth', 'Qt6TextToSpeech', 'Qt6CanvasPainter', 'Qt6HttpServer',
    'avcodec-', 'avformat-', 'avutil-', 'swscale-', 'swresample-',
    '/sqldrivers/',
    'qmllint', 'qmlls', 'qmlformat', 'qmltestrunner', 'qtdiag', 'designer.exe', 'linguist.exe',
    'assistant.exe', 'pyside6-designer', 'pyside6-linguist', 'pyside6-qml',
)


def _keep(entry):
    p = str(entry[0]).replace('\\', '/')
    return not any(s in p for s in SKIP_PATH_PARTS)


datas = []
binaries = []
hiddenimports = ['pythoncom', 'pywintypes']
for pkg in ('PySide6', 'shiboken6', 'edge_tts', 'win32com'):
    d, b, h = collect_all(pkg)
    datas += [x for x in d if _keep(x)]
    binaries += [x for x in b if _keep(x)]
    hiddenimports += h


a = Analysis(
    ['..\\desktop_pet.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# ★ 关键：再过滤一次 —— 2026-09-21 实测教训：
#   只在 collect_all 后过滤没用，PyInstaller 的 PySide6 hook 会在 **Analysis 阶段**
#   把 Qt6WebEngineCore.dll（195 MB）、icudt78.dll（32 MB）等再收回来，
#   第一次实测包体 445.6 MB（过滤前）→ 342.1 MB（只过滤 collect_all，WebEngine 仍在）→ 目标 ~210 MB。
#   所以必须在 Analysis 产出后对 a.binaries / a.datas 再篩一遭。
a.binaries = [x for x in a.binaries if _keep(x)]
a.datas = [x for x in a.datas if _keep(x)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DeepSeekPet',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DeepSeekPet',
)
