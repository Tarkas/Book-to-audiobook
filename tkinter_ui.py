import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import os
import re
import subprocess
import sys
import queue
import time
import tempfile
import shutil
import uuid
import json
import base64
import webbrowser
from pathlib import Path
from lib.conf import prog_version, default_device, voices_dir
from lib.lang import language_mapping, default_language_code, language_tts
from lib.models import TTS_ENGINES, default_engine_settings
from lib.functions import get_compatible_tts_engines, SessionContext, convert_ebook
# Import translate_ebook_file from the correct module
# Always use the improved translator since the original one doesn't have translation functionality
from lib.improved_translator import translate_ebook_file, get_compatible_translation_methods

# Cloud conversion runs the notebook shipped in the Notebooks folder on a free GPU.
# IMPORTANT: Colab loads the notebook from GitHub and the notebook clones the repo
# from GitHub too, so these must point to the fork where you pushed these changes
# (app.py translation flags + the settings-aware notebook). Change them to your fork.
CLOUD_REPO = 'Tarkas/Book-to-audiobook'
CLOUD_BRANCH = 'master'
COLAB_NOTEBOOK_URL = f'https://colab.research.google.com/github/{CLOUD_REPO}/blob/{CLOUD_BRANCH}/Notebooks/colab_ebook2audiobook.ipynb'

# Import our new language codes mapping
try:
    from lib.language_codes import LANGUAGE_CODES, get_language_abbreviations, get_language_name
    USE_NEW_LANGUAGE_MAPPING = True
except ImportError:
    USE_NEW_LANGUAGE_MAPPING = False


class FilterableCombobox(ttk.Combobox):
    """Combobox that narrows its dropdown list while the user types.

    Matching is case-insensitive against the visible display string plus
    optional per-item search terms (e.g. Russian language names), so typing
    "рус", "ru" or "russian" all shrink the list to Russian. Enter picks the
    first match, mouse selection works as usual; after any selection the full
    list is restored so the next dropdown shows every item again.
    """

    _IGNORED_KEYSYMS = {
        'Up', 'Down', 'Left', 'Right', 'Home', 'End', 'Prior', 'Next',
        'Return', 'KP_Enter', 'Escape', 'Tab',
        'Shift_L', 'Shift_R', 'Control_L', 'Control_R', 'Alt_L', 'Alt_R',
        'Caps_Lock', 'Num_Lock',
    }

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self._all_values = list(self['values']) if self['values'] else []
        self._search_terms = {}
        self.bind('<KeyRelease>', self._on_keyrelease, add='+')
        self.bind('<Return>', self._on_return, add='+')
        self.bind('<<ComboboxSelected>>', self._on_selected, add='+')
        self.bind('<FocusOut>', self._on_focus_out, add='+')

    def set_completion_list(self, values, search_terms=None):
        """Set the full item list and optional extra keywords per display string
        ({display_name: 'space separated lower-case terms'})."""
        self._all_values = list(values)
        self._search_terms = {
            disp: terms.lower() for disp, terms in (search_terms or {}).items()
        }
        self['values'] = self._all_values

    def _matches(self, display, needle):
        if needle in display.lower():
            return True
        extra = self._search_terms.get(display)
        return bool(extra and needle in extra)

    def _filtered(self, typed):
        needle = typed.strip().lower()
        if not needle:
            return []
        return [d for d in self._all_values if self._matches(d, needle)]

    def _on_keyrelease(self, event):
        # skip navigation/modifier keys and Ctrl shortcuts: they don't change the text
        if event.keysym in self._IGNORED_KEYSYMS or (event.state & 0x4):
            return
        typed = self.get().strip()
        if not typed:
            self['values'] = self._all_values
            return
        matches = self._filtered(typed)
        # keep the full list when nothing matches so the dropdown never goes blank
        self['values'] = matches if matches else self._all_values
        if matches:
            self._open_dropdown()

    def _open_dropdown(self):
        """Show the dropdown while keeping keyboard focus in the entry."""
        try:
            self.tk.call('ttk::combobox::Post', self)
            self.focus_set()
            self.icursor(tk.END)
        except tk.TclError:
            pass

    def _on_return(self, event):
        """Enter confirms the exact item or the first filtered match."""
        typed = self.get().strip()
        if typed in self._all_values:
            self._select_item(typed)
            return 'break'
        matches = self._filtered(typed)
        if matches:
            self._select_item(matches[0])
            return 'break'
        return None

    def _select_item(self, item):
        self.set(item)
        self.icursor(tk.END)
        try:
            self.tk.call('ttk::combobox::Unpost', self)
        except tk.TclError:
            pass
        self.event_generate('<<ComboboxSelected>>')

    def _on_selected(self, event):
        # after any selection show the complete list again on the next open
        self['values'] = self._all_values

    def _on_focus_out(self, event):
        # complete an unambiguous partial entry, otherwise leave the text as-is
        # (downstream code already normalizes free text) and restore the list
        typed = self.get().strip()
        if typed and typed not in self._all_values:
            matches = self._filtered(typed)
            if len(matches) == 1:
                self._select_item(matches[0])
                return
        self['values'] = self._all_values


def build_language_options():
    """Build the shared (display_names, values, search_terms) triple used by all
    language comboboxes (previously this logic was copied three times).
    search_terms maps a display string to extra lower-case keywords (Russian/
    English/native names and ISO codes from LANGUAGE_CODES) so the filter finds
    an item by any spelling, e.g. "немец" finds "German (Deutsch) [deu]".
    """
    if not USE_NEW_LANGUAGE_MAPPING:
        options = list(language_mapping.keys())
        return options, options, {}
    display_names = []
    values = []
    search_terms = {}
    # code -> every known spelling/code of that language from LANGUAGE_CODES
    extra_terms_by_code = {}
    for lang_name, abbreviations in LANGUAGE_CODES.items():
        for abbr in abbreviations:
            bucket = extra_terms_by_code.setdefault(abbr, set())
            bucket.add(lang_name)
            bucket.update(abbreviations)
    # Add language mapping entries (abbreviations with full names)
    for abbrev, info in language_mapping.items():
        display_name = f"{info['name']} ({info['native_name']}) [{abbrev}]"
        display_names.append(display_name)
        values.append(abbrev)
        extra = extra_terms_by_code.get(abbrev)
        if extra:
            search_terms[display_name] = ' '.join(sorted(extra)).lower()
    # Add new language codes entries (full names with abbreviations)
    for lang_name in LANGUAGE_CODES.keys():
        abbreviations = get_language_abbreviations(lang_name)
        if abbreviations:
            primary_abbr = abbreviations[0]
            display_name = f"{lang_name.capitalize()} [{primary_abbr}]"
            if display_name not in display_names:  # Avoid duplicates
                display_names.append(display_name)
                values.append(lang_name)
                extra = extra_terms_by_code.get(primary_abbr)
                if extra:
                    search_terms[display_name] = ' '.join(sorted(extra)).lower()
    return display_names, values, search_terms


class Ebook2AudiobookGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(f"ebook2audiobook v{prog_version}")
        self.root.geometry("850x750")
        self.root.minsize(650, 550)

        # Window/taskbar icon (book in headphones). Looked up next to this module
        # (source checkout / frozen _internal) and in the working directory (exe dir).
        # Without an explicit AppUserModelID Windows groups the window under
        # python.exe and shows the Python icon in the taskbar instead of ours.
        if sys.platform == 'win32':
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Tarkas.ebook2audiobook')
            except Exception:
                pass
        for icon_dir in (os.path.dirname(os.path.abspath(__file__)), os.getcwd()):
            ico_path = os.path.join(icon_dir, 'app_icon.ico')
            png_path = os.path.join(icon_dir, 'app_icon.png')
            applied = False
            if sys.platform == 'win32' and os.path.exists(ico_path):
                try:
                    # default= also covers child windows (dialogs, popups)
                    self.root.iconbitmap(default=ico_path)
                    applied = True
                except tk.TclError:
                    pass
            if os.path.exists(png_path):
                try:
                    self._app_icon = tk.PhotoImage(file=png_path)
                    self.root.iconphoto(True, self._app_icon)
                    applied = True
                except tk.TclError:
                    pass
            if applied:
                break
        
        # Variables
        self.ebook_path = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.language = tk.StringVar(value=default_language_code)
        self.device = tk.StringVar(value=default_device)
        self.tts_engine = tk.StringVar(value="XTTSv2")
        self.voice_file = tk.StringVar()
        self.voice_choice = tk.StringVar()
        self.custom_voice_name = tk.StringVar()
        self.custom_voice_source = tk.StringVar()
        self.output_format = tk.StringVar(value="m4b")
        self.temperature = tk.DoubleVar(value=0.75)
        self.speed = tk.DoubleVar(value=1.0)
        self.repetition_penalty = tk.DoubleVar(value=3.0)
        # Session ID variable for resuming
        self.session_id_var = tk.StringVar()
        
        # Translation variables
        self.translate_var = tk.BooleanVar()  # Default to not translating
        self.source_language = tk.StringVar(value='eng')
        self.target_language = tk.StringVar(value='eng')
        self.translation_method = tk.StringVar(value='google')
        
        # Conversion state
        self.is_converting = False
        self.is_paused = False
        self.message_queue = queue.Queue()
        self.conversion_thread = None
        self.session_context = None
        self.session_id = None
        
        # Keep track of widgets for dynamic updates
        self.tts_combo = None
        self.language_combo = None
        self.method_combo = None
        self.voice_combo = None
        self.voice_options = []  # list of (display_name, value) for the voice combobox
        
        self.create_widgets()
        self.setup_message_handler()
        
        # Bind language change event
        self.language.trace('w', self.on_language_change)
        # Bind TTS engine change to refresh the voice list
        self.tts_engine.trace('w', self.on_tts_engine_change)
        # Bind translation language changes to filter compatible methods
        self.source_language.trace('w', self.on_translation_language_change)
        self.target_language.trace('w', self.on_translation_language_change)
        
    def create_widgets(self):
        # Main frame with padding
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.grid(row=0, column=0, sticky="nsew")
        
        # Notebook for tabs
        notebook = ttk.Notebook(main_frame)
        notebook.grid(row=0, column=0, columnspan=3, sticky="nsew", pady=(0, 15))
        
        # Main parameters tab
        main_tab = ttk.Frame(notebook, padding="10")
        notebook.add(main_tab, text="Main Parameters")
        
        # Ebook selection
        ttk.Label(main_tab, text="Ebook File:").grid(row=0, column=0, sticky="w", pady=5)
        ebook_frame = ttk.Frame(main_tab)
        ebook_frame.grid(row=0, column=1, columnspan=2, sticky="ew", pady=5, padx=(10, 0))
        
        ttk.Entry(ebook_frame, textvariable=self.ebook_path, width=50).grid(row=0, column=0, sticky="ew")
        ttk.Button(ebook_frame, text="Browse...", command=self.browse_ebook).grid(row=0, column=1, padx=(5,0))
        
        # Output directory
        ttk.Label(main_tab, text="Output Directory:").grid(row=1, column=0, sticky="w", pady=5)
        output_frame = ttk.Frame(main_tab)
        output_frame.grid(row=1, column=1, columnspan=2, sticky="ew", pady=5, padx=(10, 0))
        
        ttk.Entry(output_frame, textvariable=self.output_dir, width=50).grid(row=0, column=0, sticky="ew")
        ttk.Button(output_frame, text="Browse...", command=self.browse_output).grid(row=0, column=1, padx=(5,0))
        
        # Language selection
        ttk.Label(main_tab, text="Language:").grid(row=2, column=0, sticky="w", pady=5)
        self.language_combo = FilterableCombobox(main_tab, textvariable=self.language, width=40)  # Increased width
        
        if USE_NEW_LANGUAGE_MAPPING:
            language_display_names, language_values, language_search_terms = build_language_options()
            self.language_combo.set_completion_list(language_display_names, language_search_terms)
            # Set a custom lookup to map display names back to values
            self.language_display_to_value = dict(zip(language_display_names, language_values))
            self.language_value_to_display = dict(zip(language_values, language_display_names))
            
            # Set default display value if it exists in our mapping
            default_lang = self.language.get()
            # Try to find the display name for the default language
            display_name = None
            for disp_name, value in self.language_display_to_value.items():
                if value == default_lang or (default_lang in LANGUAGE_CODES and value == default_lang):
                    display_name = disp_name
                    break
            
            if display_name:
                self.language_combo.set(display_name)
            else:
                # Fallback to setting the value directly if no display name found
                self.language_combo.set(default_lang)
        else:
            language_options = list(language_mapping.keys())
            self.language_combo.set_completion_list(language_options)
        self.language_combo.grid(row=2, column=1, sticky="w", pady=5, padx=(10, 0))
        
        # Bind selection event to update the underlying variable
        if USE_NEW_LANGUAGE_MAPPING:
            def on_language_select(event):
                selected_display = self.language_combo.get()
                if selected_display in self.language_display_to_value:
                    self.language.set(self.language_display_to_value[selected_display])
            self.language_combo.bind('<<ComboboxSelected>>', on_language_select, add='+')
        
        # Device selection
        ttk.Label(main_tab, text="Device:").grid(row=3, column=0, sticky="w", pady=5)
        device_combo = ttk.Combobox(main_tab, textvariable=self.device, width=20)
        device_combo['values'] = ['cpu', 'gpu', 'mps']
        device_combo.grid(row=3, column=1, sticky="w", pady=5, padx=(10, 0))
        
        # TTS Engine selection
        ttk.Label(main_tab, text="TTS Engine:").grid(row=4, column=0, sticky="w", pady=5)
        self.tts_combo = ttk.Combobox(main_tab, textvariable=self.tts_engine, width=20)
        self.tts_combo['values'] = list(TTS_ENGINES.keys())
        self.tts_combo.grid(row=4, column=1, sticky="w", pady=5, padx=(10, 0))

        # Voice selection (depends on the selected TTS engine) + custom cloning file
        ttk.Label(main_tab, text="Voice:\n(depends on TTS engine)").grid(row=5, column=0, sticky="w", pady=5)
        voice_frame = ttk.Frame(main_tab)
        voice_frame.grid(row=5, column=1, columnspan=2, sticky="ew", pady=5, padx=(10, 0))

        self.voice_combo = ttk.Combobox(voice_frame, textvariable=self.voice_choice, width=47, state='readonly')
        self.voice_combo.grid(row=0, column=0, sticky="ew")
        self.voice_combo.bind('<<ComboboxSelected>>', self.on_voice_selected)
        ttk.Button(voice_frame, text="\u25b6 Listen", command=self.preview_voice).grid(row=0, column=1, padx=(5, 0))
        ttk.Button(voice_frame, text="\u25a0 Stop", command=self.stop_preview).grid(row=0, column=2, padx=(5, 0))

        ttk.Label(voice_frame, text="Custom voice cloning file (optional): *.wav, *.mp3, *.flac, *.ogg").grid(row=1, column=0, columnspan=3, sticky="w", pady=(5, 0))
        ttk.Entry(voice_frame, textvariable=self.voice_file, width=50).grid(row=2, column=0, sticky="ew")
        ttk.Button(voice_frame, text="Browse...", command=self.browse_voice).grid(row=2, column=1, padx=(5,0))
        
        # Output format selection
        ttk.Label(main_tab, text="Output Format:").grid(row=6, column=0, sticky="w", pady=5)
        format_combo = ttk.Combobox(main_tab, textvariable=self.output_format, width=20)
        format_combo['values'] = ['m4b', 'mp3', 'wav', 'flac']
        format_combo.grid(row=6, column=1, sticky="w", pady=5, padx=(10, 0))
        
        # Session ID for resuming
        ttk.Label(main_tab, text="Session ID (for resuming):").grid(row=7, column=0, sticky="w", pady=5)
        session_frame = ttk.Frame(main_tab)
        session_frame.grid(row=7, column=1, columnspan=2, sticky="ew", pady=5, padx=(10, 0))
        
        ttk.Entry(session_frame, textvariable=self.session_id_var, width=50).grid(row=0, column=0, sticky="ew")
        ttk.Button(session_frame, text="Generate New", command=self.generate_new_session_id).grid(row=0, column=1, padx=(5,0))
        
        # XTTS Parameters tab
        xtts_tab = ttk.Frame(notebook, padding="10")
        notebook.add(xtts_tab, text="XTTS Parameters")
        
        # Temperature
        ttk.Label(xtts_tab, text="Temperature:").grid(row=0, column=0, sticky="w", pady=5)
        temp_scale = ttk.Scale(xtts_tab, from_=0.01, to=2.0, variable=self.temperature, orient=tk.HORIZONTAL, length=200)
        temp_scale.grid(row=0, column=1, sticky="w", pady=5, padx=(10, 10))
        temp_label = ttk.Label(xtts_tab, textvariable=self.temperature)
        temp_label.grid(row=0, column=2, sticky="w", pady=5)
        
        # Speed
        ttk.Label(xtts_tab, text="Speed:").grid(row=1, column=0, sticky="w", pady=5)
        speed_scale = ttk.Scale(xtts_tab, from_=0.1, to=2.0, variable=self.speed, orient=tk.HORIZONTAL, length=200)
        speed_scale.grid(row=1, column=1, sticky="w", pady=5, padx=(10, 10))
        speed_label = ttk.Label(xtts_tab, textvariable=self.speed)
        speed_label.grid(row=1, column=2, sticky="w", pady=5)
        
        # Repetition Penalty
        ttk.Label(xtts_tab, text="Repetition Penalty:").grid(row=2, column=0, sticky="w", pady=5)
        rep_scale = ttk.Scale(xtts_tab, from_=1.0, to=10.0, variable=self.repetition_penalty, orient=tk.HORIZONTAL, length=200)
        rep_scale.grid(row=2, column=1, sticky="w", pady=5, padx=(10, 10))
        rep_label = ttk.Label(xtts_tab, textvariable=self.repetition_penalty)
        rep_label.grid(row=2, column=2, sticky="w", pady=5)
        
        # Custom voice creation: import an audio sample into the voices library
        ttk.Separator(xtts_tab, orient=tk.HORIZONTAL).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(15, 5))
        ttk.Label(xtts_tab, text="Create Custom Voice (cloning sample added to the voice list):").grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 5))
        
        ttk.Label(xtts_tab, text="Voice Name:").grid(row=5, column=0, sticky="w", pady=5)
        ttk.Entry(xtts_tab, textvariable=self.custom_voice_name, width=30).grid(row=5, column=1, sticky="w", pady=5, padx=(10, 0))
        
        ttk.Label(xtts_tab, text="Audio Sample:").grid(row=6, column=0, sticky="w", pady=5)
        custom_voice_frame = ttk.Frame(xtts_tab)
        custom_voice_frame.grid(row=6, column=1, columnspan=2, sticky="ew", pady=5, padx=(10, 0))
        ttk.Entry(custom_voice_frame, textvariable=self.custom_voice_source, width=40).grid(row=0, column=0, sticky="ew")
        ttk.Button(custom_voice_frame, text="Browse...", command=self.browse_custom_voice_source).grid(row=0, column=1, padx=(5, 0))
        
        ttk.Button(xtts_tab, text="Create Voice", command=self.create_custom_voice).grid(row=7, column=1, sticky="w", pady=(5, 0), padx=(10, 0))
        ttk.Label(xtts_tab, text="Tip: use a clean 6-30s speech recording. The sample is converted to mono WAV\nand saved into the voices library for the selected language.").grid(row=8, column=0, columnspan=3, sticky="w", pady=(5, 0))
        
        # Translation tab
        translation_tab = ttk.Frame(notebook, padding="10")
        notebook.add(translation_tab, text="Translation")
        
        # Translation options
        ttk.Label(translation_tab, text="Translate ebook content:").grid(row=0, column=0, sticky="w", pady=5)
        translate_check = ttk.Checkbutton(translation_tab, variable=self.translate_var)
        translate_check.grid(row=0, column=1, sticky="w", pady=5, padx=(10, 0))
        
        ttk.Label(translation_tab, text="Source Language:").grid(row=1, column=0, sticky="w", pady=5)
        source_lang_combo = FilterableCombobox(translation_tab, textvariable=self.source_language, width=40)  # Increased width
        if USE_NEW_LANGUAGE_MAPPING:
            language_display_names, language_values, language_search_terms = build_language_options()
            source_lang_combo.set_completion_list(language_display_names, language_search_terms)
            # Store mapping for this combobox
            self.source_lang_display_to_value = dict(zip(language_display_names, language_values))
            self.source_lang_value_to_display = dict(zip(language_values, language_display_names))
            
            # Set default display value if it exists in our mapping
            default_lang = self.source_language.get()
            # Try to find the display name for the default language
            display_name = None
            for disp_name, value in self.source_lang_display_to_value.items():
                if value == default_lang or (default_lang in LANGUAGE_CODES and value == default_lang):
                    display_name = disp_name
                    break
            
            if display_name:
                source_lang_combo.set(display_name)
            else:
                # Fallback to setting the value directly if no display name found
                source_lang_combo.set(default_lang)
        else:
            source_lang_combo.set_completion_list(list(language_mapping.keys()))
        source_lang_combo.grid(row=1, column=1, sticky="w", pady=5, padx=(10, 0))
        
        # Bind selection event to update the underlying variable
        if USE_NEW_LANGUAGE_MAPPING:
            def on_source_lang_select(event):
                selected_display = source_lang_combo.get()
                if selected_display in self.source_lang_display_to_value:
                    self.source_language.set(self.source_lang_display_to_value[selected_display])
            source_lang_combo.bind('<<ComboboxSelected>>', on_source_lang_select, add='+')
        
        ttk.Label(translation_tab, text="Target Language:").grid(row=2, column=0, sticky="w", pady=5)
        target_lang_combo = FilterableCombobox(translation_tab, textvariable=self.target_language, width=40)  # Increased width
        if USE_NEW_LANGUAGE_MAPPING:
            language_display_names, language_values, language_search_terms = build_language_options()
            target_lang_combo.set_completion_list(language_display_names, language_search_terms)
            # Store mapping for this combobox
            self.target_lang_display_to_value = dict(zip(language_display_names, language_values))
            self.target_lang_value_to_display = dict(zip(language_values, language_display_names))
            
            # Set default display value if it exists in our mapping
            default_lang = self.target_language.get()
            # Try to find the display name for the default language
            display_name = None
            for disp_name, value in self.target_lang_display_to_value.items():
                if value == default_lang or (default_lang in LANGUAGE_CODES and value == default_lang):
                    display_name = disp_name
                    break
            
            if display_name:
                target_lang_combo.set(display_name)
            else:
                # Fallback to setting the value directly if no display name found
                target_lang_combo.set(default_lang)
        else:
            target_lang_combo.set_completion_list(list(language_mapping.keys()))
        target_lang_combo.grid(row=2, column=1, sticky="w", pady=5, padx=(10, 0))
        
        # Bind selection event to update the underlying variable
        if USE_NEW_LANGUAGE_MAPPING:
            def on_target_lang_select(event):
                selected_display = target_lang_combo.get()
                if selected_display in self.target_lang_display_to_value:
                    self.target_language.set(self.target_lang_display_to_value[selected_display])
            target_lang_combo.bind('<<ComboboxSelected>>', on_target_lang_select, add='+')
        
        ttk.Label(translation_tab, text="Translation Method:").grid(row=3, column=0, sticky="w", pady=5)
        self.method_combo = ttk.Combobox(translation_tab, textvariable=self.translation_method, width=20)
        self.method_combo['values'] = ['google', 'deepl', 'deepl_parser', 'argos', 'llm']
        self.method_combo.grid(row=3, column=1, sticky="w", pady=5, padx=(10, 0))
        
        ttk.Label(translation_tab, text="Note: Translation requires internet connection for Google Translate").grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))
        
        # Cloud tab: run the conversion on a free cloud GPU with the current settings
        cloud_tab = ttk.Frame(notebook, padding="10")
        notebook.add(cloud_tab, text="Cloud")
        
        ttk.Label(cloud_tab, text="No GPU or not enough VRAM? Send the current settings to a free cloud GPU (Google Colab):").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Button(cloud_tab, text="Open Google Colab with current settings", command=self.open_colab_with_settings).grid(row=1, column=0, sticky="w", pady=5)
        ttk.Label(cloud_tab, text="Free T4 GPU, ~12h session limit").grid(row=1, column=1, sticky="w", pady=5, padx=(10, 0))
        ttk.Label(cloud_tab, text="Colab receives your language, TTS engine, voice, output format and translation\nsettings automatically. You only upload the ebook there; conversion (and translation)\nrun in the cloud and the finished audiobook is offered for download.").grid(row=2, column=0, columnspan=2, sticky="w", pady=(15, 0))
        
        # Convert button
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=1, column=0, columnspan=3, pady=15)
        
        self.convert_button = ttk.Button(button_frame, text="Convert to Audiobook", command=self.convert_ebook)
        self.convert_button.pack(side=tk.LEFT, padx=(0, 10))
        
        # Pause/Resume button
        self.pause_resume_button = ttk.Button(button_frame, text="Pause", command=self.toggle_pause, state='disabled')
        self.pause_resume_button.pack(side=tk.LEFT, padx=(0, 10))
        
        # Stop button
        self.stop_button = ttk.Button(button_frame, text="Stop", command=self.stop_conversion, state='disabled')
        self.stop_button.pack(side=tk.LEFT)
        
        # Progress bar
        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress.grid(row=2, column=0, columnspan=3, sticky="ew", pady=5)
        
        # Status text
        ttk.Label(main_frame, text="Status:").grid(row=3, column=0, sticky="w", pady=(15, 5))
        self.status_text = scrolledtext.ScrolledText(main_frame, height=12, width=80)
        self.status_text.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=5)
        # Make status messages copyable (right-click menu + layout-independent shortcuts)
        self._setup_status_copy(self.status_text)
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)
        main_tab.columnconfigure(1, weight=1)
        xtts_tab.columnconfigure(1, weight=1)
        translation_tab.columnconfigure(1, weight=1)
        
        # Initialize with compatible engines for default language
        self.update_tts_engines_for_language(default_language_code)
        # Initialize translation methods for the default language pair
        self.update_translation_methods()
        # Initialize the voice list for the default engine/language
        self.update_voice_list()
        
    def on_language_change(self, *args):
        """Update TTS engine options when language changes"""
        selected_language = self.language.get()
        self.update_tts_engines_for_language(selected_language)
        self.update_voice_list()
        
    def on_tts_engine_change(self, *args):
        """Refresh voice options when the TTS engine changes"""
        self.update_voice_list()
        
    def on_translation_language_change(self, *args):
        """Update translation method options when source/target language changes"""
        self.update_translation_methods()
        
    def update_translation_methods(self):
        """Show only translation methods supporting both selected languages"""
        if self.method_combo is None:
            return
        # The comboboxes may hold display names like "English (English) [eng]",
        # so normalize them to plain language codes before matching
        source_lang = self.normalize_language_code(self.source_language.get())
        target_lang = self.normalize_language_code(self.target_language.get())
        if not source_lang or not target_lang:
            return
        compatible_methods = get_compatible_translation_methods(source_lang, target_lang)
        self.method_combo['values'] = compatible_methods
        # Keep the current method if still compatible, otherwise switch to the first one
        if self.translation_method.get() not in compatible_methods:
            self.translation_method.set(compatible_methods[0])
        self.update_status(f"Compatible translation methods for '{source_lang}' -> '{target_lang}': {', '.join(compatible_methods)}")
        
    def update_tts_engines_for_language(self, language_code):
        """Update TTS engine combobox with engines compatible with the selected language"""
        if self.tts_combo is None:
            return
            
        # Get compatible engines for the selected language
        compatible_engines = get_compatible_tts_engines(language_code)
        
        # Update the combobox values to show only compatible engines
        compatible_engine_names = [name for name, engine in TTS_ENGINES.items() if engine in compatible_engines]
        self.tts_combo['values'] = compatible_engine_names
        
        # If there are compatible engines, select the first one
        # Otherwise, keep the current selection if it's in the list
        if compatible_engine_names:
            # Prefer XTTSv2 if it's compatible, otherwise use the first compatible engine
            if 'XTTSv2' in compatible_engine_names:
                self.tts_engine.set('XTTSv2')
            else:
                self.tts_engine.set(compatible_engine_names[0])
        elif self.tts_engine.get() not in compatible_engine_names:
            # If current selection is not compatible and not in the list, default to XTTSv2 if it exists in the full list
            if 'XTTSv2' in list(TTS_ENGINES.keys()):
                self.tts_engine.set('XTTSv2')
            
        # Show a warning if there are no compatible engines
        if not compatible_engines:
            self.update_status(f"Warning: No TTS engines found for language '{language_code}'. Using default engine.")
        else:
            # Show which engines are compatible
            self.update_status(f"Compatible TTS engines for '{language_code}': {', '.join(compatible_engine_names)}")
        
    def _resolve_lang_dir(self):
        """Map the selected language to an existing folder inside voices_dir (ISO-639-3)"""
        raw = self.language.get()
        candidates = []
        if raw:
            candidates.append(raw)
            normalized = self.normalize_language_code(raw)
            if normalized:
                candidates.append(normalized)
            if USE_NEW_LANGUAGE_MAPPING:
                candidates.extend(get_language_abbreviations(raw) or [])
                lang_name = get_language_name(raw)
                if lang_name:
                    candidates.extend(get_language_abbreviations(lang_name) or [])
        for code in candidates:
            if code and os.path.isdir(os.path.join(voices_dir, code)):
                return code
        return 'eng'
        
    def update_voice_list(self):
        """Rebuild the voice combobox with voices available for the current TTS engine and language"""
        if self.voice_combo is None:
            return
        engine = TTS_ENGINES.get(self.tts_engine.get(), self.tts_engine.get())
        lang_dir = self._resolve_lang_dir()
        options = [('Default (engine builtin)', '')]
        # Kokoro uses named model presets instead of cloning samples
        if engine == TTS_ENGINES.get('KOKORO'):
            presets = default_engine_settings.get(engine, {}).get('voices', {})
            options += [(f'{name} [preset]', value) for name, value in presets.items()]
        elif engine == TTS_ENGINES['BARK']:
            # Bark ships pre-generated speaker prompts per language (npz + wav preview)
            speakers_path = default_engine_settings[TTS_ENGINES['BARK']].get('speakers_path', '')
            lang_iso1 = None
            try:
                from iso639 import languages as iso_languages
                lang_iso1 = iso_languages.get(part3=lang_dir).part1
            except Exception:
                pass
            if lang_iso1 and os.path.isdir(speakers_path):
                options += [
                    (f.stem, str(f))
                    for f in sorted(Path(speakers_path).rglob(f'{lang_iso1}_speaker_*.wav'))
                ]
        if engine != TTS_ENGINES.get('KOKORO'):
            # Cloning samples shipped for the selected language, plus the english library as fallback
            seen = set()
            for folder in dict.fromkeys([lang_dir, 'eng']):
                folder_path = Path(voices_dir) / folder
                if folder_path.is_dir():
                    for f in sorted(folder_path.rglob('*.wav')):
                        if f.stem not in seen:
                            seen.add(f.stem)
                            options.append((f.stem, str(f)))
        self.voice_options = options
        self.voice_combo['values'] = [name for name, _ in options]
        # Keep the current selection if still available, otherwise reset to default
        current = self.voice_choice.get()
        if current not in [name for name, _ in options]:
            self.voice_choice.set(options[0][0])
            self.voice_file.set(options[0][1])
        self.update_status(f"{len(options) - 1} voices available for engine '{self.tts_engine.get()}' / language '{lang_dir}'")
        
    def _get_selected_voice_value(self):
        selected = self.voice_choice.get()
        for name, value in self.voice_options:
            if name == selected:
                return value
        return ''
        
    def on_voice_selected(self, event=None):
        """Apply the voice chosen in the combobox"""
        value = self._get_selected_voice_value()
        self.voice_file.set(value)
        
    def preview_voice(self):
        """Play the selected voice sample"""
        value = self.voice_file.get() or self._get_selected_voice_value()
        if not value:
            messagebox.showinfo('Voice Preview', 'The default engine voice has no local sample to play.')
            return
        if not os.path.isfile(value):
            messagebox.showinfo('Voice Preview', f"'{self.voice_choice.get()}' is a model preset voice.\nIt has no local audio sample, preview is only available after conversion.")
            return
        try:
            if sys.platform == 'win32' and value.lower().endswith('.wav'):
                import winsound
                winsound.PlaySound(value, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                ffplay = shutil.which('ffplay')
                if ffplay:
                    self._preview_proc = subprocess.Popen(
                        [ffplay, '-nodisp', '-autoexit', '-loglevel', 'quiet', value],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                else:
                    messagebox.showwarning('Voice Preview', 'No audio player found (ffplay is missing).')
                    return
            self.update_status(f'Playing voice sample: {os.path.basename(value)}')
        except Exception as e:
            messagebox.showerror('Voice Preview', f'Failed to play the sample: {e}')
            
    def stop_preview(self):
        """Stop the voice sample playback"""
        try:
            if sys.platform == 'win32':
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            proc = getattr(self, '_preview_proc', None)
            if proc and proc.poll() is None:
                proc.terminate()
        except Exception:
            pass
            
    def browse_custom_voice_source(self):
        filename = filedialog.askopenfilename(
            title='Select Audio Sample for the Custom Voice',
            filetypes=[
                ('Audio files', '*.wav *.mp3 *.flac *.ogg *.m4a'),
                ('All files', '*.*')
            ]
        )
        if filename:
            self.custom_voice_source.set(filename)
            
    def create_custom_voice(self):
        """Convert the selected audio sample to WAV and store it in the voices library"""
        name = re.sub(r'[^\w-]', '', self.custom_voice_name.get().strip())
        source = self.custom_voice_source.get().strip()
        if not name:
            messagebox.showerror('Create Custom Voice', 'Please enter a valid voice name (letters, digits, - or _).')
            return
        if not source or not os.path.isfile(source):
            messagebox.showerror('Create Custom Voice', 'Please select an existing audio sample file.')
            return
        lang_dir = self._resolve_lang_dir()
        dest_dir = os.path.join(voices_dir, lang_dir, 'custom')
        dest = os.path.join(dest_dir, f'{name}.wav')
        if os.path.exists(dest):
            if not messagebox.askyesno('Create Custom Voice', f"Voice '{name}' already exists. Overwrite it?"):
                return
        try:
            os.makedirs(dest_dir, exist_ok=True)
            ffmpeg = shutil.which('ffmpeg')
            if ffmpeg:
                # normalize to mono 24kHz wav, the format expected by the cloning engines
                result = subprocess.run(
                    [ffmpeg, '-y', '-i', source, '-ac', '1', '-ar', '24000', dest],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
                )
                if result.returncode != 0 or not os.path.exists(dest):
                    raise RuntimeError(result.stderr.splitlines()[-1] if result.stderr else 'ffmpeg failed')
            elif source.lower().endswith('.wav'):
                shutil.copyfile(source, dest)
            else:
                messagebox.showerror('Create Custom Voice', 'ffmpeg not found: only .wav samples can be imported without conversion.')
                return
        except Exception as e:
            messagebox.showerror('Create Custom Voice', f'Failed to create the voice: {e}')
            return
        self.update_status(f"Custom voice '{name}' created: {dest}")
        self.update_voice_list()
        self.voice_choice.set(name)
        self.voice_file.set(dest)
        messagebox.showinfo('Create Custom Voice', f"Voice '{name}' was added to the voice list and selected.")
        
    def browse_ebook(self):
        filename = filedialog.askopenfilename(
            title="Select Ebook File",
            filetypes=[
                ("Ebook files", "*.epub *.pdf *.mobi *.azw *.azw3 *.fb2 *.txt"),
                ("All files", "*.*")
            ]
        )
        if filename:
            self.ebook_path.set(filename)
            # Set default output directory to the same directory as the ebook
            if not self.output_dir.get():
                self.output_dir.set(os.path.dirname(filename))
            
    def browse_output(self):
        directory = filedialog.askdirectory(title="Select Output Directory")
        if directory:
            self.output_dir.set(directory)
            
    def browse_voice(self):
        filename = filedialog.askopenfilename(
            title="Select Voice Cloning File",
            filetypes=[
                ("Audio files", "*.wav *.mp3 *.flac *.ogg"),
                ("All files", "*.*")
            ]
        )
        if filename:
            self.voice_file.set(filename)
            
    def generate_new_session_id(self):
        """Generate a new UUID for session ID"""
        new_session_id = str(uuid.uuid4())
        self.session_id_var.set(new_session_id)
        self.update_status(f"Generated new session ID: {new_session_id}")
            
    def convert_ebook(self):
        # Validate inputs
        if not self.ebook_path.get():
            messagebox.showerror("Error", "Please select an ebook file.")
            return
            
        if not os.path.exists(self.ebook_path.get()):
            messagebox.showerror("Error", "The selected ebook file does not exist.")
            return
            
        # Set default output directory if not specified
        if not self.output_dir.get():
            self.output_dir.set(os.path.dirname(self.ebook_path.get()) or os.getcwd())
            
        # Create output directory if it doesn't exist
        try:
            os.makedirs(self.output_dir.get(), exist_ok=True)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create output directory: {e}")
            return
            
        # Check if the selected TTS engine is compatible with the selected language
        selected_language = self.language.get()
        selected_engine = self.tts_engine.get()
        compatible_engines = get_compatible_tts_engines(selected_language)
        
        if TTS_ENGINES[selected_engine] not in compatible_engines:
            # Try to find a compatible engine
            if compatible_engines:
                # Find the name corresponding to the first compatible engine
                compatible_engine_name = 'XTTSv2'  # Default fallback
                for name, engine in TTS_ENGINES.items():
                    if engine in compatible_engines:
                        compatible_engine_name = name
                        break
                        
                # Ask user if they want to switch to a compatible engine
                compatible_engine_names = [name for name, engine in TTS_ENGINES.items() if engine in compatible_engines]
                result = messagebox.askyesno(
                    "Incompatible TTS Engine", 
                    f"The selected TTS engine '{selected_engine}' does not support the language '{selected_language}'.\n\n"
                    f"Compatible engines: {', '.join(compatible_engine_names)}\n\n"
                    f"Would you like to switch to '{compatible_engine_name}' which supports this language?"
                )
                
                if result:
                    self.tts_engine.set(compatible_engine_name)
                else:
                    messagebox.showwarning(
                        "Warning", 
                        f"Proceeding with '{selected_engine}' which may not work properly with '{selected_language}'."
                    )
            else:
                result = messagebox.askyesno(
                    "No Compatible TTS Engines", 
                    f"No TTS engines found that support the language '{selected_language}'.\n\n"
                    "Do you want to continue anyway? This may cause the application to hang or fail."
                )
                
                if not result:
                    return  # User chose to cancel
            
        # Disable the convert button and enable pause/stop buttons during conversion
        self.convert_button.config(state='disabled')
        self.pause_resume_button.config(state='normal', text="Pause")
        self.stop_button.config(state='normal')
        self.is_converting = True
        self.is_paused = False
        self.progress.start()
        
        # Clear status text
        self.status_text.delete(1.0, tk.END)
        
        # Run conversion in a separate thread to avoid blocking the UI
        self.conversion_thread = threading.Thread(target=self._convert_ebook_thread)
        self.conversion_thread.daemon = True
        self.conversion_thread.start()
        
    def toggle_pause(self):
        if self.is_converting:
            if self.is_paused:
                # Resume conversion
                self.is_paused = False
                self.pause_resume_button.config(text="Pause")
                # Remove pause flag from session
                if self.session_context and self.session_id:
                    session = self.session_context.get_session(self.session_id)
                    session['pause_requested'] = False
                self.update_status("Conversion resumed")
            else:
                # Pause conversion
                self.is_paused = True
                self.pause_resume_button.config(text="Resume")
                # Set pause flag in session
                if self.session_context and self.session_id:
                    session = self.session_context.get_session(self.session_id)
                    session['pause_requested'] = True
                self.update_status("Conversion paused")
                
    def stop_conversion(self):
        if self.is_converting:
            # Confirm with user
            if messagebox.askyesno("Stop Conversion", "Are you sure you want to stop the conversion?"):
                self.update_status("Stopping conversion...")
                # Set cancellation flag in session
                if self.session_context and self.session_id:
                    session = self.session_context.get_session(self.session_id)
                    session['cancellation_requested'] = True
                    session['pause_requested'] = False  # Also remove pause flag
                self.is_converting = False
                self.is_paused = False
                self.progress.stop()
                self.convert_button.config(state='normal')
                self.pause_resume_button.config(state='disabled', text="Pause")
                self.stop_button.config(state='disabled')
                self.update_status("Conversion stopped by user")
                
    def _collect_cloud_settings(self):
        """Gather the current UI selections into a plain dict for the cloud notebook.
        Only transferable settings are included (the ebook file itself is uploaded in
        the cloud). The voice is sent by name so the notebook can resolve it in the
        cloned repo's voices/ directory."""
        cfg = {
            'repo': CLOUD_REPO,
            'branch': CLOUD_BRANCH,
            'language': self.normalize_language_code(self.language.get()),
            'tts_engine': TTS_ENGINES.get(self.tts_engine.get(), self.tts_engine.get()),
            'output_format': self.output_format.get(),
            'voice': self.voice_choice.get() or None,
        }
        # Numeric tuning parameters (only sent when the UI provides a value)
        try:
            cfg['temperature'] = self.temperature.get()
        except Exception:
            pass
        try:
            cfg['repetition_penalty'] = self.repetition_penalty.get()
        except Exception:
            pass
        try:
            cfg['speed'] = self.speed.get()
        except Exception:
            pass
        # Translation settings mirror the Translation tab
        if self.translate_var.get():
            cfg['translate'] = True
            cfg['source_lang'] = self.normalize_language_code(self.source_language.get())
            cfg['target_lang'] = self.normalize_language_code(self.target_language.get())
            cfg['translation_method'] = self.translation_method.get()
        return cfg

    def open_colab_with_settings(self):
        """Encode the current settings into the Colab URL and open it in the browser.
        The notebook reads them from the URL automatically; the base64 config is also
        copied to the clipboard as a manual-paste fallback."""
        try:
            cfg = self._collect_cloud_settings()
            raw = json.dumps(cfg, ensure_ascii=False).encode('utf-8')
            config_b64 = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
            url = f'{COLAB_NOTEBOOK_URL}?c={config_b64}'
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(config_b64)
            except Exception:
                pass
            webbrowser.open(url)
            self.update_status('Opening Google Colab with current settings (config also copied to clipboard).')
            messagebox.showinfo(
                'Cloud conversion',
                'Google Colab is opening in your browser with your current settings.\n\n'
                '1. Run the notebook cells (top to bottom).\n'
                '2. Upload your ebook file when prompted.\n'
                '3. The conversion (and translation, if enabled) runs on the cloud GPU and\n'
                '   the finished audiobook is offered for download.\n\n'
                "If the settings are not picked up automatically, paste the config (already\n"
                "copied to your clipboard) into the 'config_b64' field in the first cell."
            )
        except Exception as e:
            messagebox.showerror('Cloud conversion', f'Could not open Colab: {e}')

    def _convert_ebook_thread(self):
        temp_dir = None
        original_ebook_path = None
        
        try:
            # Prepare arguments similar to command line
            args = {
                'ebook': self.ebook_path.get(),
                'ebook_list': None,
                'output_dir': self.output_dir.get() if self.output_dir.get() else 'audiobooks',
                'language': self.normalize_language_code(self.language.get()),
                'device': 'cuda' if self.device.get() == 'gpu' else self.device.get(),
                'tts_engine': TTS_ENGINES.get(self.tts_engine.get(), self.tts_engine.get()),
                'headless': True,
                'voice': self.voice_file.get() if self.voice_file.get() else None,
                'custom_model': None,
                'fine_tuned': 'internal',
                'output_format': self.output_format.get(),
                'temperature': self.temperature.get(),
                'length_penalty': None,
                'num_beams': None,
                'repetition_penalty': self.repetition_penalty.get(),
                'top_k': None,
                'top_p': None,
                'speed': self.speed.get(),
                'enable_text_splitting': False,
                'text_temp': None,
                'waveform_temp': None,
                'is_gui_process': False,
                'audiobooks_dir': os.path.abspath(self.output_dir.get()) if self.output_dir.get() else os.path.abspath('audiobooks'),
                'output_split': False,
                'output_split_hours': 2,
                'session': self.session_id_var.get() if self.session_id_var.get() else None,  # Use provided session ID or None
                'script_mode': 'native',
                'share': False,
                'workflow': False,
                'version': False
            }
            
            # Final check: ensure the selected TTS engine is compatible with the selected language
            # This is a last resort check before starting the conversion
            compatible_engines = get_compatible_tts_engines(args['language'])
            if args['tts_engine'] not in compatible_engines and compatible_engines:
                # Find a compatible engine name for display
                compatible_engine_name = 'XTTSv2'  # Default fallback
                for name, engine in TTS_ENGINES.items():
                    if engine in compatible_engines:
                        compatible_engine_name = name
                        break
                # Update to use the compatible engine
                args['tts_engine'] = TTS_ENGINES[compatible_engine_name]
                self.root.after(0, self.update_status, f"Switching to compatible TTS engine: {compatible_engine_name}")
            
            # Store original ebook path
            original_ebook_path = args['ebook']
            
            # If translation is requested, we need to translate the ebook content first
            if self.translate_var.get():
                try:
                    # Log raw values for debugging
                    self.root.after(0, self.update_status, f"Translation checkbox: {self.translate_var.get()}")
                    self.root.after(0, self.update_status, f"Raw language codes: {self.source_language.get()} -> {self.target_language.get()}")
                    self.root.after(0, self.update_status, f"Translation method: {self.translation_method.get()}")
                    
                    self.root.after(0, self.update_status, f"Starting ebook translation: {self.source_language.get()} -> {self.target_language.get()} using {self.translation_method.get()}")
                    
                    # Normalize language codes for translation
                    source_lang = self.normalize_language_code(self.source_language.get())
                    target_lang = self.normalize_language_code(self.target_language.get())
                    
                    # Log the normalized language codes for debugging
                    self.root.after(0, self.update_status, f"Normalized language codes: {source_lang} -> {target_lang}")
                    
                    # Check if source and target languages are the same
                    if source_lang == target_lang:
                        self.root.after(0, self.update_status, "WARNING: Source and target languages are the same - translation will be skipped")
                    else:
                        # Only proceed with translation if languages are different
                        # Create a temporary directory for the translated ebook
                        temp_dir = tempfile.mkdtemp()
                        original_filename = os.path.basename(original_ebook_path)
                        original_ext = os.path.splitext(original_filename)[1].lower()
                        
                        # For PDF files, the translation function returns a markdown file by default
                        # For other formats, we'll use the same extension
                        if original_ext == '.pdf':
                            translated_ebook_filename = f"translated_{os.path.splitext(original_filename)[0]}.md"
                        else:
                            translated_ebook_filename = f"translated_{original_filename}"
                            
                        translated_ebook_path = os.path.join(temp_dir, translated_ebook_filename)
                        
                        # Use the improved translator with user feedback
                        try:
                            # Translate the ebook file with session directory support and parent window
                            actual_translated_path = translate_ebook_file(
                                original_ebook_path,
                                source_lang,
                                target_lang,
                                self.translation_method.get(),
                                translated_ebook_path,
                                temp_dir,  # Pass temporary directory for caching
                                self.root  # Pass parent window for dialog boxes
                            )
                        except Exception as improved_error:
                            # If the improved translator fails, show error and proceed with original file
                            self.root.after(0, self.update_status, f"Translation failed: {str(improved_error)}")
                            self.root.after(0, self.update_status, "Proceeding with normal conversion using original ebook.")
                            # Revert to original ebook path if translation failed
                            args['ebook'] = original_ebook_path
                            raise  # Re-raise to skip the rest of the translation block
                        
                        # Update the args to use the translated ebook
                        # Use the actual path returned by the translation function
                        args['ebook'] = actual_translated_path
                        
                        self.root.after(0, self.update_status, "Ebook translation completed successfully")
                        
                except Exception as e:
                    self.root.after(0, self.update_status, f"Translation failed: {str(e)}")
                    self.root.after(0, self.update_status, "Proceeding with normal conversion using original ebook.")
                    # Revert to original ebook path if translation failed
                    args['ebook'] = original_ebook_path
            else:
                # Log that translation was skipped
                self.root.after(0, self.update_status, "Translation skipped - checkbox not checked")
            
            # Create session context AFTER translation so it knows about the translated ebook
            self.session_context = SessionContext()
            
            # Use provided session ID or generate a new one
            if args['session']:
                self.session_id = args['session']
                self.update_status(f"Using existing session: {self.session_id}")
            else:
                self.session_id = args['session'] = str(uuid.uuid4())  # Use UUID instead of timestamp
                self.root.after(0, self.update_status, f"Generated new session ID: {self.session_id}")
                # Update the session ID field in the UI
                self.root.after(0, self.session_id_var.set, self.session_id)
            
            session = self.session_context.get_session(self.session_id)
            
            # Validate ebook file
            if not os.path.exists(args['ebook']):
                raise FileNotFoundError(f"Ebook file not found: {args['ebook']}")
            
            # Validate output directory
            if not os.path.exists(args['audiobooks_dir']):
                os.makedirs(args['audiobooks_dir'])
            
            # Update status
            self.root.after(0, self.update_status, f"Starting conversion of {os.path.basename(args['ebook'])}")
            
            # Call the conversion function
            progress_status, passed = convert_ebook(args, self.session_context)
            
            # Clean up temporary files if we created any
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    self.root.after(0, self.update_status, f"Warning: Failed to clean up temporary files: {str(e)}")
            
            if passed:
                self.root.after(0, self.conversion_complete, f"Conversion completed successfully! Audiobook saved to {args['audiobooks_dir']}")
            else:
                raise Exception(str(progress_status))
                
        except Exception as e:
            # Clean up temporary files if we created any
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as cleanup_error:
                    self.root.after(0, self.update_status, f"Warning: Failed to clean up temporary files: {str(cleanup_error)}")
            
            self.root.after(0, self.conversion_error, str(e))
    
    def normalize_language_code(self, lang_code):
        """
        Normalize language code using our new language codes mapping if available.
        """
        # Handle display names that might contain the actual code in brackets
        if USE_NEW_LANGUAGE_MAPPING:
            # Extract code from display name format "Language Name [code]" if needed
            if '[' in lang_code and lang_code.endswith(']'):
                # Extract the code from between brackets
                start = lang_code.rfind('[')
                if start != -1:
                    extracted_code = lang_code[start+1:-1]
                    lang_code = extracted_code
            
            # First try to get abbreviations for this language name
            abbreviations = get_language_abbreviations(lang_code)
            if abbreviations:
                # Return the first (primary) abbreviation
                return abbreviations[0]
            
            # If that didn't work, try to get the language name for this code
            lang_name = get_language_name(lang_code)
            if lang_name:
                # Try again with the language name
                abbreviations = get_language_abbreviations(lang_name)
                if abbreviations:
                    return abbreviations[0]
        
        # If our new mapping didn't work or isn't available, return the original code
        return lang_code

    def update_status(self, message):
        # Add timestamp to message
        timestamp = time.strftime("[%H:%M:%S] ", time.localtime())
        self.status_text.insert(tk.END, timestamp + message + "\n")
        self.status_text.see(tk.END)
        self.status_text.update_idletasks()

    def _setup_status_copy(self, widget):
        """Enable copying status text via a right-click menu and layout-independent shortcuts."""
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="Copy", command=lambda: self._status_copy_selection(widget))
        menu.add_command(label="Copy all", command=lambda: self._status_copy_all(widget))
        menu.add_separator()
        menu.add_command(label="Select all", command=lambda: self._status_select_all(widget))
        menu.add_command(label="Clear", command=lambda: widget.delete('1.0', tk.END))

        def show_menu(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
            return 'break'

        # right click (Button-3 on Windows/Linux, Button-2 on some macs)
        widget.bind('<Button-3>', show_menu)
        widget.bind('<Button-2>', show_menu)
        # Ctrl+C / Ctrl+A also fire under a Cyrillic layout, where the physical
        # C/A keys emit Cyrillic keysyms that Tk's default bindings ignore
        for seq in ('<Control-c>', '<Control-C>', '<Control-Cyrillic_es>', '<Control-Insert>'):
            widget.bind(seq, lambda e: self._status_copy_selection(widget))
        for seq in ('<Control-a>', '<Control-A>', '<Control-Cyrillic_ef>'):
            widget.bind(seq, lambda e: self._status_select_all(widget))

    def _status_copy_selection(self, widget):
        """Copy the current selection, or the whole log if nothing is selected."""
        try:
            text = widget.get('sel.first', 'sel.last')
        except tk.TclError:
            text = widget.get('1.0', tk.END)
        text = text.rstrip('\n')
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        return 'break'

    def _status_copy_all(self, widget):
        text = widget.get('1.0', tk.END).rstrip('\n')
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        return 'break'

    def _status_select_all(self, widget):
        widget.tag_add('sel', '1.0', tk.END)
        widget.mark_set('insert', '1.0')
        widget.see('insert')
        return 'break'
        
    def conversion_complete(self, message):
        self.progress.stop()
        self.convert_button.config(state='normal')
        self.pause_resume_button.config(state='disabled', text="Pause")
        self.stop_button.config(state='disabled')
        self.is_converting = False
        self.is_paused = False
        messagebox.showinfo("Success", message)
        
    def conversion_error(self, error_message):
        self.progress.stop()
        self.convert_button.config(state='normal')
        self.pause_resume_button.config(state='disabled', text="Pause")
        self.stop_button.config(state='disabled')
        self.is_converting = False
        self.is_paused = False
        messagebox.showerror("Error", f"Conversion failed: {error_message}")
        
    def setup_message_handler(self):
        # Check for messages in the queue periodically
        self.root.after(100, self.check_messages)
        
    def check_messages(self):
        try:
            while True:
                message = self.message_queue.get_nowait()
                self.update_status(message)
        except queue.Empty:
            pass
        
        # Continue checking if we're still converting
        if self.is_converting:
            self.root.after(100, self.check_messages)
        else:
            # Conversion finished
            pass
            
    def update_status_safe(self, message):
        # Thread-safe method to update status
        self.message_queue.put(message)

def main():
    root = tk.Tk()
    app = Ebook2AudiobookGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()