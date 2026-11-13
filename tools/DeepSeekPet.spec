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

# 2026-11-13：排除**与桌宠无关**的重量级库。
#
# 起因：v3.0.3 打完 554.3 MB（解压 1256 MB），v3.0.2 是 223.7 / 383。
#   多出来的全是 torch 361 + llvmlite 115 + cv2 111 + scipy 72 + transformers 36
#   + sklearn 12 + pandas 13 + matplotlib 12（单位 MB，解压后）。
#
# 根因：11-06 接入向量检索（memory_embed）后 import onnxruntime / tokenizers，
#   PyInstaller 顺着 hook 把 transformers → torch → torchvision 整条链收了进来。
#   **源码里一处都没有 import torch / transformers / sklearn / pandas / llvmlite**，
#   全仓扫描确认过。
#
# 关键：向量检索要模型文件（models/bge-small-zh-v1.5/model.onnx），
#   而 .gitignore 排除了它 ⇒ 包里本来就没有模型 ⇒ 打包版一直走 BM25 降级。
#   即这 730 MB 是「为一个在包里跑不起来的组件带的行李」。
#
# 保留 onnxruntime + tokenizers + numpy（约 67 MB）：
#   用户自己放模型（PET_EMBED_DIR）时向量检索仍可用。
#
# ⚠ scipy：只有 collab/asset_ops.py 与 eval 脚本用；collab_panel 是点菜单才加载的
#   辅助工具，不在桌宠主路径上。真需要时会 ImportError 并在提示里显形，不静默。
HEAVY_EXCLUDES = [
    # 深度学习 / NLP —— 一条都不 import
    'torch', 'torchvision', 'torchaudio', 'transformers', 'datasets',
    'accelerate', 'huggingface_hub', 'hf_xet', 'safetensors', 'sentencepiece',
    # 科学计算 / 数据处理 —— 只 memory_embed 用 numpy
    'scipy', 'sklearn', 'pandas', 'matplotlib', 'seaborn', 'plotly', 'bokeh',
    'sympy', 'pyarrow', 'llvmlite', 'numba', 'numpy.f2py', 'numpy.distutils',
    # 其它大件
    'cv2', 'tensorflow', 'keras', 'jax', 'IPython', 'jupyter', 'notebook',
    'pytest', 'sphinx', 'docutils', 'PIL.ImageQt', 'wx',
]
excludes += HEAVY_EXCLUDES

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
# v3.4（2026-10-24）：stats_ui 是**函数内局部 import**（点菜单才加载）。
#   PyInstaller 的 AST 分析能追踪到函数内 import（status_panel 就是同类先例，
#   v3.0.0 包里已在用）；这里再登记一条做双保险，避免「开发能开、打包打不开」。
hiddenimports = ['pythoncom', 'pywintypes', 'stats_ui']
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
