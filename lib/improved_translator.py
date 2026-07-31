#!/usr/bin/env python3
"""
Improved translation module for ebook2audiobook with better user feedback.
"""

import os
import tempfile
import ebooklib
import logging
import re
import tkinter as tk
from tkinter import messagebox
from ebooklib import epub
from bs4 import BeautifulSoup, Comment, Script, Stylesheet
from deep_translator import GoogleTranslator

# Import custom exceptions
try:
    from .translation_exceptions import TranslationFailedError, RepetitiveContentError
except ImportError:
    # Fallback for when running as a script
    from translation_exceptions import TranslationFailedError, RepetitiveContentError

# Import language codes mapping
try:
    from .language_codes import normalize_language_code, get_language_abbreviations, get_language_name
except ImportError:
    # Fallback function if language_codes.py is not available
    def normalize_language_code(code):
        return code
    
    def get_language_abbreviations(language_name):
        return []

    def get_language_name(abbreviation):
        return None

# Import configuration
try:
    from .conf import DEEPL_API_KEY
except ImportError:
    DEEPL_API_KEY = None

# DeepL translator
try:
    import deepl
    DEEPL_AVAILABLE = True
except ImportError:
    DEEPL_AVAILABLE = False

# DeepL parser wrapper
try:
    from .deepl_wrapper import translate_text_with_deepl_parser
    DEEPL_PARSER_AVAILABLE = True
except ImportError:
    DEEPL_PARSER_AVAILABLE = False

# Argos translator
try:
    import argostranslate.package
    import argostranslate.translate
    ARGOS_AVAILABLE = True
except ImportError:
    ARGOS_AVAILABLE = False

# Free LLM translator (approach ported from the TranslateBooksWithLLMs project):
# any local Ollama or OpenAI-compatible server (llama.cpp, LM Studio, vLLM...)
# reachable through a /v1/chat/completions endpoint. Fully free when local.
try:
    import requests
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False

LLM_API_ENDPOINT = os.environ.get('LLM_API_ENDPOINT', 'http://localhost:11434/v1/chat/completions')
LLM_MODEL = os.environ.get('LLM_MODEL', 'qwen3:14b')
LLM_API_KEY = os.environ.get('LLM_API_KEY', None)

# Language code mappings for different translation services
LANGUAGE_MAPPINGS = {
    'google': {
        'eng': 'en', 'rus': 'ru', 'spa': 'es', 'fra': 'fr', 'deu': 'de',
        'ita': 'it', 'por': 'pt', 'nld': 'nl', 'pol': 'pl', 'ara': 'ar',
        'jpn': 'ja', 'kor': 'ko', 'zho': 'zh', 'tur': 'tr', 'hin': 'hi',
        'ces': 'cs', 'dan': 'da', 'fin': 'fi', 'ell': 'el', 'heb': 'he',
        'hun': 'hu', 'lav': 'lv', 'lit': 'lt', 'nob': 'no', 'ron': 'ro',
        'slk': 'sk', 'slv': 'sl', 'swe': 'sv', 'tha': 'th', 'ukr': 'uk',
        'vie': 'vi', 'bul': 'bg', 'hrv': 'hr', 'srp': 'sr', 'cat': 'ca',
        'est': 'et', 'glg': 'gl', 'msa': 'ms', 'tgl': 'tl', 'ind': 'id'
    },
    'deepl': {
        'eng': 'EN', 'rus': 'RU', 'spa': 'ES', 'fra': 'FR', 'deu': 'DE',
        'ita': 'IT', 'por': 'PT', 'nld': 'NL', 'pol': 'PL', 'ara': 'AR',
        'jpn': 'JA', 'kor': 'KO', 'zho': 'ZH', 'tur': 'TR', 'hin': 'HI',
        'ces': 'CS', 'dan': 'DA', 'fin': 'FI', 'ell': 'EL', 'hun': 'HU',
        'lav': 'LV', 'lit': 'LT', 'nob': 'NB', 'ron': 'RO', 'slk': 'SK',
        'slv': 'SL', 'swe': 'SV', 'ukr': 'UK'
    },
    'argos': {
        'eng': 'en', 'rus': 'ru', 'spa': 'es', 'fra': 'fr', 'deu': 'de',
        'ita': 'it', 'por': 'pt', 'nld': 'nl', 'pol': 'pl', 'ara': 'ar',
        'jpn': 'ja', 'kor': 'ko', 'zho': 'zh', 'tur': 'tr', 'hin': 'hi',
        'ces': 'cs', 'dan': 'da', 'fin': 'fi', 'ell': 'el', 'heb': 'he',
        'hun': 'hu', 'lav': 'lv', 'lit': 'lt', 'nob': 'no', 'ron': 'ro',
        'slk': 'sk', 'slv': 'sl', 'swe': 'sv', 'tha': 'th', 'ukr': 'uk',
        'vie': 'vi', 'bul': 'bg', 'hrv': 'hr', 'srp': 'sr'
    },
    'deepl_parser': {
        'eng': 'en', 'rus': 'ru', 'spa': 'es', 'fra': 'fr', 'deu': 'de',
        'ita': 'it', 'por': 'pt', 'nld': 'nl', 'pol': 'pl', 'ara': 'ar',
        'jpn': 'ja', 'kor': 'ko', 'zho': 'zh', 'tur': 'tr', 'hin': 'hi',
        'ces': 'cs', 'dan': 'da', 'fin': 'fi', 'ell': 'el', 'hun': 'hu',
        'lav': 'lv', 'lit': 'lt', 'nob': 'no', 'ron': 'ro', 'slk': 'sk',
        'slv': 'sl', 'swe': 'sv', 'ukr': 'uk'
    }
}

def map_language_code(lang_code, service):
    """
    Map language code to the format expected by a specific translation service.
    
    Args:
        lang_code (str): Language code (can be full name or abbreviation)
        service (str): Translation service name
    
    Returns:
        str: Language code in the format expected by the service
    """
    # First, try to normalize using our language codes mapping
    normalized_code = normalize_language_code(lang_code)
    
    # If the normalized code is the same as input, it means it wasn't found in our mapping
    # In that case, try to get the primary abbreviation from the language name
    if normalized_code == lang_code:
        abbreviations = get_language_abbreviations(lang_code)
        if abbreviations:
            normalized_code = abbreviations[0]  # Use the first (primary) abbreviation
    
    if service in LANGUAGE_MAPPINGS and normalized_code in LANGUAGE_MAPPINGS[service]:
        return LANGUAGE_MAPPINGS[service][normalized_code]
    return normalized_code

def get_compatible_translation_methods(source_lang, target_lang):
    """
    Return translation methods supporting both the source and the target language.

    Args:
        source_lang (str): Source language code (ISO 639-3, name or abbreviation)
        target_lang (str): Target language code (ISO 639-3, name or abbreviation)

    Returns:
        list: Method names ('google', 'deepl', 'deepl_parser', 'argos', 'llm')
              usable for this language pair; 'google' is kept as a fallback because
              map_language_code() passes unknown codes through to the service;
              'llm' is always offered since an LLM can translate any pair
    """
    def _candidates(lang_code):
        # collect every known form of the code: raw ISO-639-3 key, normalized
        # ISO-639-1 form and the primary abbreviation of a full language name
        candidates = {str(lang_code).lower()}
        normalized = normalize_language_code(lang_code)
        if normalized:
            candidates.add(str(normalized).lower())
        abbreviations = get_language_abbreviations(lang_code)
        if abbreviations:
            candidates.add(str(abbreviations[0]).lower())
        return candidates

    def _supported(candidates, mapping):
        keys = {key.lower() for key in mapping.keys()}
        values = {value.lower() for value in mapping.values()}
        return bool(candidates & (keys | values))

    src = _candidates(source_lang)
    tgt = _candidates(target_lang)
    compatible = [
        service for service, mapping in LANGUAGE_MAPPINGS.items()
        if _supported(src, mapping) and _supported(tgt, mapping)
    ]
    if not compatible:
        compatible = ['google']
    # LLM translation is language-agnostic: always offered as a free local option
    if LLM_AVAILABLE and 'llm' not in compatible:
        compatible.append('llm')
    return compatible

def _llm_language_name(lang_code):
    # LLM prompts work best with plain language names ('russian'), not codes
    name = get_language_name(str(lang_code)) or get_language_name(normalize_language_code(lang_code))
    return (name or str(lang_code)).capitalize()

def _translate_with_llm(text, source_lang, target_lang):
    """
    Translate text with a local/self-hosted LLM through an OpenAI-compatible
    chat completions endpoint (default: Ollama at http://localhost:11434).
    Configure via LLM_API_ENDPOINT, LLM_MODEL and optional LLM_API_KEY env vars.
    Prompt style follows the TranslateBooksWithLLMs project.
    """
    source_name = _llm_language_name(source_lang)
    target_name = _llm_language_name(target_lang)
    system_prompt = (
        f"You are a professional {target_name} translator and writer.\n\n"
        f"Translate {source_name} to {target_name}. Output only the translation, "
        f"without explanations, notes or the original text. Preserve the meaning, "
        f"tone, formatting and proper nouns of the source text."
    )
    headers = {'Content-Type': 'application/json'}
    if LLM_API_KEY:
        headers['Authorization'] = f'Bearer {LLM_API_KEY}'
    payload = {
        'model': LLM_MODEL,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': text}
        ],
        'temperature': 0.3,
        'stream': False
    }
    response = requests.post(LLM_API_ENDPOINT, json=payload, headers=headers, timeout=300)
    response.raise_for_status()
    data = response.json()
    result = data['choices'][0]['message']['content']
    # strip reasoning blocks emitted by thinking models (qwen3, deepseek-r1...)
    result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL).strip()
    if not result:
        raise ValueError('LLM returned an empty translation')
    return result

# Google's direct <source>->Ukrainian output is noticeably weaker than routing
# through Russian first, because Google's ru<->uk pair is very high quality. This
# maps a Google target code to an intermediate (pivot) code so translation runs
# in two steps: source -> pivot -> target. Empty the dict to disable all pivots.
GOOGLE_PIVOT_ROUTES = {
    'uk': 'ru',
}

def _translate_with_google(text, source_lang, target_lang):
    """Translate with GoogleTranslator, optionally pivoting through an intermediate
    language for pairs where two-step translation is clearly better (e.g.
    <source> -> ru -> uk). Raises on failure so callers keep handling SSL/other
    errors exactly as before.
    """
    src = map_language_code(source_lang, 'google')
    tgt = map_language_code(target_lang, 'google')
    pivot = GOOGLE_PIVOT_ROUTES.get(tgt)
    # Skip the pivot when the source already is the pivot or the target, otherwise
    # we'd add a pointless (and lossy) extra hop.
    if pivot and src != pivot and src != tgt:
        intermediate = GoogleTranslator(source=src, target=pivot).translate(text)
        if intermediate:
            logging.info(f"Google pivot translation {src}->{pivot}->{tgt}")
            return GoogleTranslator(source=pivot, target=tgt).translate(intermediate)
    return GoogleTranslator(source=src, target=tgt).translate(text)

# Same idea as GOOGLE_PIVOT_ROUTES but for Argos package codes: translate
# source -> pivot -> target when the direct route gives weaker output for the
# target language. Falls back to the direct pair automatically when the pivot
# chain has no installable packages. Empty the dict to disable all pivots.
ARGOS_PIVOT_ROUTES = {
    'uk': 'ru',
}

# Cache the Argos package index: update_package_index() hits the network and
# translate_text is called once per text chunk, so fetching it every time would
# slow long books down considerably.
_argos_available_packages = None

def _argos_get_available_packages():
    global _argos_available_packages
    if _argos_available_packages is None:
        argostranslate.package.update_package_index()
        _argos_available_packages = argostranslate.package.get_available_packages()
    return _argos_available_packages

def _argos_pair_available(src, tgt):
    """Check (without installing) whether an Argos package exists for the pair."""
    return any(p.from_code == src and p.to_code == tgt for p in _argos_get_available_packages())

def _argos_translate_pair(text, src, tgt):
    """Translate a single language pair with Argos, installing the package on
    demand. Returns the translated text, or None when no package/translation is
    available for the pair (callers decide how to fall back).
    """
    package_to_install = next(
        (p for p in _argos_get_available_packages() if p.from_code == src and p.to_code == tgt),
        None
    )
    if package_to_install is None:
        return None
    installed_packages = argostranslate.package.get_installed_packages()
    if package_to_install not in installed_packages:
        package_to_install.install()
    translation = argostranslate.translate.get_translation_from_codes(src, tgt)
    if translation:
        return translation.translate(text)
    return None

def _translate_with_argos(text, source_lang, target_lang):
    """Translate with Argos, optionally pivoting through an intermediate
    language (e.g. <source> -> ru -> uk), mirroring _translate_with_google.
    Both legs of the pivot are checked for package availability up front so we
    never waste a translation pass on a chain that cannot be completed.
    Returns None when neither the pivot chain nor the direct pair is available;
    raises on unexpected Argos errors.
    """
    src = map_language_code(source_lang, 'argos')
    tgt = map_language_code(target_lang, 'argos')
    pivot = ARGOS_PIVOT_ROUTES.get(tgt)
    if pivot and src != pivot and src != tgt:
        if _argos_pair_available(src, pivot) and _argos_pair_available(pivot, tgt):
            intermediate = _argos_translate_pair(text, src, pivot)
            if intermediate:
                result = _argos_translate_pair(intermediate, pivot, tgt)
                if result:
                    logging.info(f"Argos pivot translation {src}->{pivot}->{tgt}")
                    return result
        else:
            logging.info(f"Argos pivot chain {src}->{pivot}->{tgt} unavailable, using direct {src}->{tgt}")
    return _argos_translate_pair(text, src, tgt)

def translate_text(text, source_lang, target_lang, method='google', parent_window=None):
    """
    Translate text from source language to target language with user feedback.
    
    Args:
        text (str): Text to translate
        source_lang (str): Source language code (ISO 639-3)
        target_lang (str): Target language code (ISO 639-3)
        method (str): Translation method ('google', 'deepl', 'deepl_parser', 'argos' or 'llm')
        parent_window (tk.Tk): Parent window for dialog boxes (optional)

    Returns:
        str: Translated text

    Raises:
        TranslationFailedError: If translation fails and user chooses not to continue
    """
    if method == 'google':
        try:
            return _translate_with_google(text, source_lang, target_lang)
        except Exception as e:
            if "SSL" in str(e) or "ssl" in str(e).lower():
                logging.warning(f"Google Translate SSL error: {e}")
                # Try fallback methods when SSL error occurs
                return _try_fallback_methods(text, source_lang, target_lang, e, parent_window)
            # Handle translation failure with user interaction
            return _handle_translation_failure(text, source_lang, target_lang, str(e), method, parent_window)
    
    elif method == 'deepl':
        if not DEEPL_AVAILABLE:
            error_msg = "DeepL translator not available. Install it first."
            return _handle_translation_failure(text, source_lang, target_lang, error_msg, method, parent_window)
        if not DEEPL_API_KEY:
            error_msg = "DeepL translation requires an API key. Please configure your DeepL API key."
            return _handle_translation_failure(text, source_lang, target_lang, error_msg, method, parent_window)
        
        try:
            deepl_source_lang = map_language_code(source_lang, 'deepl')
            deepl_target_lang = map_language_code(target_lang, 'deepl')
            translator = deepl.Translator(DEEPL_API_KEY)
            result = translator.translate_text(text, source_lang=deepl_source_lang, target_lang=deepl_target_lang)
            return result.text
        except Exception as e:
            return _handle_translation_failure(text, source_lang, target_lang, str(e), method, parent_window)
    
    elif method == 'deepl_parser':
        if not DEEPL_PARSER_AVAILABLE:
            error_msg = "DeepL parser not available."
            return _handle_translation_failure(text, source_lang, target_lang, error_msg, method, parent_window)
        
        try:
            result = translate_text_with_deepl_parser(text, source_lang, target_lang)
            if result.startswith("[Translated with DeepL Parser:") or result.startswith("[Translation failed"):
                logging.warning("DeepL parser translation failed, falling back to Google Translate")
                try:
                    return _translate_with_google(text, source_lang, target_lang)
                except Exception as fallback_error:
                    if "SSL" in str(fallback_error) or "ssl" in str(fallback_error).lower():
                        logging.warning(f"Google Translate fallback SSL error: {fallback_error}")
                        # Try other fallback methods when SSL error occurs
                        return _try_fallback_methods(text, source_lang, target_lang, fallback_error, parent_window)
                    else:
                        logging.error(f"Google Translate fallback also failed: {fallback_error}")
                    if ARGOS_AVAILABLE:
                        try:
                            logging.warning("Trying Argos Translate as second fallback")
                            argos_result = _translate_with_argos(text, source_lang, target_lang)
                            if argos_result:
                                return argos_result
                        except Exception as argos_error:
                            logging.error(f"Argos Translate fallback also failed: {argos_error}")
                    return _handle_translation_failure(text, source_lang, target_lang, str(fallback_error), method, parent_window)
            return result
        except Exception as e:
            return _handle_translation_failure(text, source_lang, target_lang, str(e), method, parent_window)
    
    elif method == 'llm':
        if not LLM_AVAILABLE:
            error_msg = "LLM translator not available. Install the 'requests' package first."
            return _handle_translation_failure(text, source_lang, target_lang, error_msg, method, parent_window)
        try:
            return _translate_with_llm(text, source_lang, target_lang)
        except Exception as e:
            error_msg = (
                f"LLM translation failed ({LLM_MODEL} @ {LLM_API_ENDPOINT}): {e}. "
                f"Make sure a local Ollama/OpenAI-compatible server is running "
                f"or set LLM_API_ENDPOINT/LLM_MODEL/LLM_API_KEY environment variables."
            )
            return _handle_translation_failure(text, source_lang, target_lang, error_msg, method, parent_window)

    elif method == 'argos':
        if not ARGOS_AVAILABLE:
            error_msg = "ArgosTranslate not available. Install it first."
            return _handle_translation_failure(text, source_lang, target_lang, error_msg, method, parent_window)
        
        try:
            result = _translate_with_argos(text, source_lang, target_lang)
            if result:
                return result
            src_lang = map_language_code(source_lang, 'argos')
            tgt_lang = map_language_code(target_lang, 'argos')
            error_msg = f"No ArgosTranslate package available for {src_lang} -> {tgt_lang}"
            return _handle_translation_failure(text, source_lang, target_lang, error_msg, method, parent_window)
        except Exception as e:
            return _handle_translation_failure(text, source_lang, target_lang, str(e), method, parent_window)
    
    else:
        error_msg = f"Unknown translation method: {method}"
        return _handle_translation_failure(text, source_lang, target_lang, error_msg, method, parent_window)

def _try_fallback_methods(text, source_lang, target_lang, original_error, parent_window=None):
    """
    Try fallback translation methods when Google Translate fails with SSL error.
    
    Args:
        text (str): Text to translate
        source_lang (str): Source language code
        target_lang (str): Target language code
        original_error (Exception): The original SSL error
        parent_window (tk.Tk): Parent window for dialog boxes (optional)
        
    Returns:
        str: Translated text or error message
    """
    logging.warning("Attempting fallback translation methods due to SSL error")
    
    # Try DeepL Parser first if available
    if DEEPL_PARSER_AVAILABLE:
        try:
            logging.info("Trying DeepL Parser as fallback")
            result = translate_text_with_deepl_parser(text, source_lang, target_lang)
            if not (result.startswith("[Translated with DeepL Parser:") or result.startswith("[Translation failed")):
                return result
            else:
                logging.warning("DeepL Parser failed or returned error message")
        except Exception as e:
            logging.warning(f"DeepL Parser fallback failed: {e}")
    
    # Try Argos Translate if available
    if ARGOS_AVAILABLE:
        try:
            logging.info("Trying Argos Translate as fallback")
            argos_result = _translate_with_argos(text, source_lang, target_lang)
            if argos_result:
                return argos_result
        except Exception as e:
            logging.warning(f"Argos Translate fallback failed: {e}")
    
    # If all fallbacks fail, return original text with error message
    logging.error(f"All fallback translation methods failed. Original SSL error: {original_error}")
    return text

def _handle_translation_failure(text, source_lang, target_lang, error_msg, method, parent_window=None):
    """
    Handle translation failure with user interaction.
    
    Args:
        text (str): Original text that failed to translate
        source_lang (str): Source language code
        target_lang (str): Target language code
        error_msg (str): Error message
        method (str): Translation method used
        parent_window (tk.Tk): Parent window for dialog boxes (optional)
        
    Returns:
        str: Either translated text (if user chooses to continue) or raises TranslationFailedError
        
    Raises:
        TranslationFailedError: If user chooses not to continue
    """
    logging.error(f"Translation failed: {error_msg}")
    
    # If we're in a GUI context, show a dialog to the user
    if parent_window:
        import tkinter.messagebox as messagebox
        
        # Create a custom dialog with options
        dialog_result = messagebox.askyesnocancel(
            "Translation Failed",
            f"Translation failed using {method}: {error_msg}\n\n"
            f"Original text: {text[:100]}{'...' if len(text) > 100 else ''}\n\n"
            "Do you want to:\n"
            "- Yes: Continue with another translation method\n"
            "- No: Skip this text and continue\n"
            "- Cancel: Stop the entire translation process",
            parent=parent_window
        )
        
        if dialog_result is True:  # User chose to continue with another method
            # Try alternative methods
            alternative_methods = [m for m in ['google', 'deepl', 'deepl_parser', 'argos', 'llm'] if m != method]
            
            for alt_method in alternative_methods:
                try:
                    logging.info(f"Trying alternative translation method: {alt_method}")
                    return translate_text(text, source_lang, target_lang, alt_method, parent_window)
                except Exception as alt_error:
                    logging.warning(f"Alternative method {alt_method} also failed: {alt_error}")
                    continue
            
            # If all alternatives fail, fall back to original text
            messagebox.showwarning(
                "All Methods Failed", 
                "All translation methods failed. Using original text.",
                parent=parent_window
            )
            return text
            
        elif dialog_result is False:  # User chose to skip this text
            return text
            
        else:  # User cancelled the entire process
            raise TranslationFailedError(
                f"Translation cancelled by user. Last error: {error_msg}",
                original_text=text,
                source_lang=source_lang,
                target_lang=target_lang
            )
    else:
        # Not in GUI context, just log and return error message
        return text

def _detect_repetitive_content(content, threshold=20):
    """
    Detect repetitive content in translated text.
    
    Args:
        content (str): Content to check for repetitions
        threshold (int): Minimum number of repetitions to consider problematic
        
    Returns:
        tuple: (bool, str, int) - (is_repetitive, repeated_content, count)
    """
    # Split content into sentences or phrases
    sentences = re.split(r'[.!?]+|\n+', content)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    # Filter out very short sentences (likely single words)
    sentences = [s for s in sentences if len(s) > 15]
    
    # Count occurrences of each sentence
    sentence_counts = {}
    for sentence in sentences:
        # Normalize whitespace
        normalized = re.sub(r'\s+', ' ', sentence).strip()
        sentence_counts[normalized] = sentence_counts.get(normalized, 0) + 1
    
    # Check for sentences that appear more than threshold times
    for sentence, count in sentence_counts.items():
        if count >= threshold and len(sentence) > 20:  # Only consider longer sentences
            return True, sentence, count
    
    # Also check for repeated short words/phrases that might be problematic
    words = re.findall(r'\b\w+\b', content)
    word_counts = {}
    for word in words:
        if len(word) > 5:  # Only consider longer words
            word_counts[word] = word_counts.get(word, 0) + 1
    
    for word, count in word_counts.items():
        # Increase the threshold significantly for single words to avoid false positives
        # In a book about healthcare/data science, words like "data" or "health" will appear frequently
        if count >= threshold * 5:  # Much higher threshold for single words
            return True, word, count
    
    return False, "", 0

def translate_ebook_content(content, source_lang, target_lang, method='google', translation_manager=None, chapter_index=None, parent_window=None):
    """
    Translate ebook content, handling large texts by chunking.
    
    Args:
        content (str): Ebook content to translate
        source_lang (str): Source language code
        target_lang (str): Target language code
        method (str): Translation method
        translation_manager (TranslationManager): Optional manager for caching translations
        chapter_index (int): Optional chapter index for caching
        parent_window (tk.Tk): Parent window for dialog boxes (optional)
        
    Returns:
        str: Translated content
    """
    if translation_manager and chapter_index is not None:
        cached_translation = translation_manager.get_translated_chapter(chapter_index)
        if cached_translation:
            logging.info(f"Using cached translation for chapter {chapter_index}")
            return cached_translation

    max_chunk_size = 5000  # Characters

    if len(content) <= max_chunk_size:
        try:
            result = translate_text(content, source_lang, target_lang, method, parent_window)
            # Translators may return None for junk input (OCR artifacts, dot
            # leaders, page numbers) - keep the original text in that case.
            if not result:
                logging.warning("Translator returned no result; keeping original text")
                result = content
            # Check for repetitive content with a higher threshold to reduce false positives
            # Use a higher threshold (20) for normal content checking
            is_repetitive, repeated_content, count = _detect_repetitive_content(result, threshold=20)
            if is_repetitive:
                logging.warning(f"Repetitive content detected: '{repeated_content}' appears {count} times")
                if parent_window:
                    import tkinter.messagebox as messagebox
                    messagebox.showwarning(
                        "Repetitive Content Detected",
                        f"Repetitive content detected in translation:\n"
                        f"'{repeated_content}' appears {count} times.\n"
                        f"This may affect the quality of the audiobook.",
                        parent=parent_window
                    )
            
            if translation_manager and chapter_index is not None:
                translation_manager.save_translated_chapter(chapter_index, content, result)
            return result
        except TranslationFailedError:
            raise
        except Exception as e:
            logging.warning(f"Translation failed: {e}")
            # Keep the raw original text: any marker prepended here would be
            # read aloud in the audiobook.
            error_result = content
            if translation_manager and chapter_index is not None:
                translation_manager.save_translated_chapter(chapter_index, content, error_result)
            return error_result
    else:
        paragraphs = content.split('\n\n')
        translated_paragraphs = []
        for paragraph in paragraphs:
            if paragraph.strip():
                try:
                    translated = translate_text(paragraph, source_lang, target_lang, method, parent_window)
                    if not translated:
                        logging.warning("Translator returned no result for a paragraph; keeping original text")
                        translated = paragraph
                    # Check for repetitive content with a higher threshold to reduce false positives
                    # Use a higher threshold (20) for normal content checking
                    is_repetitive, repeated_content, count = _detect_repetitive_content(translated, threshold=20)
                    if is_repetitive:
                        logging.warning(f"Repetitive content detected: '{repeated_content}' appears {count} times")
                        if parent_window:
                            import tkinter.messagebox as messagebox
                            messagebox.showwarning(
                                "Repetitive Content Detected",
                                f"Repetitive content detected in translation:\n"
                                f"'{repeated_content}' appears {count} times.\n"
                                f"This may affect the quality of the audiobook.",
                                parent=parent_window
                            )
                    
                    translated_paragraphs.append(translated)
                except TranslationFailedError:
                    raise
                except Exception as e:
                    logging.warning(f"Translation failed for paragraph: {e}")
                    translated_paragraphs.append(paragraph)
            else:
                translated_paragraphs.append(paragraph)
        result = '\n\n'.join(translated_paragraphs)
        if translation_manager and chapter_index is not None:
            translation_manager.save_translated_chapter(chapter_index, content, result)
        return result

def check_translation_method(method, source_lang, target_lang, sample_text="Hello, world."):
    """Probe a single translation method with a tiny sample and report its status.

    Unlike translate_text(), this never shows dialogs and never falls back to another
    method: it reports exactly why THIS method does or does not work for the given
    language pair, so the caller can tell the user which method is broken and why.

    Returns:
        tuple: (ok: bool, detail: str)
    """
    try:
        if method == 'google':
            src = map_language_code(source_lang, 'google')
            tgt = map_language_code(target_lang, 'google')
            result = GoogleTranslator(source=src, target=tgt).translate(sample_text)
            if not result or not result.strip():
                return False, "Google returned an empty result"
            return True, f"{src}->{tgt}"

        elif method == 'deepl':
            if not DEEPL_AVAILABLE:
                return False, "the 'deepl' package is not installed"
            if not DEEPL_API_KEY:
                return False, "no DeepL API key configured (set DEEPL_API_KEY in conf)"
            src = map_language_code(source_lang, 'deepl')
            tgt = map_language_code(target_lang, 'deepl')
            deepl.Translator(DEEPL_API_KEY).translate_text(sample_text, source_lang=src, target_lang=tgt)
            return True, f"{src}->{tgt}"

        elif method == 'deepl_parser':
            if not DEEPL_PARSER_AVAILABLE:
                return False, "the DeepL parser wrapper is not available"
            result = translate_text_with_deepl_parser(sample_text, source_lang, target_lang)
            if result.startswith("[Translated with DeepL Parser:") or result.startswith("[Translation failed"):
                return False, "DeepL parser could not translate the sample"
            return True, "ok"

        elif method == 'argos':
            if not ARGOS_AVAILABLE:
                return False, "the 'argostranslate' package is not installed"
            src = map_language_code(source_lang, 'argos')
            tgt = map_language_code(target_lang, 'argos')
            argostranslate.package.update_package_index()
            available_packages = argostranslate.package.get_available_packages()
            package_to_install = next((p for p in available_packages if p.from_code == src and p.to_code == tgt), None)
            if not package_to_install:
                return False, f"no Argos language package for {src}->{tgt}"
            installed = argostranslate.package.get_installed_packages()
            if package_to_install not in installed:
                return True, f"package available for {src}->{tgt} (downloads on first use)"
            translation = argostranslate.translate.get_translation_from_codes(src, tgt)
            if not translation:
                return False, f"Argos package installed but no translation for {src}->{tgt}"
            return True, f"{src}->{tgt}"

        elif method == 'llm':
            if not LLM_AVAILABLE:
                return False, "the 'requests' package is not installed"
            result = _translate_with_llm(sample_text, source_lang, target_lang)
            if not result or not result.strip():
                return False, f"LLM at {LLM_API_ENDPOINT} returned an empty result"
            return True, f"{LLM_MODEL} @ {LLM_API_ENDPOINT}"

        else:
            return False, f"unknown translation method '{method}'"
    except Exception as e:
        msg = str(e)
        if "SSL" in msg or "ssl" in msg.lower():
            return False, f"network/SSL error (no internet?): {e}"
        return False, f"{type(e).__name__}: {e}"

def diagnose_translation_methods(source_lang, target_lang, methods=None, selected_method=None):
    """Probe every candidate translation method and log a readable status report.

    Used as a preflight before translating a whole file so the log clearly shows which
    methods work for this language pair and which are broken (and why), instead of
    silently falling back to the original text.

    Returns:
        dict: {method: (ok: bool, detail: str)}
    """
    if methods is None:
        methods = get_compatible_translation_methods(source_lang, target_lang)
    results = {}
    lines = [f"Translation preflight ({source_lang} -> {target_lang}):"]
    for m in methods:
        ok, detail = check_translation_method(m, source_lang, target_lang)
        results[m] = (ok, detail)
        lines.append(f"  {m:<13}: {'OK' if ok else 'FAIL'} - {detail}")
    logging.info("\n".join(lines))

    if selected_method is not None:
        if selected_method not in results:
            results[selected_method] = check_translation_method(selected_method, source_lang, target_lang)
        ok, detail = results[selected_method]
        if ok:
            logging.info(f"Selected translation method '{selected_method}' is working ({detail}).")
        else:
            working = [m for m, (o, _) in results.items() if o and m != selected_method]
            logging.error(
                f"Selected translation method '{selected_method}' is NOT working: {detail}. "
                f"Without a working method the audiobook is voiced from the ORIGINAL (untranslated) text. "
                f"Working alternatives: {working or 'none'}"
            )
    return results

def translate_ebook_file(ebook_path, source_lang, target_lang, method='google', output_path=None, session_dir=None, parent_window=None):
    """
    Translate an ebook file from source language to target language with user feedback.
    
    Args:
        ebook_path (str): Path to the ebook file
        source_lang (str): Source language code (ISO 639-3)
        target_lang (str): Target language code (ISO 639-3)
        method (str): Translation method ('google', 'deepl', 'deepl_parser', or 'argos')
        output_path (str): Path for the translated ebook (optional)
        session_dir (str): Session directory for caching translations (optional)
        parent_window (tk.Tk): Parent window for dialog boxes (optional)
        
    Returns:
        str: Path to the translated ebook file
        
    Raises:
        TranslationFailedError: If translation fails and user chooses not to continue
    """
    translation_manager = None
    if session_dir:
        try:
            try:
                from .translation_manager import TranslationManager
            except ImportError:
                # Fallback for when running as a script
                from translation_manager import TranslationManager
            translation_manager = TranslationManager(session_dir, source_lang, target_lang, method)
        except Exception as e:
            logging.warning(f"Failed to initialize translation manager: {e}")

    # Preflight: probe every compatible method (and flag the selected one) so the log
    # tells us exactly which methods work and why the others don't, before we translate
    # the whole file and risk silently falling back to the original text.
    # If the selected method is broken (e.g. 'deepl' without the package/API key on
    # Colab) but another method works, switch to it instead of voicing the original.
    try:
        results = diagnose_translation_methods(source_lang, target_lang, selected_method=method)
        ok, _ = results.get(method, (False, ''))
        if not ok:
            for alt in ('google', 'deepl_parser', 'argos'):
                if alt != method and results.get(alt, (False, ''))[0]:
                    logging.warning(
                        f"Automatically falling back from broken translation method "
                        f"'{method}' to working method '{alt}'.")
                    method = alt
                    break
    except Exception as e:
        logging.warning(f"Translation preflight check could not run: {e}")

    file_ext = os.path.splitext(ebook_path)[1].lower()
    if file_ext == '.epub':
        return _translate_epub_file(ebook_path, source_lang, target_lang, method, output_path, translation_manager, parent_window)
    elif file_ext == '.pdf':
        return _translate_pdf_file(ebook_path, source_lang, target_lang, method, output_path, parent_window)
    elif file_ext in ['.txt', '.md']:
        return _translate_text_file(ebook_path, source_lang, target_lang, method, output_path, translation_manager, parent_window)
    else:
        raise Exception(f"Translation not supported for format: {file_ext}")

def _translate_epub_file(ebook_path, source_lang, target_lang, method, output_path, translation_manager=None, parent_window=None):
    """Translate an EPUB file with user feedback."""
    logging.info(f"Starting translation of {ebook_path}")
    book = epub.read_epub(ebook_path)
    if translation_manager:
        document_items = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT]
        translation_manager.set_total_chapters(len(document_items))

    # Translate metadata
    metadata = book.get_metadata('DC', 'title')
    if metadata:
        title = metadata[0][0]
        try:
            translated_title = translate_text(title, source_lang, target_lang, method, parent_window)
            book.set_title(translated_title)
        except TranslationFailedError:
            raise
        except Exception as e:
            logging.warning(f"Failed to translate title: {e}")
            book.set_title(f"[Translation failed] {title}")

    metadata = book.get_metadata('DC', 'creator')
    if metadata:
        creator = metadata[0][0]
        try:
            translated_creator = translate_text(creator, source_lang, target_lang, method, parent_window)
            book.add_author(translated_creator)
        except TranslationFailedError:
            raise
        except Exception as e:
            logging.warning(f"Failed to translate creator: {e}")
            book.add_author(f"[Translation failed] {creator}")

    # Translate content
    document_items = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT]
    for i, item in enumerate(document_items):
        content = item.get_content().decode('utf-8')
        content = re.sub(r'<\?xml[^>]*>', '', content, flags=re.IGNORECASE)
        soup = BeautifulSoup(content, 'html.parser')
        cached_translation = None
        if translation_manager:
            cached_translation = translation_manager.get_translated_chapter(i)

        if cached_translation:
            logging.info(f"Using cached translation for document {i}")
            item.set_content(cached_translation.encode('utf-8'))
        else:
            # Collect all text nodes that need translation
            text_nodes_to_translate = []
            for tag in soup.find_all(string=True):  # Use string=True instead of text=True
                # Skip empty text
                if not tag.strip():
                    continue
                    
                # Skip comments
                if isinstance(tag, Comment):
                    continue
                    
                # Skip processing instructions and doctypes
                if isinstance(tag, (Comment, Script, Stylesheet)) or type(tag).__name__ in ['ProcessingInstruction', 'Doctype']:
                    continue
                    
                # Skip script and style content
                parent = tag.parent
                if parent and parent.name in ['script', 'style']:
                    continue
                    
                # Skip certain tags that might contain non-content text
                if parent and parent.name in ['meta', 'link', 'img', 'input', 'option']:
                    continue
                
                # Store the tag and its text content for translation
                if hasattr(tag, 'string') and tag.string:
                    text_content = tag.string
                else:
                    # For NavigableString objects, get the string value directly
                    text_content = str(tag) if not isinstance(tag, (Comment, Script, Stylesheet)) else ""

                # Only add non-empty text content that looks like actual text
                if text_content.strip() and len(text_content.strip()) > 1:
                    # Simplified check - translate most content that looks like readable text
                    # Skip if it looks like HTML/XML tags or attributes
                    stripped_content = text_content.strip()
                    if not (stripped_content.startswith('<') and stripped_content.endswith('>')):
                        if not (stripped_content.startswith('"') and stripped_content.endswith('"')):
                            text_nodes_to_translate.append((tag, stripped_content))
                            
            # Log how many text nodes we found to translate
            logging.info(f"Found {len(text_nodes_to_translate)} text nodes to translate in document {i}")
            
            # Log first few text nodes for debugging
            for j, (tag, content) in enumerate(text_nodes_to_translate[:3]):
                logging.debug(f"Text node {j}: '{content[:50]}{'...' if len(content) > 50 else ''}'")
            
            # Translate all text nodes
            translated_content_pairs = []
            
            for tag, text_content in text_nodes_to_translate:
                try:
                    # More permissive translation filter - translate most content
                    # Only skip content that is clearly not translatable
                    if text_content.strip():
                        # Log what we're about to translate
                        logging.debug(f"Translating text: '{text_content[:50]}{'...' if len(text_content) > 50 else ''}'")
                        
                        # Translate the text content without using chapter index for caching individual text nodes
                        # The chapter index is only used for caching the entire chapter translation
                        translated = translate_ebook_content(text_content, source_lang, target_lang, method, None, None, parent_window)
                        
                        # Log the translation result
                        logging.debug(f"Translation result: '{translated[:50]}{'...' if len(translated) > 50 else ''}'")
                        
                        translated_content_pairs.append((tag, translated))
                    else:
                        # Keep the original content if it doesn't look like translatable text
                        translated_content_pairs.append((tag, text_content))
                except TranslationFailedError:
                    raise
                except Exception as e:
                    logging.warning(f"Failed to translate content: {e}")
                    translated_content_pairs.append((tag, f"[Translation failed] {text_content}"))

            # Replace text nodes one by one, being careful not to interfere with iteration
            # We'll collect all replacements first, then apply them
            replacements_to_make = []
            for original_tag, translated_text in translated_content_pairs:
                replacements_to_make.append((original_tag, translated_text))
            
            # Log how many replacements we're about to make
            logging.info(f"Making {len(replacements_to_make)} replacements in document {i}")
            
            # Apply replacements in reverse order to avoid index issues
            for original_tag, translated_text in reversed(replacements_to_make):
                try:
                    # Log the replacement
                    original_text = str(original_tag)[:50] + "..." if len(str(original_tag)) > 50 else str(original_tag)
                    translated_preview = translated_text[:50] + "..." if len(translated_text) > 50 else translated_text
                    logging.debug(f"Replacing '{original_text}' with '{translated_preview}'")
                    
                    # More robust replacement that preserves the original tag structure
                    if hasattr(original_tag, 'string') and original_tag.string:
                        original_tag.string.replace_with(translated_text)
                    else:
                        original_tag.replace_with(translated_text)
                except Exception as e:
                    logging.warning(f"Failed to replace tag: {e}")

            translated_html = str(soup)
            
            # Check for repetitive content in the entire HTML with a higher threshold
            # This is a simplified check - in practice, you might want to check specific sections
            # Use a higher threshold (25) for HTML content checking to avoid false positives
            is_repetitive, repeated_content, count = _detect_repetitive_content(translated_html, threshold=25)
            if is_repetitive:
                logging.warning(f"Repetitive content detected in chapter {i}: '{repeated_content}' appears {count} times")
                if parent_window:
                    import tkinter.messagebox as messagebox
                    messagebox.showwarning(
                        "Repetitive Content Detected",
                        f"Repetitive content detected in chapter {i}:\n"
                        f"'{repeated_content}' appears {count} times.\n"
                        f"This may affect the quality of the audiobook.",
                        parent=parent_window
                    )
            
            if translation_manager:
                translation_manager.save_translated_chapter(i, content, translated_html)
            item.set_content(translated_html.encode('utf-8'))

    # Save the translated EPUB
    if not output_path:
        filename = os.path.splitext(os.path.basename(ebook_path))[0]
        output_path = os.path.join(os.path.dirname(ebook_path), f"{filename}_translated.epub")

    epub.write_epub(output_path, book)
    return output_path

def _read_text_file_any_encoding(path):
    """Read a text file as a str regardless of its original encoding.

    Users often provide .txt/.md sources in legacy encodings (e.g. cp1251 for
    Cyrillic). Reading them as strict UTF-8 raises UnicodeDecodeError and aborts
    translation, so detect the encoding and decode to a normal str (the rest of
    the pipeline then writes UTF-8). A UTF-8 BOM is stripped automatically; when
    a detector is unavailable we try a short list of common encodings before a
    final lossy decode so translation never hard-fails on encoding alone.
    """
    with open(path, 'rb') as f:
        raw = f.read()
    if not raw:
        return ''
    # UTF-8 with BOM -> decode and drop the BOM
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw.decode('utf-8-sig')
    # UTF-8 is self-validating: if the bytes decode cleanly it is almost certainly
    # UTF-8, so try it before any detector to keep the common case deterministic
    # and immune to detector misfires on short/ambiguous input.
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        pass
    # Prefer a real detector when available (charset_normalizer ships with requests)
    for detector in ('charset_normalizer', 'chardet'):
        try:
            mod = __import__(detector)
        except Exception:
            continue
        try:
            if detector == 'charset_normalizer':
                best = mod.from_bytes(raw).best()
                enc = best.encoding if best else None
            else:
                enc = mod.detect(raw).get('encoding')
            if enc:
                try:
                    text = raw.decode(enc)
                    logging.info(f"Decoded input '{os.path.basename(path)}' as {enc} (auto-detected)")
                    return text
                except (LookupError, UnicodeDecodeError):
                    pass
        except Exception:
            pass
    # No detector or detection failed: try common single-byte encodings (UTF-8 was
    # already ruled out above), then a final lossy decode so we never hard-fail.
    for enc in ('cp1251', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    logging.warning(f"Could not determine encoding of '{os.path.basename(path)}'; decoding as UTF-8 with replacement")
    return raw.decode('utf-8', errors='replace')

def _translate_text_file(ebook_path, source_lang, target_lang, method, output_path, translation_manager=None, parent_window=None):
    """Translate a text file with user feedback."""
    content = _read_text_file_any_encoding(ebook_path)

    cached_translation = None
    if translation_manager:
        cached_translation = translation_manager.get_translated_chapter(0)

    if cached_translation:
        logging.info("Using cached translation for text file")
        translated_content = cached_translation
    else:
        try:
            translated_content = translate_ebook_content(content, source_lang, target_lang, method, translation_manager, 0, parent_window)
        except TranslationFailedError:
            raise
        except Exception as e:
            logging.error(f"Translation failed: {e}")
            translated_content = content

    if not output_path:
        filename = os.path.splitext(os.path.basename(ebook_path))[0]
        output_path = os.path.join(os.path.dirname(ebook_path), f"{filename}_translated{os.path.splitext(ebook_path)[1]}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(translated_content)

    return output_path

def _translate_pdf_file(ebook_path, source_lang, target_lang, method, output_path, parent_window=None):
    """Translate a PDF file by flattening it to Markdown, then translating the text.

    convert2epub already turns PDFs into Markdown (via pymupdf4llm) before chaptering,
    so we do the same here and translate the resulting Markdown. The output is a .md
    file, which the conversion pipeline supports directly (no PDF re-generation needed).
    """
    logging.info(f"Starting translation of PDF {ebook_path}")
    try:
        import pymupdf4llm
    except Exception as e:
        raise Exception(f"PDF translation requires the 'pymupdf4llm' package: {e}")

    # Flatten the PDF to Markdown, mirroring convert2epub's PDF handling
    markdown_text = pymupdf4llm.to_markdown(ebook_path)
    # Remove single asterisks/underscores used for italics (keep bold ** and __)
    markdown_text = re.sub(r'(?<!\*)\*(?!\*)(.*?)\*(?!\*)', r'\1', markdown_text)
    markdown_text = re.sub(r'(?<!_)_(?!_)(.*?)_(?!_)', r'\1', markdown_text)

    try:
        translated_content = translate_ebook_content(markdown_text, source_lang, target_lang, method, None, None, parent_window)
    except TranslationFailedError:
        raise
    except Exception as e:
        logging.error(f"PDF translation failed: {e}")
        translated_content = markdown_text

    if not output_path:
        filename = os.path.splitext(os.path.basename(ebook_path))[0]
        output_path = os.path.join(os.path.dirname(ebook_path), f"{filename}_translated.md")
    # Force a .md extension so convert2epub treats the output as Markdown, not as a PDF
    if os.path.splitext(output_path)[1].lower() != '.md':
        output_path = os.path.splitext(output_path)[0] + '.md'

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(translated_content)

    return output_path

if __name__ == "__main__":
    text = "This is a sample text to translate."
    try:
        translated = translate_text(text, "eng", "rus", "google")
        print(f"Translated text: {translated}")
    except Exception as e:
        print(f"Translation error: {e}")
