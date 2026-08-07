# ebook2audiobook Android thin client

A minimal Kivy app that runs entirely on the phone but performs no heavy work:
it collects the same settings as the desktop "Cloud" tab, encodes them into a
base64url JSON string and opens the Google Colab notebook in the browser. The
TTS/translation runs on the free Colab GPU.

## TTS engines available on the phone

The app only lists engines that work in Colab **without any extra setup** (they
are pip-installed from `requirements.txt`):

- **XTTSv2** (default), **BARK**, **VITS**, **FAIRSEQ**, **TACOTRON2**, **YOURTTS**
  — provided by `coqui-tts[languages]==0.26.0`;
- **KOKORO** — provided by `kokoro>=0.9.2`.

**COSYVOICE** and **MOSSTTSNANO** are intentionally omitted: they need the
`./CosyVoice` and `./MOSS-TTS-Nano` repos (gitignored, not cloned by the Colab
notebook), so they fail on a phone with `No module named 'cosyvoice'` /
`No module named 'onnx_tts_runtime'` unless those repos are set up manually.

## Building the APK

Buildover only runs on Linux, so the APK is built on a free Google Colab machine
using [`Notebooks/build_android_apk.ipynb`](../Notebooks/build_android_apk.ipynb).

## Permanent signing key (in-place updates)

The APK is signed with the **permanent keystore** that lives on your Google
Drive (not in git, for security). The keystore is shared as a link and the
build notebook (`Notebooks/build_android_apk.ipynb`) downloads it via `gdown`
into `android_client/` automatically before `buildozer` runs.

To configure the keystore link, edit cell (2) of the notebook and set
`KEY_FILE_ID` to the id from your Google Drive share link (the part after
`/file/d/` or `?id=`). The file must be shared as **"Anyone with the link"**.

Keystore details:
- store/key alias: `ebook2audiobook`
- store/key password: `ebook2audiobook`
Because the same keystore is used for **every** build, all APKs share the same
signature. Android therefore treats a newer APK installed over an older one as an
**update** — users do **not** have to uninstall and reinstall the client.

### Why this matters

Without a fixed keystore, `buildozer android debug` signs with a throwaway
per-machine debug keystore (`~/.android/debug.keystore`). Every fresh Colab
runtime generates a *different* key, so each new APK would have a different
signature and Android would refuse the in-place install ("App not installed"),
forcing users to uninstall/reinstall.

### Rules to keep updates working

1. **Never lose or replace this keystore.** If it is regenerated, existing
   installs can no longer be updated in place. Back it up on Google Drive.
2. **Keep it secret.** Anyone with this keystore + password can release an APK
   that overwrites your app. Never commit it to git (it is gitignored).
3. **Bump the version for each release** in `buildozer.spec`:
   - `version` (human readable, e.g. `1.2.0`)
   - `version.code` (monotonic integer Android compares, e.g. `3`)
   Android refuses to install an "update" whose `version.code` is not higher.

### Related buildozer.spec settings

```ini
android.sign_key = ebook2audiobook
android.keystore = %(source.dir)s/ebook2audiobook-release.keystore
android.storepass = ebook2audiobook
android.keyalias = ebook2audiobook
android.keypass = ebook2audiobook
