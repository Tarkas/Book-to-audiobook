# DeepL Integration for ebook2audiobook

This document explains how to use the DeepL translation options in ebook2audiobook.

## Translation Methods

ebook2audiobook now supports multiple translation methods:

1. **Google Translate** (`google`) - Online translation service
2. **DeepL Official** (`deepl`) - Official DeepL API (requires API key)
3. **DeepL Parser** (`deepl_parser`) - Web-based parser implementation
4. **Argos Translate** (`argos`) - Offline translation engine

## Using DeepL Translation

### 1. DeepL Official API

To use the official DeepL API:

1. Sign up for a DeepL API key at https://www.deepl.com/pro-api
2. Add your API key to the application configuration
3. Select "deepl" as the translation method in the UI

Note: This method requires an internet connection and a paid API key for heavy usage.

### 2. DeepL Parser

The DeepL Parser uses web scraping to access DeepL translation:

1. Ensure ChromeDriver is installed and accessible
2. Select "deepl_parser" as the translation method in the UI
3. The parser will automatically handle the translation process

Note: Web-based parsing may be slower and less reliable than the official API.

## Configuration

### ChromeDriver Setup

For the DeepL Parser to work, you need to have ChromeDriver installed:

1. Download ChromeDriver from https://chromedriver.chromium.org/
2. Extract it to a known location
3. Update the path in `lib/deepl_parser.py` if necessary

## Troubleshooting

### CAPTCHA Issues

If you encounter CAPTCHA errors:
- Try using the official DeepL API instead
- Reduce the frequency of translations
- Use a different IP address

### Translation Quality

For best results:
- Use the official DeepL API for highest quality
- Ensure proper language codes are selected
- Check that your text is properly formatted

## Language Support

DeepL supports translation between many languages. Check the DeepL website for the most current list of supported language pairs.