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
version = 1.1.0
version.code = 2

requirements = python3,kivy==2.3.0,pyjnius

# Pin a known-good toolchain: this p4a release targets Python 3.10 on the
# device, matching kivy 2.3.0 cythonized with Cython 0.29.x. p4a master
# targets Python 3.14 whose C API breaks the kivy build (too few arguments /
# _PyInterpreterState_GetConfig errors).
p4a.branch = release-2024.01.21
android.ndk = 25b

orientation = portrait
fullscreen = 0

# Target Android 11, installable down to Android 5.0 (API 21). minapi MUST
# equal ndk_api: p4a refuses to package when they differ
# ("--minsdk argument does not match the api that is compiled against").
android.api = 30
android.minapi = 21
android.ndk_api = 21
# Fat APK: arm64 for modern phones + 32-bit armeabi-v7a for older ones.
# Builds roughly twice as long, but installs almost everywhere.
android.archs = arm64-v8a, armeabi-v7a
android.permissions = INTERNET

# --- Permanent signing key -----------------------------------------------
# The APK must be signed with a FIXED keystore so that a new build can be
# installed as an UPDATE over the previous one (Android refuses an in-place
# install when the signature differs). Every Colab build uses this same
# committed keystore; the debug keystore (~/.android/debug.keystore) is
# regenerated per machine/runtime and would force users to uninstall/reinstall.
android.sign_key = ebook2audiobook
android.keystore = %(source.dir)s/ebook2audiobook-release.keystore
android.storepass = ebook2audiobook
android.keyalias = ebook2audiobook
android.keypass = ebook2audiobook

# Accept SDK licenses automatically inside CI/Colab
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0
