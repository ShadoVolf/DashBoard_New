# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, collect_data_files


# ---------------------------------------------------------------------------
# hiddenimports:
#   * подмодули проекта (кроме train_models — обучение в exe не нужно);
#   * динамически подгружаемые пакеты (pyvisa-py, serial, mysql, PIL);
#   * условный импорт scipy.stats (используется в Virtual_Stats).
# ---------------------------------------------------------------------------
hiddenimports = (
    collect_submodules('pyvisa_py')
    + collect_submodules('serial')
    + collect_submodules('sqlalchemy.dialects.mysql')
    + collect_submodules('matplotlib.backends')
    + collect_submodules('PIL')
    + collect_submodules('Temperature_Measure')
    + collect_submodules('Archive_View')
    + collect_submodules('Authorization')
    + collect_submodules('Assistant')         # ← НОВОЕ, с большой A
    + collect_submodules('Statistik')         # ← НОВОЕ (dashboard_llm и др.)
    + collect_submodules('ResonatorGraph')    # ← НОВОЕ (graph_tools/controller)
    + [
        # Подмодули Virtual_Measure явно (train_models намеренно пропущен)
        'Virtual_Measure.Virtual_Data',
        'Virtual_Measure.Virtual_Stats',
        'Virtual_Measure.Virtual_Window',
        'Virtual_Measure.Virtual_Settings',
        'Virtual_Measure.Virtual_NN',

        # Верхнеуровневые модули проекта
        'window_manager',
        'Options',

        # Динамически подключаемые C-расширения/протоколы
        'pyvisa_py.protocols.hislip',
        'pyvisa_py.protocols.vxi11',
        'pyvisa_py.protocols.usbtmc',
        'pyvisa_py.protocols.serial',
        'dearpygui.dearpygui',
        'numpy.core._multiarray_umath',
        'mysql.connector',
        'pymysql',
        'pyodbc',
        'screeninfo',

        # Условный импорт в Virtual_Stats
        'scipy.stats',
        'scipy.stats._stats',
    ]
)


# ---------------------------------------------------------------------------
# Исключения:
#   * torch — обучение в exe не запускается, весит гигабайты;
#   * train_models — не нужен в рантайме;
#   * крупные ML-фреймворки, которые иногда «подтягиваются» через scipy.
# ---------------------------------------------------------------------------
excludes = [
    'torch',
    'torchvision',
    'torchaudio',
    'tensorflow',
    'Virtual_Measure.train_models',
]


# ---------------------------------------------------------------------------
# datas:
#   Файлы моделей (.npz) НЕ включаются — читаем из virtual_nn_models.
#   virtual_settings.json намеренно не пакуется: он должен быть
#   изменяемым (создастся из DEFAULT_SETTINGS при первом запуске).
#   Если есть картинки/шрифты — раскомментировать.
# ---------------------------------------------------------------------------
datas = []
# datas += [('Pictures', 'Pictures')]
# datas += [('fonts', 'fonts')]
# datas += [('morion_40.ico', '.')]


a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# ---------------------------------------------------------------------------
# Страховка: если какие-то .npz попали в бандл (например, из models/),
# выкидываем их ДО передачи в Splash/EXE.
# ---------------------------------------------------------------------------
a.datas    = [d for d in a.datas    if not d[0].lower().endswith('.npz')]
a.binaries = [b for b in a.binaries if not b[0].lower().endswith('.npz')]


pyz = PYZ(a.pure)

splash = Splash(
    'morion.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
    [],
    name='Measure',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['morion_40.ico'],
    hide_console=None,
)