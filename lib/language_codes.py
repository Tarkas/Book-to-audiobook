#!/usr/bin/env python3
"""
Language codes mapping for ebook2audiobook
Provides comprehensive mapping of language names to their abbreviations in various formats.
"""

# Language mapping: {language_name: [abbreviations]}
LANGUAGE_CODES = {
    # Russian
    "русский": ["ru", "rus"],
    "russian": ["ru", "rus"],
    
    # English
    "english": ["en", "eng"],
    "английский": ["en", "eng"],
    
    # Spanish
    "spanish": ["es", "spa"],
    "español": ["es", "spa"],
    "испанский": ["es", "spa"],
    
    # French
    "french": ["fr", "fra"],
    "français": ["fr", "fra"],
    "французский": ["fr", "fra"],
    
    # German
    "german": ["de", "deu"],
    "deutsch": ["de", "deu"],
    "немецкий": ["de", "deu"],
    
    # Italian
    "italian": ["it", "ita"],
    "italiano": ["it", "ita"],
    "итальянский": ["it", "ita"],
    
    # Portuguese
    "portuguese": ["pt", "por"],
    "português": ["pt", "por"],
    "португальский": ["pt", "por"],
    
    # Dutch
    "dutch": ["nl", "nld"],
    "nederlands": ["nl", "nld"],
    "нидерландский": ["nl", "nld"],
    
    # Polish
    "polish": ["pl", "pol"],
    "polski": ["pl", "pol"],
    "польский": ["pl", "pol"],
    
    # Arabic
    "arabic": ["ar", "ara"],
    "العربية": ["ar", "ara"],
    "арабский": ["ar", "ara"],
    
    # Japanese
    "japanese": ["ja", "jpn"],
    "日本語": ["ja", "jpn"],
    "японский": ["ja", "jpn"],
    
    # Korean
    "korean": ["ko", "kor"],
    "한국어": ["ko", "kor"],
    "корейский": ["ko", "kor"],
    
    # Chinese
    "chinese": ["zh", "zho"],
    "中文": ["zh", "zho"],
    "китайский": ["zh", "zho"],
    
    # Turkish
    "turkish": ["tr", "tur"],
    "türkçe": ["tr", "tur"],
    "турецкий": ["tr", "tur"],
    
    # Hindi
    "hindi": ["hi", "hin"],
    "हिन्दी": ["hi", "hin"],
    "хинди": ["hi", "hin"],
    
    # Czech
    "czech": ["cs", "ces"],
    "čeština": ["cs", "ces"],
    "чешский": ["cs", "ces"],
    
    # Danish
    "danish": ["da", "dan"],
    "dansk": ["da", "dan"],
    "датский": ["da", "dan"],
    
    # Finnish
    "finnish": ["fi", "fin"],
    "suomi": ["fi", "fin"],
    "финский": ["fi", "fin"],
    
    # Greek
    "greek": ["el", "ell"],
    "ελληνικά": ["el", "ell"],
    "греческий": ["el", "ell"],
    
    # Hebrew
    "hebrew": ["he", "heb"],
    "עברית": ["he", "heb"],
    "иврит": ["he", "heb"],
    
    # Hungarian
    "hungarian": ["hu", "hun"],
    "magyar": ["hu", "hun"],
    "венгерский": ["hu", "hun"],
    
    # Latvian
    "latvian": ["lv", "lav"],
    "latviešu": ["lv", "lav"],
    "латышский": ["lv", "lav"],
    
    # Lithuanian
    "lithuanian": ["lt", "lit"],
    "lietuvių": ["lt", "lit"],
    "литовский": ["lt", "lit"],
    
    # Norwegian
    "norwegian": ["no", "nob"],
    "norsk": ["no", "nob"],
    "норвежский": ["no", "nob"],
    
    # Romanian
    "romanian": ["ro", "ron"],
    "română": ["ro", "ron"],
    "румынский": ["ro", "ron"],
    
    # Slovak
    "slovak": ["sk", "slk"],
    "slovenčina": ["sk", "slk"],
    "словацкий": ["sk", "slk"],
    
    # Slovenian
    "slovenian": ["sl", "slv"],
    "slovenščina": ["sl", "slv"],
    "словенский": ["sl", "slv"],
    
    # Swedish
    "swedish": ["sv", "swe"],
    "svenska": ["sv", "swe"],
    "шведский": ["sv", "swe"],
    
    # Thai
    "thai": ["th", "tha"],
    "ไทย": ["th", "tha"],
    "тайский": ["th", "tha"],
    
    # Ukrainian
    "ukrainian": ["uk", "ukr"],
    "українська": ["uk", "ukr"],
    "украинский": ["uk", "ukr"],
    
    # Vietnamese
    "vietnamese": ["vi", "vie"],
    "tiếng việt": ["vi", "vie"],
    "вьетнамский": ["vi", "vie"],
    
    # Bulgarian
    "bulgarian": ["bg", "bul"],
    "български": ["bg", "bul"],
    "болгарский": ["bg", "bul"],
    
    # Croatian
    "croatian": ["hr", "hrv"],
    "hrvatski": ["hr", "hrv"],
    "хорватский": ["hr", "hrv"],
    
    # Serbian
    "serbian": ["sr", "srp"],
    "српски": ["sr", "srp"],
    "сербский": ["sr", "srp"],
    
    # Catalan
    "catalan": ["ca", "cat"],
    "català": ["ca", "cat"],
    "каталонский": ["ca", "cat"],
    
    # Estonian
    "estonian": ["et", "est"],
    "eesti": ["et", "est"],
    "эстонский": ["et", "est"],
    
    # Galician
    "galician": ["gl", "glg"],
    "galego": ["gl", "glg"],
    "галисийский": ["gl", "glg"],
    
    # Malay
    "malay": ["ms", "msa"],
    "bahasa melayu": ["ms", "msa"],
    "малайский": ["ms", "msa"],
    
    # Tagalog
    "tagalog": ["tl", "tgl"],
    "wikang tagalog": ["tl", "tgl"],
    "тагальский": ["tl", "tgl"],
    
    # Indonesian
    "indonesian": ["id", "ind"],
    "bahasa indonesia": ["id", "ind"],
    "индонезийский": ["id", "ind"]
}

# Reverse mapping for quick lookup: {abbreviation: language_name}
REVERSE_LANGUAGE_CODES = {}
for lang_name, abbreviations in LANGUAGE_CODES.items():
    for abbr in abbreviations:
        if abbr not in REVERSE_LANGUAGE_CODES:
            REVERSE_LANGUAGE_CODES[abbr] = lang_name

def get_language_abbreviations(language_name):
    """
    Get abbreviations for a given language name.
    
    Args:
        language_name (str): Full name of the language
        
    Returns:
        list: List of abbreviations for the language, or empty list if not found
    """
    return LANGUAGE_CODES.get(language_name.lower(), [])

def get_language_name(abbreviation):
    """
    Get the language name for a given abbreviation.
    
    Args:
        abbreviation (str): Language abbreviation
        
    Returns:
        str: Full language name, or None if not found
    """
    return REVERSE_LANGUAGE_CODES.get(abbreviation.lower())

def normalize_language_code(code):
    """
    Normalize a language code to the standard format.
    
    Args:
        code (str): Language code to normalize
        
    Returns:
        str: Normalized language code, or original if not found
    """
    # Try to find the language name for this code
    lang_name = get_language_name(code)
    if lang_name:
        # Return the first (primary) abbreviation
        abbreviations = get_language_abbreviations(lang_name)
        if abbreviations:
            return abbreviations[0]
    return code

if __name__ == "__main__":
    # Example usage
    print("Language codes mapping:")
    print("-" * 30)
    
    # Test some examples
    test_languages = ["русский", "english", "français", "китайский"]
    for lang in test_languages:
        abbreviations = get_language_abbreviations(lang)
        print(f"{lang}: {abbreviations}")
    
    print("\nReverse lookup:")
    print("-" * 30)
    test_codes = ["ru", "en", "fr", "zh"]
    for code in test_codes:
        lang_name = get_language_name(code)
        print(f"{code}: {lang_name}")