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

# Pin a known-good toolchain: this p4a release targets Python 3.10 on the
# device, matching kivy 2.3.0 cythonized with Cython 0.29.x. p4a master
# targets Python 3.14 whose C API breaks the kivy build (too few arguments /
# _PyInterpreterState_GetConfig errors).
p4a.branch = release-2024.01.21
android.ndk = 25b

orientation = portrait
fullscreen = 0

# Target Android 11, but stay installable down to Android 8.0 (API 26):
# the user's second phone runs Android 8.
android.api = 30
android.minapi = 26
android.ndk_api = 21
# Fat APK: arm64 for modern phones + 32-bit armeabi-v7a for older ones.
# Builds roughly twice as long, but installs almost everywhere.
android.archs = arm64-v8a, armeabi-v7a
android.permissions = INTERNET

# Accept SDK licenses automatically inside CI/Colab
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0
