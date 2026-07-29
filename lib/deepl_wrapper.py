"""
DeepL wrapper for ebook2audiobook
Provides integration with the DeepL parser functionality
"""

import os
import sys
import tempfile
import subprocess
import time
import logging

# Add the DeepL parser directory to the path
DEEPL_PARSER_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'DeeplParser-main')

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
    'deepl_parser': {
        'eng': 'en', 'rus': 'ru', 'spa': 'es', 'fra': 'fr', 'deu': 'de',
        'ita': 'it', 'por': 'pt', 'nld': 'nl', 'pol': 'pl', 'ara': 'ar',
        'jpn': 'ja', 'kor': 'ko', 'zho': 'zh', 'tur': 'tr', 'hin': 'hi',
        'ces': 'cs', 'dan': 'da', 'fin': 'fi', 'ell': 'el', 'hun': 'hu',
        'lav': 'lv', 'lit': 'lt', 'nob': 'no', 'ron': 'ro', 'slk': 'sk',
        'slv': 'sl', 'swe': 'sv'
    }
}

def map_language_code(lang_code, service):
    """
    Map language code to the format expected by a specific translation service
    
    Args:
        lang_code (str): ISO 639-3 language code
        service (str): Translation service name
        
    Returns:
        str: Language code in the format expected by the service
    """
    if service in LANGUAGE_MAPPINGS and lang_code in LANGUAGE_MAPPINGS[service]:
        return LANGUAGE_MAPPINGS[service][lang_code]
    # If no mapping is found, return the original code
    return lang_code

def translate_text_with_deepl_parser(text, source_lang, target_lang):
    """
    Translate text using the DeepL parser implementation
    
    Args:
        text (str): Text to translate
        source_lang (str): Source language code
        target_lang (str): Target language code
    
    Returns:
        str: Translated text
    """
    try:
        # Try to use the new DeepL parser implementation
        from .deepl_parser import translate_text_simple
        result = translate_text_simple(text, source_lang, target_lang)
        
        # Check if the result is the simulation text (indicating failure)
        if result.startswith("[Translated with DeepL Parser:"):
            # Fall back to a more reliable translation method
            return _fallback_translation(text, source_lang, target_lang)
            
        return result
    except ImportError:
        # Fall back to the old method if the new parser is not available
        pass
    except Exception as e:
        # If there's any error with the DeepL parser, fall back
        logging.warning(f"DeepL parser failed: {e}")
        return _fallback_translation(text, source_lang, target_lang)
    
    # Fallback method using the existing parser directory
    if not os.path.exists(DEEPL_PARSER_PATH):
        # If DeepL parser doesn't exist, use fallback translation
        return _fallback_translation(text, source_lang, target_lang)
    
    # Create temporary files for input and output
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as input_file:
        input_file.write(text)
        input_file_path = input_file.name
    
    output_file_path = input_file_path.replace('.txt', '_translated.txt')
    original_cwd = os.getcwd()  # Initialize before try block
    
    try:
        # Change to the DeepL parser directory
        os.chdir(DEEPL_PARSER_PATH)
        
        # Copy input file to the expected location
        import shutil
        shutil.copy(input_file_path, 'input.txt')
        
        # Check if main.py exists
        if not os.path.exists('main.py'):
            # Use the simulation if main.py doesn't exist
            result = _simulate_deepl_translation(text, source_lang, target_lang)
        else:
            # Try to run the actual DeepL parser
            try:
                # Run the DeepL parser
                subprocess.run([sys.executable, 'main.py'], check=True, capture_output=True, text=True)
                
                # Read the output
                if os.path.exists('output.txt'):
                    with open('output.txt', 'r', encoding='utf-8') as f:
                        result = f.read()
                else:
                    # Fall back to simulation if no output was produced
                    result = _fallback_translation(text, source_lang, target_lang)
            except subprocess.CalledProcessError:
                # Fall back to simulation if the parser fails
                result = _fallback_translation(text, source_lang, target_lang)
        
        # Check if the result is the simulation text (indicating failure)
        if result.startswith("[Translated with DeepL Parser:"):
            result = _fallback_translation(text, source_lang, target_lang)
            
        return result
        
    except Exception as e:
        raise Exception(f"DeepL parser translation failed: {str(e)}")
    finally:
        # Clean up temporary files
        os.chdir(original_cwd)
        try:
            os.unlink(input_file_path)
        except:
            pass
        try:
            if os.path.exists(os.path.join(DEEPL_PARSER_PATH, 'input.txt')):
                os.unlink(os.path.join(DEEPL_PARSER_PATH, 'input.txt'))
        except:
            pass
        try:
            if os.path.exists(os.path.join(DEEPL_PARSER_PATH, 'output.txt')):
                os.unlink(os.path.join(DEEPL_PARSER_PATH, 'output.txt'))
        except:
            pass

def _fallback_translation(text, source_lang, target_lang):
    """
    Fallback translation using more reliable methods
    """
    try:
        # Try to use deep_translator (Google Translate) as a fallback
        from deep_translator import GoogleTranslator
        
        # Map language codes to Google Translate format
        src_lang = map_language_code(source_lang, 'google')
        tgt_lang = map_language_code(target_lang, 'google')
        
        translator = GoogleTranslator(source=src_lang, target=tgt_lang)
        result = translator.translate(text)
        
        if result:
            return result
    except Exception as e:
        logging.warning(f"Google Translate fallback failed: {e}")
    
    # If all else fails, return the original text with a warning
    return f"[Translation failed - using original text] {text}"

def _simulate_deepl_translation(text, source_lang, target_lang):
    """
    Simulate DeepL translation (for testing purposes)
    In a real implementation, this would call the actual DeepL parser
    """
    # This is a simple simulation - in reality, you would call the DeepL parser
    return f"[Translated with DeepL Parser: {source_lang}->{target_lang}] {text}"

# Example usage
if __name__ == "__main__":
    # Test the DeepL wrapper
    try:
        text = "Hello, this is a test."
        translated = translate_text_with_deepl_parser(text, "eng", "rus")
        print(f"Original: {text}")
        print(f"Translated: {translated}")
    except Exception as e:
        print(f"Error: {e}")