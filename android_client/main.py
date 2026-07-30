#!/usr/bin/env python3
"""ebook2audiobook - Android thin client (Kivy).

The phone does NOT convert anything: this app only collects the same settings
as the desktop "Cloud" tab (tkinter_ui._collect_cloud_settings), encodes them
into a base64url JSON string and opens the Google Colab notebook URL in the
browser. The heavy TTS/translation work runs on the free Colab GPU.

The app is intentionally self-contained (no imports from the repo lib/) so the
APK stays tiny: the language table below mirrors lib/language_codes.py.

Build: see Notebooks/build_android_apk.ipynb (buildozer only runs on Linux,
so the APK is built in Colab too).
"""
import base64
import json
import webbrowser

from kivy.app import App
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton

# Must match CLOUD_REPO / CLOUD_BRANCH in tkinter_ui.py
CLOUD_REPO = 'Tarkas/Book-to-audiobook'
CLOUD_BRANCH = 'main'
COLAB_NOTEBOOK_URL = (
    f'https://colab.research.google.com/github/{CLOUD_REPO}'
    f'/blob/{CLOUD_BRANCH}/Notebooks/colab_ebook2audiobook.ipynb'
)

# iso3 code -> all spellings used for the type-to-filter search.
# The first spelling is shown in the list. Mirrors lib/language_codes.py.
LANGS = [
    ('rus', ['русский', 'russian', 'ru']),
    ('eng', ['английский', 'english', 'en']),
    ('spa', ['испанский', 'spanish', 'español', 'es']),
    ('fra', ['французский', 'french', 'français', 'fr']),
    ('deu', ['немецкий', 'german', 'deutsch', 'de']),
    ('ita', ['итальянский', 'italian', 'italiano', 'it']),
    ('por', ['португальский', 'portuguese', 'português', 'pt']),
    ('nld', ['нидерландский', 'dutch', 'nederlands', 'nl']),
    ('pol', ['польский', 'polish', 'polski', 'pl']),
    ('ara', ['арабский', 'arabic', 'العربية', 'ar']),
    ('jpn', ['японский', 'japanese', '日本語', 'ja']),
    ('kor', ['корейский', 'korean', '한국어', 'ko']),
    ('zho', ['китайский', 'chinese', '中文', 'zh']),
    ('tur', ['турецкий', 'turkish', 'türkçe', 'tr']),
    ('hin', ['хинди', 'hindi', 'हिन्दी', 'hi']),
    ('ces', ['чешский', 'czech', 'čeština', 'cs']),
    ('dan', ['датский', 'danish', 'dansk', 'da']),
    ('fin', ['финский', 'finnish', 'suomi', 'fi']),
    ('ell', ['греческий', 'greek', 'ελληνικά', 'el']),
    ('heb', ['иврит', 'hebrew', 'עברית', 'he']),
    ('hun', ['венгерский', 'hungarian', 'magyar', 'hu']),
    ('lav', ['латышский', 'latvian', 'latviešu', 'lv']),
    ('lit', ['литовский', 'lithuanian', 'lietuvių', 'lt']),
    ('nob', ['норвежский', 'norwegian', 'norsk', 'no']),
    ('ron', ['румынский', 'romanian', 'română', 'ro']),
    ('slk', ['словацкий', 'slovak', 'slovenčina', 'sk']),
    ('slv', ['словенский', 'slovenian', 'slovenščina', 'sl']),
    ('swe', ['шведский', 'swedish', 'svenska', 'sv']),
    ('tha', ['тайский', 'thai', 'ไทย', 'th']),
    ('ukr', ['украинский', 'ukrainian', 'українська', 'uk']),
    ('vie', ['вьетнамский', 'vietnamese', 'tiếng việt', 'vi']),
    ('bul', ['болгарский', 'bulgarian', 'български', 'bg']),
    ('hrv', ['хорватский', 'croatian', 'hrvatski', 'hr']),
    ('srp', ['сербский', 'serbian', 'српски', 'sr']),
    ('cat', ['каталонский', 'catalan', 'català', 'ca']),
    ('est', ['эстонский', 'estonian', 'eesti', 'et']),
    ('glg', ['галисийский', 'galician', 'galego', 'gl']),
    ('msa', ['малайский', 'malay', 'bahasa melayu', 'ms']),
    ('tgl', ['тагальский', 'tagalog', 'tl']),
    ('ind', ['индонезийский', 'indonesian', 'bahasa indonesia', 'id']),
]

# Display name -> iso3 (same "Name / name [code]" idea as the desktop filter)
LANG_DISPLAY = {f'{names[0]} / {names[1]} [{code}]': code for code, names in LANGS}
LANG_SEARCH = {
    f'{names[0]} / {names[1]} [{code}]': ' '.join(names + [code]).lower()
    for code, names in LANGS
}

# Same engines as lib/models.py TTS_ENGINES
TTS_ENGINES = {
    'XTTSv2': 'xtts', 'BARK': 'bark', 'VITS': 'vits', 'FAIRSEQ': 'fairseq',
    'TACOTRON2': 'tacotron', 'YOURTTS': 'yourtts', 'COSYVOICE': 'cosyvoice',
    'KOKORO': 'kokoro', 'MOSSTTSNANO': 'mosstts_nano',
}
OUTPUT_FORMATS = ['m4b', 'mp3', 'wav', 'flac']
TRANSLATION_METHODS = ['google', 'deepl', 'deepl_parser', 'argos']

# Universal voices: XTTS clones the timbre for ANY language, so these
# curated voices from voices/eng/ work for every book language. Display
# label -> file name (resolved by the notebook via glob in voices/**).
VOICE_DEFAULT = 'По умолчанию (движок сам выберет)'
VOICES = {
    VOICE_DEFAULT: None,
    'Женский · Alexandra Hisakawa': 'AlexandraHisakawa',
    'Женский · Ana Florence': 'AnaFlorence',
    'Женский · Claribel Dervla': 'ClaribelDervla',
    'Женский · Daenerys Targaryen': 'DaenerysTargaryen',
    'Женский · Rosamund Pike': 'RosamundPike',
    'Женский · Sofia Hellen': 'SofiaHellen',
    'Женский · Tanja Adelina': 'TanjaAdelina',
    'Мужской · Aaron Dreschner': 'AaronDreschner',
    'Мужской · Baldur Sanjin': 'BaldurSanjin',
    'Мужской · Kumar Dahl': 'KumarDahl',
    'Мужской · Ludvig Milivoj': 'LudvigMilivoj',
    'Мужской · Morgan Freeman': 'MorganFreeman',
    'Мужской · Ray Porter': 'RayPorter',
    'Мужской · Viktor Eka': 'ViktorEka',
    'Мужской (пожилой) · David Attenborough': 'DavidAttenborough',
}


def open_url(url):
    """Open a URL in the phone browser (Android intent, desktop fallback)."""
    try:
        from jnius import autoclass, cast
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        Intent = autoclass('android.content.Intent')
        Uri = autoclass('android.net.Uri')
        intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
        activity = cast('android.app.Activity', PythonActivity.mActivity)
        activity.startActivity(intent)
    except Exception:
        webbrowser.open(url)


class LanguagePicker(BoxLayout):
    """Filter field + button opening a filtered popup list of languages."""

    def __init__(self, default_code='eng', **kwargs):
        super().__init__(orientation='horizontal', size_hint_y=None,
                         height=dp(44), spacing=dp(4), **kwargs)
        self.selected_code = default_code
        default_display = next(
            (d for d, c in LANG_DISPLAY.items() if c == default_code),
            list(LANG_DISPLAY)[0])
        self.button = Button(text=default_display, halign='left',
                             valign='middle', shorten=True)
        self.button.bind(size=lambda b, s: setattr(b, 'text_size', s))
        self.button.bind(on_release=lambda *_: self.open_popup())
        self.add_widget(self.button)

    def open_popup(self):
        content = BoxLayout(orientation='vertical', spacing=dp(4),
                            padding=dp(4))
        filter_input = TextInput(hint_text='Фильтр: рус / ru / russian…',
                                 size_hint_y=None, height=dp(44),
                                 multiline=False)
        content.add_widget(filter_input)
        scroll = ScrollView()
        listbox = GridLayout(cols=1, size_hint_y=None, spacing=dp(2))
        listbox.bind(minimum_height=listbox.setter('height'))
        scroll.add_widget(listbox)
        content.add_widget(scroll)
        popup = Popup(title='Выбор языка', content=content,
                      size_hint=(0.95, 0.9))

        def rebuild(*_):
            needle = filter_input.text.strip().lower()
            listbox.clear_widgets()
            for display, code in LANG_DISPLAY.items():
                if needle and needle not in LANG_SEARCH[display]:
                    continue
                btn = Button(text=display, size_hint_y=None, height=dp(44))

                def pick(_btn, d=display, c=code):
                    self.selected_code = c
                    self.button.text = d
                    popup.dismiss()

                btn.bind(on_release=pick)
                listbox.add_widget(btn)

        filter_input.bind(text=rebuild)
        rebuild()
        popup.open()
        filter_input.focus = True


class Ebook2AudiobookClient(App):
    title = 'ebook2audiobook · облако'

    def build(self):
        Window.softinput_mode = 'below_target'
        root = ScrollView()
        form = GridLayout(cols=1, size_hint_y=None, padding=dp(12),
                          spacing=dp(8))
        form.bind(minimum_height=form.setter('height'))
        root.add_widget(form)

        def label(text):
            lbl = Label(text=text, size_hint_y=None, height=dp(28),
                        halign='left', valign='bottom')
            lbl.bind(size=lambda l, s: setattr(l, 'text_size', s))
            form.add_widget(lbl)

        label('Язык озвучки:')
        self.language = LanguagePicker(default_code='eng')
        form.add_widget(self.language)

        label('TTS движок:')
        self.engine = Spinner(text='XTTSv2', values=list(TTS_ENGINES),
                              size_hint_y=None, height=dp(44))
        form.add_widget(self.engine)

        label('Формат аудио:')
        self.out_format = Spinner(text='m4b', values=OUTPUT_FORMATS,
                                  size_hint_y=None, height=dp(44))
        form.add_widget(self.out_format)

        label('Голос (универсальный, подходит любому языку):')
        self.voice = Spinner(text=VOICE_DEFAULT, values=list(VOICES),
                             size_hint_y=None, height=dp(44))
        form.add_widget(self.voice)

        label('Или своё имя голоса из voices/ (перекрывает выбор выше):')
        self.voice_custom = TextInput(size_hint_y=None, height=dp(44),
                                      multiline=False,
                                      hint_text='например KumarDahl')
        form.add_widget(self.voice_custom)

        label('Скорость (0.5–2.0):')
        self.speed = TextInput(text='1.0', size_hint_y=None, height=dp(44),
                               multiline=False, input_filter='float')
        form.add_widget(self.speed)

        # Translation toggle: a big colored button instead of a checkbox (the
        # stock Kivy checkbox is nearly invisible on phone screens).
        self.translate = ToggleButton(text='Перевод: выключен',
                                      size_hint_y=None, height=dp(56),
                                      background_color=(0.55, 0.55, 0.55, 1))

        def _tr_toggle(btn, *_):
            on = btn.state == 'down'
            btn.text = ('Перевод: ВКЛЮЧЁН — книга будет переведена'
                        if on else 'Перевод: выключен')
            btn.background_color = ((0.2, 0.7, 0.2, 1) if on
                                    else (0.55, 0.55, 0.55, 1))

        self.translate.bind(state=_tr_toggle)
        form.add_widget(self.translate)

        label('Язык оригинала:')
        self.source_lang = LanguagePicker(default_code='eng')
        form.add_widget(self.source_lang)

        label('Язык перевода:')
        self.target_lang = LanguagePicker(default_code='rus')
        form.add_widget(self.target_lang)

        label('Метод перевода:')
        self.method = Spinner(text='google', values=TRANSLATION_METHODS,
                              size_hint_y=None, height=dp(44))
        form.add_widget(self.method)

        run_btn = Button(text='Запустить в облаке (Colab)',
                         size_hint_y=None, height=dp(56),
                         background_color=(0.2, 0.6, 0.2, 1))
        run_btn.bind(on_release=lambda *_: self.launch_cloud())
        form.add_widget(run_btn)

        hint = Label(
            text='Книга загружается уже в Colab. Настройки передаются через '
                 'ссылку и копируются в буфер обмена как запасной вариант.',
            size_hint_y=None, halign='left', valign='top')
        hint.bind(width=lambda l, w: setattr(l, 'text_size', (w, None)))
        hint.bind(texture_size=lambda l, s: setattr(l, 'height', s[1]))
        form.add_widget(hint)
        return root

    def collect_cloud_settings(self):
        """Same payload shape as tkinter_ui._collect_cloud_settings()."""
        cfg = {
            'repo': CLOUD_REPO,
            'branch': CLOUD_BRANCH,
            'language': self.language.selected_code,
            'tts_engine': TTS_ENGINES.get(self.engine.text, self.engine.text),
            'output_format': self.out_format.text,
            'voice': (self.voice_custom.text.strip()
                      or VOICES.get(self.voice.text)),
        }
        try:
            cfg['speed'] = float(self.speed.text)
        except ValueError:
            pass
        if self.translate.state == 'down':
            cfg['translate'] = True
            cfg['source_lang'] = self.source_lang.selected_code
            cfg['target_lang'] = self.target_lang.selected_code
            cfg['translation_method'] = self.method.text
        return cfg

    def launch_cloud(self):
        cfg = self.collect_cloud_settings()
        raw = json.dumps(cfg, ensure_ascii=False).encode('utf-8')
        config_b64 = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
        try:
            Clipboard.copy(config_b64)
        except Exception:
            pass
        open_url(f'{COLAB_NOTEBOOK_URL}?c={config_b64}')


if __name__ == '__main__':
    Ebook2AudiobookClient().run()
