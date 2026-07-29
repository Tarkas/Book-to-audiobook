# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec for the ebook2audiobook Windows folder build.

Build:  .\\env\\Scripts\\python.exe -m PyInstaller ebook2audiobook.spec --noconfirm
Result: dist/ebook2audiobook/  (run ebook2audiobook.exe from that folder)

Heavy TTS models are NOT bundled: they download into models/ next to the exe on
first use, exactly like the source checkout. External tools (calibre, ffmpeg,
espeak-ng) are expected on the system as before.
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

block_cipher = None
project_dir = os.path.abspath('.')

datas = [
    ('VERSION.txt', '.'),
    ('app_icon.png', '.'),
    ('lib', 'lib'),
    ('DeeplParser-main', 'DeeplParser-main'),
]
binaries = []
hiddenimports = [
    'tkinter_ui',
    'lib.improved_translator',
    'lib.language_codes',
    'lib.deepl_wrapper',
    'lib.deepl_parser',
    'lib.translation_manager',
    'lib.translation_exceptions',
    # TTS engine classes are imported dynamically by tts_manager
    'lib.classes.tts_engines.coqui',
    'lib.classes.tts_engines.bark',
    'lib.classes.tts_engines.vits',
    'lib.classes.tts_engines.fairseq',
    'lib.classes.tts_engines.tacotron2',
    'lib.classes.tts_engines.yourtts',
    'lib.classes.tts_engines.kokoro',
    'lib.classes.tts_engines.mosstts_nano',
    'lib.classes.tts_engines.cosyvoice',
]

# Packages that need their full data/metadata trees, or are imported lazily and
# would otherwise be missed by static analysis.
for pkg in (
    'gradio', 'gradio_client', 'safehttpx', 'groovy',
    'TTS', 'stanza', 'espeakng_loader',
    'argostranslate', 'deep_translator', 'deepl',
    'num2words', 'iso639', 'unidic', 'sudachipy', 'sudachidict_core',
    'pythainlp', 'soynlp', 'jieba', 'pypinyin', 'hangul_romanize', 'cutlet',
    'ebooklib', 'pymupdf4llm', 'pymupdf', 'markdown',
    'charset_normalizer', 'kokoro', 'misaki',
    'torch', 'torchaudio', 'transformers', 'tokenizers',
    'librosa', 'scipy', 'sklearn', 'gruut', 'anyascii', 'inflect',
    'pydub', 'soundfile', 'audioread', 'noisereduce', 'pyannote',
    'speechbrain', 'onnxruntime', 'uvicorn', 'starlette', 'fastapi',
    'lightning_fabric', 'pytorch_lightning',  # need their version.info data files
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f'spec: skipping {pkg}: {e}')

for pkg in ('gradio', 'gradio_client', 'coqui-tts', 'transformers', 'tqdm',
            'regex', 'requests', 'packaging', 'filelock', 'numpy', 'torch'):
    try:
        datas += copy_metadata(pkg)
    except Exception as e:
        print(f'spec: no metadata for {pkg}: {e}')

a = Analysis(
    ['windows_launcher.py'],
    pathex=[project_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['env', 'audiblez', 'CosyVoice', 'MOSS-TTS-Nano'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    module_collection_mode={'gradio': 'py'},  # gradio breaks when bytecode-frozen
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ebook2audiobook',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # keep the console: conversion progress is printed there
    icon='app_icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='ebook2audiobook',
)
