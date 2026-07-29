[app]
# ebook2audiobook Android thin client: collects settings and opens the
# Colab notebook in the browser. Built in Colab (Notebooks/build_android_apk.ipynb),
# buildozer does not run on Windows.
title = ebook2audiobook
package.name = ebook2audiobook_client
package.domain = org.tarkas
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/icon.png
version = 1.0

requirements = python3,kivy==2.3.0,pyjnius

orientation = portrait
fullscreen = 0

# Android 10/11 target per project requirements
android.api = 30
android.minapi = 29
android.ndk_api = 29
# arm64 covers all Android 10/11 phones; single arch = faster, simpler build
android.archs = arm64-v8a
android.permissions = INTERNET

# Accept SDK licenses automatically inside CI/Colab
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0
