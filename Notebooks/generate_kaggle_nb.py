#!/usr/bin/env python3
"""Generate Notebooks/kaggle_ebook2audiobook.ipynb from the Colab notebook.

Adapts the Colab notebook for Kaggle Notebooks:
  - no Google Drive -> /kaggle/working/ + optional Kaggle Dataset for state
  - no Colab upload widget -> books come from /kaggle/input/ or /kaggle/working/
  - config via config_b64 field (clipboard from the mobile app), not URL params
  - session budget ~8 hours (Kaggle free GPU limit is ~9h per session)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'colab_ebook2audiobook.ipynb')
DST = os.path.join(HERE, 'kaggle_ebook2audiobook.ipynb')


def to_source(text: str) -> list:
    lines = text.split('\n')
    return [line + '\n' for line in lines[:-1]] + [lines[-1]]


CELL0_MD = r"""# ebook2audiobook - Kaggle Notebooks

Convert a book into an audiobook on a free Kaggle GPU, **in parts** sized for a
Kaggle session. When the last part finishes, the parts are merged into one
audiobook named after the book.

## Setup (one-time)

1. Create a Kaggle account and open this notebook.
2. **Settings** (right panel) -> Accelerator -> **GPU T4 x2**.
3. **Settings** -> Internet -> **On** (needed to clone the repo and pip-install).
4. Optional but recommended for multi-session books: create a private Dataset
   (e.g. `your-name/ebook2audiobook-state`) and attach it via
   **Add Data** -> search for it -> **Attach**. The notebook saves checkpoints
   there so a new session can resume where the previous one stopped.
5. Upload your ebook via **Add Data** -> **Upload** (it appears in
   `/kaggle/input/`), or put it into the attached state dataset.

## Each session

1. Paste the settings string from the mobile app (or desktop Cloud tab)
   into the `config_b64` field of cell (1).
2. Click **Run all**. The book is split into parts of ~2 hours of audio and
   converted one after another.
3. When the session budget is reached (or the book is finished), the final
   audiobook appears in `/kaggle/working/output/final/` - download it from
   the **Output** tab on the right.

## Resuming on the next day

Open this notebook, attach the same state dataset, paste the same settings
and **Run all** again. Finished parts are skipped; the unfinished part
resumes from its last sentence-level checkpoint.

**Kaggle free-tier tips**

- GPU quota is 30 hours per week; a session can run up to ~12 hours (GPU ~9h).
- `session_budget_minutes` in cell (1) stops the loop before the session is
  killed. It is safe to stop at any moment: progress is checkpointed.
- The state dataset only stores checkpoints and plan metadata (tens of MB),
  not the finished audio - download finished parts from the Output tab.
- To convert a **different** book, upload it via Add Data and re-run; a fresh
  upload always wins over automatic resume. You can also delete the old plan
  folder inside the state dataset.
"""

CELL1_CODE = r'''#@title (1) Settings, book selection and resume point { display-mode: "form" }
config_b64 = ""  #@param {type:"string"}
book_filename = ""  #@param {type:"string"}
state_dataset = ""  #@param {type:"string"}
part_audio_hours = 2.0  #@param {type:"number"}
chars_per_minute = 900  #@param {type:"number"}
session_budget_minutes = 480  #@param {type:"number"}

import base64, glob, hashlib, json, os, re, shutil

try:
    part_audio_hours = float(part_audio_hours)
    chars_per_minute = int(chars_per_minute)
    session_budget_minutes = float(session_budget_minutes)
except (TypeError, ValueError):
    raise SystemExit("part_audio_hours, chars_per_minute and session_budget_minutes must be numbers.")
if part_audio_hours <= 0 or chars_per_minute <= 0:
    raise SystemExit("part_audio_hours and chars_per_minute must be positive.")
if session_budget_minutes <= 0:
    session_budget_minutes = 480

def _decode_cfg(b64):
    if not b64:
        return {}
    b64 = b64.strip().strip('"\'')
    if '://' in b64 or 'c=' in b64:
        import urllib.parse as _up
        _query = _up.urlparse(b64).query or b64.split('?', 1)[-1]
        _value = _up.parse_qs(_query).get('c')
        if _value:
            b64 = _value[0]
    b64 = b64.strip()
    b64 += "=" * (-len(b64) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(b64.encode('ascii')).decode('utf-8'))
    except Exception as _e:
        print("Could not decode the config string:", _e)
        print("Paste the code copied by the mobile app into config_b64.")
        return {}

CFG = _decode_cfg(config_b64)
globals()['CFG'] = CFG
if CFG:
    print("Settings received from the app:")
    print(json.dumps(CFG, ensure_ascii=False, indent=2))
else:
    print("No settings received - defaults will be used.")

# --- Storage layout on Kaggle -------------------------------------------
# /kaggle/working/  is wiped after each session.
# An attached state Dataset provides cross-session persistence: the notebook
# reads checkpoints from /kaggle/input/<dataset>/ at start and writes them
# back (new Dataset version) at the end.
WORKING_DIR = '/kaggle/working'
os.makedirs(WORKING_DIR, exist_ok=True)

STATE_INPUT_DIR = ''
if state_dataset:
    # The user typed the slug manually or the notebook auto-detected it.
    slug = state_dataset.strip().strip('/')
    candidate = os.path.join('/kaggle/input', slug.replace('/', '-'))
    if os.path.isdir(candidate):
        STATE_INPUT_DIR = candidate
    else:
        # Try to find any attached dataset whose directory contains a plans/ folder.
        for d in sorted(glob.glob('/kaggle/input/*')):
            if os.path.isdir(os.path.join(d, 'plans')):
                STATE_INPUT_DIR = d
                break

BASE_DIR = os.path.join(WORKING_DIR, 'state')
os.makedirs(BASE_DIR, exist_ok=True)

if STATE_INPUT_DIR:
    print(f"State dataset found: {STATE_INPUT_DIR}")
    # Copy state from the input dataset into the working dir so the plan
    # logic can mutate it freely; it is uploaded back at the end.
    # The upload puts plans/ at the dataset root, so look for it there first.
    _plans_src = os.path.join(STATE_INPUT_DIR, 'plans')
    _state_src = os.path.join(STATE_INPUT_DIR, 'ebook2audiobook')
    if os.path.isdir(_plans_src):
        shutil.copytree(_plans_src, os.path.join(BASE_DIR, 'plans'), dirs_exist_ok=True)
        print("Existing plans restored from the dataset.")
    elif os.path.isdir(_state_src):
        shutil.copytree(_state_src, BASE_DIR, dirs_exist_ok=True)
        print("Existing state restored from the dataset.")
    else:
        print("State dataset attached but contains no plans/ folder - starting fresh.")
else:
    print("No state dataset attached - progress lives only in /kaggle/working")
    print("and will be LOST when the session ends. To enable resume across")
    print("sessions, attach a Kaggle Dataset (see the instructions above).")

PLANS_DIR = os.path.join(BASE_DIR, 'plans')
os.makedirs(PLANS_DIR, exist_ok=True)

def _number(value):
    if value is None or value == '':
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None

def _settings_payload(book_sha1=''):
    language = str(CFG.get('language') or 'eng')
    return {
        'book_sha1': book_sha1,
        'part_audio_minutes': round(part_audio_hours * 60.0, 3),
        'chars_per_minute': int(chars_per_minute),
        'language': language,
        'output_format': str(CFG.get('output_format') or 'm4b').lower(),
        'tts_engine': str(CFG.get('tts_engine') or ''),
        'voice': str(CFG.get('voice') or ''),
        'speed': _number(CFG.get('speed')),
        'temperature': _number(CFG.get('temperature')),
        'repetition_penalty': _number(CFG.get('repetition_penalty')),
        'translate': bool(CFG.get('translate')),
        'source_lang': str(CFG.get('source_lang') or ''),
        'target_lang': str(CFG.get('target_lang') or CFG.get('language') or ''),
        'translation_method': str(CFG.get('translation_method') or ''),
    }

def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))

def _sha1_file(path):
    digest = hashlib.sha1()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def _book_key(source_sha1, name):
    slug = re.sub(r'[^A-Za-z0-9._-]+', '-', os.path.splitext(os.path.basename(name))[0])
    slug = re.sub(r'-+', '-', slug).strip('-._')[:40] or 'book'
    return source_sha1[:12] + '-' + slug

def _plan_id(settings):
    return hashlib.sha1(_canonical(settings).encode('utf-8')).hexdigest()[:12]

def _read_json(path):
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        return None

def _plan_states():
    rows = []
    for state_path in glob.glob(os.path.join(PLANS_DIR, '*', '*', 'state.json')):
        state = _read_json(state_path)
        if isinstance(state, dict):
            rows.append((state_path, state))
    return rows

def _source_in_plan(plan_dir, state):
    source_dir = os.path.join(plan_dir, 'source')
    candidates = []
    name = (state or {}).get('source_name')
    if name:
        candidates.append(os.path.join(source_dir, name))
    if os.path.isdir(source_dir):
        try:
            candidates += [os.path.join(source_dir, n) for n in sorted(os.listdir(source_dir))]
        except OSError:
            pass
    for path in candidates:
        if os.path.isfile(path):
            return os.path.abspath(path)
    return ''

CURRENT_SETTINGS = _settings_payload('')
_CURRENT_MATCH = {k: v for k, v in CURRENT_SETTINGS.items() if k != 'book_sha1'}

def _settings_match(state):
    stored = state.get('settings')
    if not isinstance(stored, dict):
        return False
    return {k: v for k, v in stored.items() if k != 'book_sha1'} == _CURRENT_MATCH

def _unfinished_plans(source_sha1=None):
    found = []
    for state_path, state in _plan_states():
        if state.get('status') == 'completed' or not _settings_match(state):
            continue
        if source_sha1 and state.get('source_sha1') != source_sha1:
            continue
        plan_dir = os.path.dirname(state_path)
        source = _source_in_plan(plan_dir, state)
        if not source:
            continue
        found.append((str(state.get('updated_at') or ''), state_path, state, source))
    found.sort(key=lambda row: row[0], reverse=True)
    return found

EBOOK_EXTS = ('epub', 'mobi', 'azw3', 'azw', 'pdf', 'txt', 'rtf', 'docx',
              'doc', 'html', 'htm', 'fb2', 'md', 'odt')

def _find_books():
    """Search /kaggle/input/ and /kaggle/working/ for ebook files."""
    found = []
    search_roots = []
    # Files uploaded via Add Data -> Upload appear directly in /kaggle/input/<name>/
    for d in sorted(glob.glob('/kaggle/input/*')):
        if os.path.isdir(d):
            search_roots.append(d)
    # Files the user placed into /kaggle/working/ (rare but possible).
    search_roots.append(WORKING_DIR)
    for root in search_roots:
        for ext in EBOOK_EXTS:
            found += [p for p in glob.glob(os.path.join(root, '*.' + ext))
                      if os.path.isfile(p)]
    # Also include sources already stored in plans (for resume).
    for state_path, state in _plan_states():
        source = _source_in_plan(os.path.dirname(state_path), state)
        if source:
            found.append(source)
    # Deduplicate by (name, size), keep the newest.
    unique = {}
    for path in found:
        try:
            key = (os.path.basename(path).lower(), os.path.getsize(path))
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if key not in unique or mtime > unique[key][0]:
            unique[key] = (mtime, path)
    return [row[1] for row in sorted(unique.values(), key=lambda row: row[0], reverse=True)]

EBOOK = ''
SELECTED_STATE = None
SELECTED_PLAN_DIR = ''

# Priority: explicit book_filename > unfinished plan > newest book found.
if book_filename:
    needle = book_filename.strip().lower()
    for path in _find_books():
        if needle in os.path.basename(path).lower():
            EBOOK = path
            break
    if not EBOOK:
        raise SystemExit(f"book_filename='{book_filename}' did not match any file in /kaggle/input or /kaggle/working.")

if not EBOOK:
    # Check for an unfinished plan whose source is still available.
    matches = _unfinished_plans()
    if matches:
        _, state_path, SELECTED_STATE, EBOOK = matches[0]
        SELECTED_PLAN_DIR = os.path.dirname(state_path)
        print("\nUnfinished plan found - resuming it automatically.")
        print("Book:", EBOOK)

if not EBOOK:
    books = _find_books()
    # Exclude files that are already plan sources (those were handled above).
    plan_sources = set()
    for state_path, state in _plan_states():
        s = _source_in_plan(os.path.dirname(state_path), state)
        if s:
            plan_sources.add(os.path.abspath(s))
    books = [b for b in books if os.path.abspath(b) not in plan_sources]
    if books:
        EBOOK = books[0]
        print("\nBooks found:")
        for _i, _path in enumerate(books[:10], 1):
            print(f"  {_i}. {os.path.basename(_path)}  ({_path})")
        if len(books) > 1:
            try:
                _answer = input(
                    "Press Enter to convert the first book, "
                    "or type its number: "
                ).strip()
            except Exception:
                _answer = ''
            if _answer.isdigit() and 1 <= int(_answer) <= len(books):
                EBOOK = books[int(_answer) - 1]

if not EBOOK or not os.path.isfile(EBOOK):
    raise SystemExit(
        "No ebook found. Upload it via Add Data -> Upload (or put it into the "
        "state dataset), set book_filename in cell (1), and re-run this cell."
    )

EBOOK = os.path.abspath(EBOOK)
BOOK_HASH = _sha1_file(EBOOK)
BOOK_NAME = os.path.basename(EBOOK)
BOOK_KEY = _book_key(BOOK_HASH, BOOK_NAME)
CUR_SETTINGS = _settings_payload(BOOK_HASH)
PART_AUDIO_MINUTES = round(part_audio_hours * 60.0, 3)

if SELECTED_STATE:
    PLAN_ID = str(SELECTED_STATE.get('plan_id') or _plan_id(CUR_SETTINGS))
    PLAN_DIR = SELECTED_PLAN_DIR or os.path.join(PLANS_DIR, BOOK_KEY, PLAN_ID)
else:
    PLAN_ID = _plan_id(CUR_SETTINGS)
    PLAN_DIR = os.path.join(PLANS_DIR, BOOK_KEY, PLAN_ID)

EXISTING_STATE = _read_json(os.path.join(PLAN_DIR, 'state.json'))

print("\n" + "=" * 70)
print("Book:       ", EBOOK)
print("Storage:    ", BASE_DIR)
print("Plan:       ", PLAN_ID)
print("Part size:  ", f"{PART_AUDIO_MINUTES:.0f} min of audio "
                       f"(~{int(PART_AUDIO_MINUTES * chars_per_minute):,} characters)")
if STATE_INPUT_DIR:
    print("Resume:     ", "state dataset attached - progress survives sessions")
else:
    print("Resume:     ", "NO state dataset - progress is lost when the session ends")
if EXISTING_STATE:
    _parts = EXISTING_STATE.get('parts') or {}
    _done = sum(1 for entry in _parts.values() if entry.get('status') == 'done')
    _total = int(EXISTING_STATE.get('total_parts') or len(_parts))
    if EXISTING_STATE.get('status') == 'completed':
        print("Status:      COMPLETED - this plan is already finished.")
        print("             To convert it again, delete the plan folder and re-run.")
    else:
        print("Progress:   ", f"{_done}/{_total or '?'} parts finished - will continue.")
else:
    print("Status:       a new plan will be created.")
print("=" * 70)

globals().update({
    'EBOOK': EBOOK,
    'BOOK_HASH': BOOK_HASH,
    'BOOK_NAME': BOOK_NAME,
    'BOOK_KEY': BOOK_KEY,
    'CUR_SETTINGS': CUR_SETTINGS,
    'PLAN_ID': PLAN_ID,
    'PLAN_DIR': PLAN_DIR,
    'PART_AUDIO_MINUTES': PART_AUDIO_MINUTES,
    'CHARS_PER_MINUTE': int(chars_per_minute),
    'SESSION_BUDGET_MINUTES': float(session_budget_minutes),
    'BASE_DIR': BASE_DIR,
    'PLANS_DIR': PLANS_DIR,
    'STATE_INPUT_DIR': STATE_INPUT_DIR,
    'WORKING_DIR': WORKING_DIR,
    'CFG': CFG,
})
'''

CELL2_CODE = r'''#@title (2) Install dependencies & clone the repository
import os, subprocess, sys

CFG = globals().get('CFG', {})
REPO = CFG.get('repo', 'Tarkas/Book-to-audiobook')
BRANCH = CFG.get('branch', 'master')
print(f"Repo: {REPO}  Branch: {BRANCH}")
print(f"Python: {sys.version.split()[0]}")

def _run_stream(cmd):
    print('$', cmd, flush=True)
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1,
                         errors='replace')
    for _line in p.stdout:
        print(_line, end='', flush=True)
    p.wait()
    return p.returncode

# Kaggle images already have ffmpeg and most system deps.
# Install only what is missing.
os_cmds = [
    "sudo apt-get update -qq",
    "sudo apt-get install -y libxcb-cursor0 libegl1 libopengl0 espeak-ng mecab libmecab-dev mecab-ipadic-utf8",
    # calibre is needed for ebook conversion (epub -> internal format)
    "sudo -v && wget -nv -O- https://download.calibre-ebook.com/linux-installer.sh | sudo sh /dev/stdin",
    "pip install --no-cache-dir -q mecab-python3 unidic-lite unidic",
    "python -m unidic download",
]
for c in os_cmds:
    print()
    _run_stream(c)

SETUP_REV = "2026-10-22a-kaggle"
print(f"Cell setup revision: {SETUP_REV}")

REPO_DIR = '/kaggle/working/ebook2audiobook'
if not os.path.isdir(os.path.join(REPO_DIR, '.git')):
    if os.path.isdir(REPO_DIR):
        import shutil as _sh
        _sh.rmtree(REPO_DIR, ignore_errors=True)
        print('Removed stale ebook2audiobook directory (no .git).')
    for _attempt in range(3):
        r = subprocess.run(
            f"git clone --depth 1 --branch {BRANCH} --no-tags "
            f"https://github.com/{REPO}.git {REPO_DIR}",
            shell=True, capture_output=True, text=True)
        if r.returncode == 0:
            break
        print(f"Clone attempt {_attempt+1}/3 failed: {r.stderr.strip()}")
        import time; time.sleep(5)
    if r.returncode != 0:
        raise SystemExit(f"git clone failed after 3 attempts (rc={r.returncode}).")
else:
    subprocess.run(f"git -C {REPO_DIR} fetch --depth 1 --no-tags --prune origin {BRANCH}", shell=True)
    _ru = subprocess.run(f"git -C {REPO_DIR} reset --hard FETCH_HEAD", shell=True)
    if _ru.returncode != 0:
        print("WARNING: could not update the existing clone - continuing as is.")
_rh = subprocess.run(f"git -C {REPO_DIR} rev-parse --short HEAD", shell=True,
                     capture_output=True, text=True)
print("Repo checkout:", (_rh.stdout or '?').strip())

# Kaggle ships its own torch; drop the pinned torch stack from requirements.
_skip = ('torch==', 'torchaudio==', 'torchvision==')
with open(os.path.join(REPO_DIR, 'requirements.txt'), encoding='utf-8') as _f:
    _reqs = [l for l in _f if not l.strip().startswith(_skip)]

# Kaggle's Python version: adjust pins if needed.
if sys.version_info[:2] >= (3, 13):
    _PY313_PIN_SWAPS = (
        ('coqui-tts',      'coqui-tts[languages]==0.27.5\n'),
        ('transformers==', 'transformers>=4.57,<5\n'),
        ('numpy==',        'numpy>=2.1\n'),
        ('kokoro>=',       ''),
    )
    def _swap_pins(line):
        s = line.strip()
        for prefix, replacement in _PY313_PIN_SWAPS:
            if s.startswith(prefix):
                return replacement
        return line
    _reqs = [_swap_pins(l) for l in _reqs]
    print(f"Python {sys.version.split()[0]} - swapped pins for py3.13-compatible versions.")

REQ_PATH = '/kaggle/working/req_kaggle.txt'
with open(REQ_PATH, 'w', encoding='utf-8') as _f:
    _f.writelines(_reqs)

# kokoro & misaki: force-install if their Requires-Python cap blocks pip.
if sys.version_info[:2] >= (3, 13):
    _whl_dir = '/tmp/_kokoro_misaki_whls'
    os.makedirs(_whl_dir, exist_ok=True)
    _dl_misaki = ('wget -q -O ' + _whl_dir + '/misaki-0.9.4-py3-none-any.whl '
        'https://files.pythonhosted.org/packages/82/ec/0ee4110ddb54278b8f21c40a140370ae8f687036c4edf578316602697c56/misaki-0.9.4-py3-none-any.whl')
    _dl_kokoro = ('wget -q -O ' + _whl_dir + '/kokoro-0.9.4-py3-none-any.whl '
        'https://files.pythonhosted.org/packages/ea/cc/75f41633c75224ba820a4533163bc8b070b6bf25416014074c63284c2d4e/kokoro-0.9.4-py3-none-any.whl')
    print('$ wget: downloading misaki-0.9.4 and kokoro-0.9.4 wheels')
    _run_stream(_dl_misaki)
    _run_stream(_dl_kokoro)
    _install_cmd = (sys.executable + ' -m pip install --ignore-requires-python --no-deps '
                    + _whl_dir + '/misaki-0.9.4-py3-none-any.whl '
                    + _whl_dir + '/kokoro-0.9.4-py3-none-any.whl')
    print('$ pip install --ignore-requires-python --no-deps (local wheels)')
    _rc = _run_stream(_install_cmd)
    if _rc != 0:
        raise SystemExit('kokoro/misaki install FAILED.')
    import importlib.util as _ilu
    if _ilu.find_spec('kokoro') is None or _ilu.find_spec('misaki') is None:
        raise SystemExit('kokoro/misaki still missing after install.')
    print('kokoro==0.9.4 + misaki==0.9.4 installed.')

print("\nInstalling python requirements (a few minutes)...")
r = _run_stream(f"pip install --no-cache-dir -r {REQ_PATH}")
if r != 0:
    raise SystemExit("pip install of requirements FAILED - see output above.")
print("Requirements installed.")

# Neuter torchaudio.set_audio_backend calls (removed in torchaudio >= 2.2).
import glob as _g, re as _re
_patch_files = []
for _pkg_dir in ('pyannote/audio', 'speechbrain'):
    _patch_files += _g.glob('/usr/local/lib/python3*/dist-packages/' + _pkg_dir + '/**/*.py',
                            recursive=True)
for _p in _patch_files:
    with open(_p, encoding='utf-8') as _f:
        _s = _f.read()
    _s2 = _re.sub(r'^(\s*)torchaudio\.set_audio_backend\(',
                  r'\1pass  # torchaudio>=2.2 removed it (',
                  _s, flags=_re.M)
    if _s2 != _s:
        with open(_p, 'w', encoding='utf-8') as _f:
            _f.write(_s2)
        print("Patched set_audio_backend in", _p)

print("\nInstalled versions:")
from importlib.metadata import version as _pkgver
for _pkn in ('kokoro', 'misaki', 'coqui-tts', 'transformers', 'numpy',
             'torch', 'torchaudio', 'gradio'):
    try:
        print(f'  {_pkn}=={_pkgver(_pkn)}')
    except Exception:
        print(f'  {_pkn}: NOT INSTALLED')
print("\nSetup done.")
'''

CELL3_CODE = r'''#@title (3) Convert parts, checkpoint and merge { display-mode: "form" }
import glob, hashlib, json, os, shutil, subprocess, sys, threading, time
from datetime import datetime, timezone

CFG = globals().get('CFG', {})
_required = ['EBOOK', 'BOOK_HASH', 'BOOK_NAME', 'BOOK_KEY', 'CUR_SETTINGS',
             'PLAN_ID', 'PLAN_DIR', 'PART_AUDIO_MINUTES', 'CHARS_PER_MINUTE',
             'SESSION_BUDGET_MINUTES', 'BASE_DIR', 'PLANS_DIR',
             'WORKING_DIR']
_missing = [name for name in _required if name not in globals()]
if _missing:
    raise SystemExit("Run cell (1) first - missing: " + ", ".join(_missing))

REPO_DIR = '/kaggle/working/ebook2audiobook'
APP_PATH = os.path.join(REPO_DIR, 'app.py')
SPLITTER = os.path.join(REPO_DIR, 'tools', 'colab_book_parts.py')
FINALIZER = os.path.join(REPO_DIR, 'tools', 'colab_book_finalize.py')
if not os.path.isfile(APP_PATH):
    raise SystemExit("Repository not found. Run cell (2) to clone it, then re-run this cell.")
if not os.path.isfile(SPLITTER) or not os.path.isfile(FINALIZER):
    raise SystemExit(
        "The helper tools are missing in the cloned repository.\n"
        "Push the updated tools/colab_book_parts.py, tools/colab_book_finalize.py "
        "and app.py to the branch used in cell (2), then re-run."
    )

PLAN_STATE_PATH = os.path.join(PLAN_DIR, 'state.json')
PARTS_DIR = os.path.join(PLAN_DIR, 'parts')
SOURCE_DIR = os.path.join(PLAN_DIR, 'source')
OUTPUT_DIR = os.path.join(PLAN_DIR, 'output')
FINAL_DIR = os.path.join(OUTPUT_DIR, 'final')
FINAL_INFO_PATH = os.path.join(FINAL_DIR, 'final.json')
CKPT_DIR = os.path.join(PLAN_DIR, 'checkpoints')
LOG_DIR = os.path.join(PLAN_DIR, 'logs')
for _folder in (PLAN_DIR, SOURCE_DIR, PARTS_DIR, OUTPUT_DIR, FINAL_DIR, CKPT_DIR, LOG_DIR):
    os.makedirs(_folder, exist_ok=True)

TMP_DIR = os.path.join(REPO_DIR, 'tmp')
os.makedirs(TMP_DIR, exist_ok=True)
PART_MINUTES = float(PART_AUDIO_MINUTES)
TARGET_CHARS = int(PART_MINUTES * float(CHARS_PER_MINUTE))
OUTPUT_FORMAT = str(CUR_SETTINGS.get('output_format') or 'm4b').lower()
TRANSLATE = bool(CUR_SETTINGS.get('translate'))
HAVE_RSYNC = shutil.which('rsync') is not None

def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def _read_json(path):
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        return None

def _write_json(path, data):
    temp = path + '.tmp'
    with open(temp, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(temp, path)

def _final_paths(info=None):
    info = info if isinstance(info, dict) else _read_json(FINAL_INFO_PATH)
    if not isinstance(info, dict) or info.get('plan_id') != PLAN_ID:
        return None
    if info.get('translated_error'):
        return None
    result = {}
    for key in ('audio', 'translated'):
        name = info.get(key)
        if not name:
            result[key] = None
            continue
        path = name if os.path.isabs(name) else os.path.join(FINAL_DIR, name)
        try:
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                return None
        except OSError:
            return None
        result[key] = path
    return result if result.get('audio') else None

def _sha1_file(path):
    digest = hashlib.sha1()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def _list_files(folder):
    result = []
    if not os.path.isdir(folder):
        return result
    for dirpath, _, names in os.walk(folder):
        for name in names:
            result.append(os.path.join(dirpath, name))
    return result

def _tail(path, count=30):
    try:
        with open(path, encoding='utf-8', errors='replace') as handle:
            return '\n'.join(handle.read().splitlines()[-count:])
    except Exception:
        return ''

def _stream(cmd, cwd=None, log_path=None):
    print('$', ' '.join(cmd), flush=True)
    env = dict(os.environ)
    env['PYTHONUNBUFFERED'] = '1'
    log = open(log_path, 'w', encoding='utf-8') if log_path else None
    try:
        process = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1, errors='replace',
        )
    except OSError as exc:
        if log:
            log.close()
        print("Could not start the command:", exc)
        return 127
    for line in process.stdout:
        print(line, end='', flush=True)
        if log:
            log.write(line)
            log.flush()
    process.wait()
    if log:
        log.close()
    return process.returncode

def _copy_tree(src, dst, settled=False):
    """Copy src -> dst. settled=True skips files modified in the last 30s."""
    if not os.path.isdir(src):
        return True
    os.makedirs(dst, exist_ok=True)
    cutoff = time.time() - (30 if settled else 0)
    for dirpath, _, names in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        target_dir = dst if rel == '.' else os.path.join(dst, rel)
        os.makedirs(target_dir, exist_ok=True)
        for name in names:
            src_file = os.path.join(dirpath, name)
            dst_file = os.path.join(target_dir, name)
            try:
                if settled and os.path.getmtime(src_file) > cutoff:
                    continue
                if (not os.path.exists(dst_file)
                        or os.path.getmtime(src_file) >= os.path.getmtime(dst_file)):
                    shutil.copy2(src_file, dst_file)
            except OSError:
                pass
    return True

state = _read_json(PLAN_STATE_PATH)
if isinstance(state, dict):
    if state.get('plan_id') != PLAN_ID:
        raise SystemExit("Plan folder does not match this plan. Re-run cell (1).")
    if state.get('source_sha1') != BOOK_HASH:
        raise SystemExit(
            "The source book and the plan do not match.\n"
            "Re-run cell (1) to select the correct book, or delete the plan folder."
        )
    if state.get('status') == 'completed':
        _final = _final_paths()
        if _final:
            print("This plan is already complete - nothing to convert.")
            print("Final audiobook:", _final['audio'])
            if _final.get('translated'):
                print("Translated book:", _final['translated'])
            print("Output folder:", OUTPUT_DIR)
            raise SystemExit(0)
        print("This plan is complete, but the final merged files are missing - restarting the merge.")
else:
    state = {
        'version': 1,
        'plan_id': PLAN_ID,
        'book_key': BOOK_KEY,
        'book_name': BOOK_NAME,
        'source_name': BOOK_NAME,
        'source_sha1': BOOK_HASH,
        'settings': CUR_SETTINGS,
        'created_at': _now(),
        'updated_at': _now(),
        'status': 'running',
        'total_parts': 0,
        'completed_parts': 0,
        'parts': {},
    }

SOURCE_NAME = state.get('source_name') or BOOK_NAME
SOURCE_PATH = os.path.join(SOURCE_DIR, SOURCE_NAME)
if not os.path.isfile(SOURCE_PATH) or _sha1_file(SOURCE_PATH) != BOOK_HASH:
    if os.path.abspath(EBOOK) == os.path.abspath(SOURCE_PATH):
        raise SystemExit("The plan's source file is missing or corrupted: " + SOURCE_PATH)
    _temp = SOURCE_PATH + '.tmp'
    print("Copying the book into the plan folder...")
    shutil.copy2(EBOOK, _temp)
    os.replace(_temp, SOURCE_PATH)
state['source_name'] = os.path.basename(SOURCE_PATH)
state['settings'] = CUR_SETTINGS
state['updated_at'] = _now()
_write_json(PLAN_STATE_PATH, state)
print("Source book:", SOURCE_PATH)

def _manifest_valid(manifest):
    if not isinstance(manifest, dict):
        return False
    if manifest.get('source_sha1') != BOOK_HASH:
        return False
    if int((manifest.get('split') or {}).get('target_chars', -1)) != TARGET_CHARS:
        return False
    items = manifest.get('parts') or []
    if not items:
        return False
    for item in items:
        path = os.path.join(PARTS_DIR, str(item.get('file') or ''))
        if not os.path.isfile(path):
            return False
        if item.get('sha1') and _sha1_file(path) != item.get('sha1'):
            return False
    return True

MARKER_PATH = os.path.join(PARTS_DIR, 'manifest.json')
manifest = _read_json(MARKER_PATH)
if _manifest_valid(manifest):
    print(f"Reusing the existing split: {len(manifest['parts'])} parts.")
else:
    manifest = None
    print("Splitting the book into parts...")
    split_cmd = [
        sys.executable, SPLITTER, 'plan',
        '--ebook', SOURCE_PATH,
        '--out-dir', PARTS_DIR,
        '--part-minutes', str(PART_MINUTES),
        '--chars-per-minute', str(int(CHARS_PER_MINUTE)),
        '--language', str(CUR_SETTINGS.get('language') or 'eng'),
    ]
    if os.path.isfile(MARKER_PATH):
        split_cmd.append('--force')
    split_rc = _stream(split_cmd, cwd=REPO_DIR,
                       log_path=os.path.join(LOG_DIR, 'split.log'))
    if split_rc != 0:
        raise SystemExit(f"Splitting failed (exit {split_rc}). See {LOG_DIR}/split.log")
    manifest = _read_json(MARKER_PATH)
    if not _manifest_valid(manifest):
        raise SystemExit("Splitting finished, but the manifest or parts are invalid.")
    print(f"Split into {len(manifest['parts'])} parts.")

parts = sorted(manifest['parts'], key=lambda item: int(item.get('index', 0)))
state['total_parts'] = len(parts)
state['title'] = manifest.get('title') or state.get('title') or os.path.splitext(SOURCE_NAME)[0]
state_parts = state.setdefault('parts', {})
for item in parts:
    key = f"{int(item['index']):03d}"
    entry = state_parts.setdefault(key, {})
    old_sha = entry.get('sha1')
    if entry.get('status') == 'done' and old_sha and old_sha != item.get('sha1'):
        print(f"WARNING: part {key} was rebuilt; its old audio is stale and will be re-converted.")
        entry.clear()
        entry['status'] = 'pending'
    entry.update({
        'index': int(item['index']),
        'file': item['file'],
        'title': item.get('title', ''),
        'sha1': item.get('sha1', ''),
        'estimated_minutes': item.get('estimated_minutes'),
    })
state['updated_at'] = _now()
_write_json(PLAN_STATE_PATH, state)

try:
    _app_source = open(APP_PATH, encoding='utf-8', errors='replace').read()
except Exception:
    _app_source = ''
PER_SESSION_TRANSLATION = 'translation_id' in _app_source

def _session_id(item):
    raw = f"{PLAN_ID}|{int(item['index'])}|{item.get('sha1', '')}"
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:24]

def _audio_files(folder):
    suffix = '.' + OUTPUT_FORMAT
    result = []
    for path in _list_files(folder):
        try:
            if path.lower().endswith(suffix) and os.path.getsize(path) > 0:
                result.append(path)
        except OSError:
            pass
    return result

def _is_done(key, entry):
    if entry.get('status') != 'done':
        return False
    if _audio_files(os.path.join(OUTPUT_DIR, key)):
        return True
    print(f"Part {key} is marked done, but its audio is missing - it will be re-converted.")
    entry['status'] = 'pending'
    shutil.rmtree(os.path.join(OUTPUT_DIR, key), ignore_errors=True)
    return False

def _validate_audio(root):
    try:
        import soundfile as sf
    except Exception:
        sf = None
    checked = 0
    removed = []
    for path in _list_files(root):
        if not path.lower().endswith('.flac'):
            continue
        ok = False
        if sf is not None:
            try:
                ok = sf.info(path).frames > 0
            except Exception:
                ok = False
        else:
            try:
                ok = os.path.getsize(path) > 1024
            except OSError:
                ok = False
        if ok:
            checked += 1
            continue
        try:
            os.remove(path)
            removed.append(os.path.relpath(path, root))
        except OSError:
            pass
    if checked or removed:
        print(f"Checkpoint check: {checked} valid audio files, {len(removed)} incomplete removed.")
    return removed

def _run_app(part_path, session_id, out_dir, log_path):
    cmd = [
        sys.executable, 'app.py', '--headless', '--script_mode', 'full_docker',
        '--ebook', part_path,
        '--language', str(CUR_SETTINGS.get('language') or 'eng'),
        '--output_format', OUTPUT_FORMAT,
        '--device', 'gpu',
        '--output_dir', out_dir,
        '--session', session_id,
    ]
    engine = CFG.get('tts_engine')
    if engine:
        cmd += ['--tts_engine', str(engine)]
    voice = CFG.get('voice')
    if voice:
        if os.path.isfile(str(voice)):
            cmd += ['--voice', os.path.abspath(str(voice))]
        else:
            matches = [m for m in glob.glob(
                os.path.join(REPO_DIR, 'voices', '**', str(voice) + '.*'),
                recursive=True) if '__sessions' not in m]
            matches.sort(key=lambda m: (not m.endswith('.wav'), len(m)))
            if matches:
                cmd += ['--voice', os.path.abspath(matches[0])]
                print("Using voice:", matches[0])
            else:
                print(f"Voice '{voice}' was not found; the engine default will be used.")
    for key, flag in (('speed', '--speed'), ('temperature', '--temperature'),
                      ('repetition_penalty', '--repetition_penalty')):
        value = CFG.get(key)
        if value is not None:
            cmd += [flag, str(value)]
    if TRANSLATE:
        cmd += [
            '--translate',
            '--source_lang', str(CUR_SETTINGS.get('source_lang') or 'eng'),
            '--target_lang', str(CUR_SETTINGS.get('target_lang')
                                or CUR_SETTINGS.get('language') or 'eng'),
            '--translation_method', str(CUR_SETTINGS.get('translation_method') or 'google'),
        ]
    return _stream(cmd, cwd=REPO_DIR, log_path=log_path)

# Remove leftovers of finished parts and stale outputs of unfinished ones.
for key, entry in state_parts.items():
    if not isinstance(entry, dict):
        continue
    if entry.get('status') == 'done':
        sid = _session_id(entry)
        shutil.rmtree(os.path.join(CKPT_DIR, sid), ignore_errors=True)
        shutil.rmtree(os.path.join(TMP_DIR, f'proc-{sid}'), ignore_errors=True)
        shutil.rmtree(os.path.join(TMP_DIR, 'translation', sid), ignore_errors=True)
    else:
        shutil.rmtree(os.path.join(OUTPUT_DIR, key), ignore_errors=True)

session_started = time.time()
failed = False
stopped_for_budget = False
completed_this_run = 0

print(f"\nParts to convert: {len(parts)}. Session budget: {SESSION_BUDGET_MINUTES:.0f} min.")
print("Checkpoints are saved to the plan folder every 60 seconds.\n")

for item in parts:
    key = f"{int(item['index']):03d}"
    entry = state_parts.setdefault(key, {})
    if _is_done(key, entry):
        print(f"Part {key}: already finished - skipping.")
        continue
    elapsed_min = (time.time() - session_started) / 60.0
    if elapsed_min >= SESSION_BUDGET_MINUTES:
        stopped_for_budget = True
        print(f"Session budget reached; part {key} will start in the next session.")
        break

    part_path = os.path.join(PARTS_DIR, entry['file'])
    session_id = _session_id(entry)
    part_ckpt = os.path.join(CKPT_DIR, session_id)
    proc_dir = os.path.join(TMP_DIR, f'proc-{session_id}')
    if PER_SESSION_TRANSLATION:
        trans_dir = os.path.join(TMP_DIR, 'translation', session_id)
    else:
        trans_dir = os.path.join(TMP_DIR, 'translation')
    out_local = os.path.join(WORKING_DIR, 'out', session_id)
    part_log = os.path.join(
        LOG_DIR, f"part-{key}-attempt-{int(entry.get('attempts') or 0) + 1}.log")

    entry['attempts'] = int(entry.get('attempts') or 0) + 1
    entry['session'] = session_id
    entry['status'] = 'running'
    state['status'] = 'running'
    state['updated_at'] = _now()
    _write_json(PLAN_STATE_PATH, state)

    shutil.rmtree(out_local, ignore_errors=True)
    os.makedirs(out_local, exist_ok=True)
    restored_checkpoint = os.path.isdir(os.path.join(part_ckpt, 'proc'))

    print(f"\n{'=' * 70}\nPart {key}/{len(parts)}  ({entry.get('estimated_minutes') or '?'} min estimated)")
    print("Part file:", part_path)
    print("Session:  ", session_id)
    if restored_checkpoint:
        print("Restoring checkpoint...")
        _copy_tree(os.path.join(part_ckpt, 'proc'), proc_dir)
        if TRANSLATE and os.path.isdir(os.path.join(part_ckpt, 'translation')):
            _copy_tree(os.path.join(part_ckpt, 'translation'), trans_dir)
        print("Checkpoint restored.")
    else:
        print("No checkpoint yet - starting this part from the beginning.")

    if TRANSLATE:
        os.makedirs(os.path.join(TMP_DIR, 'translation'), exist_ok=True)
        if PER_SESSION_TRANSLATION:
            os.makedirs(trans_dir, exist_ok=True)

    if os.path.isdir(proc_dir):
        _validate_audio(proc_dir)

    os.makedirs(part_ckpt, exist_ok=True)
    _write_json(os.path.join(part_ckpt, 'part.json'), {
        'plan_id': PLAN_ID,
        'index': int(entry['index']),
        'sha1': entry.get('sha1'),
        'source': entry['file'],
        'title': entry.get('title'),
    })

    stop_sync = threading.Event()

    def _sync_loop(proc=proc_dir, trans=trans_dir, ckpt=part_ckpt):
        warned = False
        while not stop_sync.wait(60):
            _copy_tree(proc, os.path.join(ckpt, 'proc'), settled=True)
            if TRANSLATE:
                _copy_tree(trans, os.path.join(ckpt, 'translation'), settled=True)

    sync_thread = threading.Thread(target=_sync_loop, daemon=True)
    sync_thread.start()

    rc = _run_app(part_path, session_id, out_local, part_log)
    stop_sync.set()
    sync_thread.join(timeout=30)

    if rc != 0:
        _copy_tree(proc_dir, os.path.join(part_ckpt, 'proc'))
        if TRANSLATE:
            _copy_tree(trans_dir, os.path.join(part_ckpt, 'translation'))
        entry['status'] = 'pending'
        entry['last_error'] = f'app.py exited with code {rc}'
        state['updated_at'] = _now()
        _write_json(PLAN_STATE_PATH, state)
        print(f"\nPart {key} did not finish (exit {rc}). Progress is saved.")
        print("The next run resumes this part. Last log lines:")
        print(_tail(part_log))
        failed = True
        break

    out_files = _list_files(out_local)
    audio_files = _audio_files(out_local)
    if not audio_files:
        entry['status'] = 'pending'
        entry['last_error'] = 'app.py finished without producing audio'
        state['updated_at'] = _now()
        _write_json(PLAN_STATE_PATH, state)
        print(f"\nPart {key}: app.py exited successfully but produced no audio.")
        print("The checkpoint is kept; the next run retries this part. Last log lines:")
        print(_tail(part_log))
        failed = True
        break

    target_dir = os.path.join(OUTPUT_DIR, key)
    shutil.rmtree(target_dir, ignore_errors=True)
    os.makedirs(target_dir, exist_ok=True)
    copied_audio = []
    for src_path in out_files:
        rel = os.path.relpath(src_path, out_local)
        dst_path = os.path.join(target_dir, rel)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.copy2(src_path, dst_path)
        if src_path in audio_files:
            copied_audio.append(dst_path)

    entry['status'] = 'done'
    entry['outputs'] = sorted(os.path.relpath(path, target_dir)
                              for path in _list_files(target_dir))
    entry['completed_at'] = _now()
    entry.pop('last_error', None)
    part_keys = {f"{int(row['index']):03d}" for row in parts}
    done_count = sum(1 for part_key in part_keys
                     if state_parts.get(part_key, {}).get('status') == 'done')
    state['completed_parts'] = done_count
    state['status'] = 'finalizing' if done_count == len(parts) else 'running'
    state['updated_at'] = _now()
    _write_json(PLAN_STATE_PATH, state)

    shutil.rmtree(part_ckpt, ignore_errors=True)
    shutil.rmtree(proc_dir, ignore_errors=True)
    if PER_SESSION_TRANSLATION:
        shutil.rmtree(trans_dir, ignore_errors=True)
    shutil.rmtree(out_local, ignore_errors=True)

    completed_this_run += 1
    print(f"Part {key} finished ({done_count}/{len(parts)}). Saved to {target_dir}")

part_keys = {f"{int(row['index']):03d}" for row in parts}
done_total = sum(1 for part_key in part_keys
                 if state_parts.get(part_key, {}).get('status') == 'done')
state['completed_parts'] = done_total

if done_total == len(parts):
    _final = _final_paths()
    if _final:
        state['status'] = 'completed'
        state['completed_at'] = state.get('completed_at') or _now()
        state['updated_at'] = _now()
        _write_json(PLAN_STATE_PATH, state)
        print(f"\nAll {len(parts)} parts are finished and already merged.")
        print("Final audiobook:", _final['audio'])
        if _final.get('translated'):
            print("Translated book:", _final['translated'])
    else:
        state['status'] = 'finalizing'
        state['updated_at'] = _now()
        _write_json(PLAN_STATE_PATH, state)
        print(f"\nAll {len(parts)} parts are finished. Merging them into one audiobook...")
        print("The merge uses ffmpeg and can take a few minutes.")
        finalize_log = os.path.join(LOG_DIR, 'finalize.log')
        finalize_rc = _stream(
            [sys.executable, FINALIZER, '--plan-dir', PLAN_DIR,
             '--audio-format', OUTPUT_FORMAT,
             '--language', str(CUR_SETTINGS.get('target_lang')
                               or CUR_SETTINGS.get('language') or 'eng')],
            cwd=REPO_DIR, log_path=finalize_log)
        final_info = _read_json(FINAL_INFO_PATH)
        _final = _final_paths(final_info)
        if finalize_rc == 0 and _final:
            state['final'] = final_info
            state['status'] = 'completed'
            state['completed_at'] = _now()
            state['updated_at'] = _now()
            state.pop('final_error', None)
            _write_json(PLAN_STATE_PATH, state)
            print("\nFinal audiobook:", _final['audio'])
            if _final.get('translated'):
                print("Translated book:", _final['translated'])
            print("The plan is marked complete; re-running the cells will not convert it again.")
        else:
            message = ((final_info or {}).get('translated_error')
                       or f'finalizer exited with code {finalize_rc}')
            state['status'] = 'finalizing'
            state['final_error'] = message
            state['updated_at'] = _now()
            _write_json(PLAN_STATE_PATH, state)
            print(f"\nThe parts are safe, but the final merge failed: {message}")
            print("Re-run this cell to retry the merge. Last log lines:")
            print(_tail(finalize_log))
elif failed:
    state['status'] = 'running'
    state['updated_at'] = _now()
    _write_json(PLAN_STATE_PATH, state)
    print(f"\nStopped after {done_total}/{len(parts)} parts. Fix the error above, then re-run this cell.")
    print("The checkpoint of the unfinished part is kept and will be reused.")
else:
    state['status'] = 'running'
    state['updated_at'] = _now()
    _write_json(PLAN_STATE_PATH, state)
    print(f"\nThis session finished {completed_this_run} part(s); total {done_total}/{len(parts)}.")
    if stopped_for_budget:
        print("Session budget reached.")
    print("To continue: open this notebook again, attach the state dataset, Run all.")
    print("Finished parts are skipped and the unfinished part resumes from its checkpoint.")

# --- Upload state back to the Kaggle Dataset (if attached) ---------------
STATE_INPUT_DIR = globals().get('STATE_INPUT_DIR', '')
if STATE_INPUT_DIR:
    # Derive the dataset slug from the input directory name.
    # /kaggle/input/username-dataset-name/ -> username/dataset-name
    _dir_name = os.path.basename(STATE_INPUT_DIR.rstrip('/'))
    # Kaggle replaces '/' with '-' in the directory name; try to recover the slug
    # by looking at kaggle metadata if available.
    _slug = ''
    _meta_candidates = [
        os.path.join(STATE_INPUT_DIR, 'dataset-metadata.json'),
        os.path.join(STATE_INPUT_DIR, 'metadata.json'),
    ]
    for _mc in _meta_candidates:
        _md = _read_json(_mc)
        if isinstance(_md, dict) and _md.get('slug'):
            _slug = _md['slug']
            break
    if not _slug:
        # Fallback: assume the dir name is "owner-name" and try to split on
        # the first dash after a known owner pattern. Ask the user instead.
        try:
            _slug = input(
                f"Enter the Kaggle dataset slug for state upload "
                f"(e.g. your-name/ebook2audiobook-state, detected dir: {_dir_name}): "
            ).strip()
        except Exception:
            _slug = ''
    if _slug:
        _upload_dir = '/kaggle/working/_state_upload'
        shutil.rmtree(_upload_dir, ignore_errors=True)
        os.makedirs(_upload_dir, exist_ok=True)
        # Copy only the plans/ tree (state + checkpoints), not the finished audio.
        shutil.copytree(PLANS_DIR, os.path.join(_upload_dir, 'plans'), dirs_exist_ok=True)
        print(f"\nUploading state to Kaggle Dataset '{_slug}'...")
        _rc = _run_stream(
            f"kaggle datasets version -p {_upload_dir} -m 'ebook2audiobook state {_now()}' "
            f"--slug {_slug} --dir-mode skip")
        if _rc == 0:
            print("State uploaded. Attach this dataset next session to resume.")
        else:
            print("State upload failed (see output above).")
            print("You can retry manually: kaggle datasets version -p", _upload_dir)
    else:
        print("\nNo dataset slug provided - state was NOT uploaded.")
        print("Progress lives only in /kaggle/working and will be lost.")

# --- Point the user to the finished files -------------------------------
_final = _final_paths()
if _final:
    print("\n" + "=" * 70)
    print("FINAL AUDIOBOOK:", _final['audio'])
    if _final.get('translated'):
        print("TRANSLATED BOOK:", _final['translated'])
    print("Download it from the Output panel on the right, or:")
    print(f"  from google.colab import files  # not available on Kaggle")
    print(f"  # Use the Kaggle Output tab or: kaggle kernels output <this-notebook>")
    print("=" * 70)
else:
    _done_now = done_total
    print(f"\nProgress: {_done_now}/{len(parts)} parts finished.")
    print("Output folder:", OUTPUT_DIR)
    if STATE_INPUT_DIR:
        print("State was uploaded to the dataset - next session will resume.")
    else:
        print("WARNING: no state dataset attached. If the session ends now,")
        print("all progress is lost. Attach a dataset next time to enable resume.")
'''


def build_notebook():
    with open(SRC, encoding='utf-8') as f:
        colab = json.load(f)

    cells = [
        {
            'cell_type': 'markdown',
            'metadata': {},
            'source': to_source(CELL0_MD),
        },
        {
            'cell_type': 'code',
            'execution_count': None,
            'metadata': {'cellView': 'form'},
            'outputs': [],
            'source': to_source(CELL1_CODE),
        },
        {
            'cell_type': 'code',
            'execution_count': None,
            'metadata': {'cellView': 'form'},
            'outputs': [],
            'source': to_source(CELL2_CODE),
        },
        {
            'cell_type': 'code',
            'execution_count': None,
            'metadata': {'cellView': 'form'},
            'outputs': [],
            'source': to_source(CELL3_CODE),
        },
    ]

    notebook = {
        'cells': cells,
        'metadata': {
            'accelerator': 'GPU',
            'kaggle': {
                'accelerator': 'gpu',
                'dataSources': [],
                'isGpuEnabled': True,
                'isInternetEnabled': True,
                'language': 'python',
            },
            'kernelspec': {
                'display_name': 'Python 3',
                'language': 'python',
                'name': 'python3',
            },
            'language_info': {
                'codemirror_mode': {'name': 'ipython', 'version': 3},
                'file_extension': '.py',
                'mimetype': 'text/x-python',
                'name': 'python',
                'nbconvert_exporter': 'python',
                'pygments_lexer': 'ipython3',
            },
        },
        'nbformat': 4,
        'nbformat_minor': 0,
    }

    with open(DST, 'w', encoding='utf-8') as f:
        json.dump(notebook, f, ensure_ascii=False, indent=1)
    print(f"Wrote {DST}")


if __name__ == '__main__':
    build_notebook()
