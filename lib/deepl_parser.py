"""
DeepL Parser for ebook2audiobook
Adapted from the existing parser to work with DeepL instead of Google Translate
"""

import logging
import time
import random
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys


# --- Logging setup ---
log_formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(funcName)s - %(message)s')
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(log_formatter)
stream_handler.setLevel(logging.DEBUG)

app_log = logging.getLogger('deepl_parser')
app_log.setLevel(logging.DEBUG)
app_log.addHandler(stream_handler)


# --- Constants ---
DEEPL_BASE_URL = "https://www.deepl.com/translator"
CHROMEDRIVER_PATH = "C:/chromedriver/chromedriver.exe"  # Default path, can be overridden


# --- Browser setup ---
def setup_browser(chromedriver_path=None):
    """
    Setup Chrome browser for web scraping
    
    Args:
        chromedriver_path (str): Path to chromedriver executable
        
    Returns:
        webdriver.Chrome: Configured browser instance
    """
    app_log.info("Setting up browser...")
    
    # Use provided path or default
    driver_path = chromedriver_path if chromedriver_path else CHROMEDRIVER_PATH
    
    options = ChromeOptions()
    options.add_argument("--disable-infobars")
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("start-maximized")

    service = Service(executable_path=driver_path)
    browser = webdriver.Chrome(service=service, options=options)

    # Anti-detection for headless mode
    browser.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return browser


# --- Text translation function ---
def translate_text(browser, text, source_lang="en", target_lang="es"):
    """
    Translate text using DeepL web interface
    
    Args:
        browser (webdriver.Chrome): Browser instance
        text (str): Text to translate
        source_lang (str): Source language code
        target_lang (str): Target language code
        
    Returns:
        str: Translated text
    """
    try:
        app_log.debug(f"Translating text: '{text}' from {source_lang} to {target_lang}")

        # Navigate to DeepL with language parameters
        url = f"{DEEPL_BASE_URL}#{source_lang}/{target_lang}/{text}"
        browser.get(url)
        
        # Wait for the input area to be present
        input_area = WebDriverWait(browser, 60).until(
            EC.presence_of_element_located((By.XPATH, '//div[@contenteditable="true"]'))
        )

        # Clear and input text (in case it wasn't loaded properly)
        browser.execute_script("arguments[0].innerHTML = '';", input_area)
        input_area.send_keys(text)
        
        # Wait for translation to complete
        time.sleep(random.uniform(3, 5))

        # Check for CAPTCHA
        if "Please verify you are a human" in browser.page_source or "CAPTCHA" in browser.page_source:
            app_log.critical("CAPTCHA detected! DeepL is blocking automated access.")
            browser.save_screenshot("captcha_detected.png")
            raise Exception("CAPTCHA detected")

        # Wait for and extract the translation result
        # DeepL uses different selectors, so we need to find the right one
        try:
            # Try multiple selectors that DeepL might use
            result_element = WebDriverWait(browser, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 
                    "d-textarea[aria-labelledby*='target'] div, .lmt__textarea_container[aria-labelledby*='target'] div, div[aria-labelledby*='target-textarea']"))
            )
            result = result_element.text.strip()
        except:
            # Fallback: try to get text from any div with translated content
            time.sleep(2)
            result_elements = browser.find_elements(By.CSS_SELECTOR, "d-textarea div, .lmt__target_textarea")
            if result_elements:
                result = result_elements[0].text.strip()
            else:
                result = "[Translation failed]"

        app_log.debug(f"Translation result: '{result}'")
        return result

    except Exception as e:
        app_log.error(f"Translation error for '{text}': {e}")
        return "[TRANSLATION ERROR]"


# --- Main translation function ---
def translate_file(input_file, output_file, source_lang="en", target_lang="es", chromedriver_path=None):
    """
    Translate text file using DeepL parser
    
    Args:
        input_file (str): Path to input file
        output_file (str): Path to output file
        source_lang (str): Source language code
        target_lang (str): Target language code
        chromedriver_path (str): Path to chromedriver executable
    """
    browser = None
    try:
        browser = setup_browser(chromedriver_path)
        
        # Read input file
        with open(input_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        app_log.info(f"Translating file '{input_file}' from {source_lang} to {target_lang}")
        
        # Translate content
        translated_content = translate_text(browser, content, source_lang, target_lang)
        
        # Write output file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(translated_content)
            
        app_log.info(f"Translation saved to '{output_file}'")

    finally:
        if browser:
            browser.quit()
            app_log.info("Browser closed.")


# --- Simple function for translating text directly ---
def translate_text_simple(text, source_lang="en", target_lang="es", chromedriver_path=None):
    """
    Simple function to translate text directly
    
    Args:
        text (str): Text to translate
        source_lang (str): Source language code
        target_lang (str): Target language code
        chromedriver_path (str): Path to chromedriver executable
        
    Returns:
        str: Translated text
    """
    browser = None
    try:
        browser = setup_browser(chromedriver_path)
        return translate_text(browser, text, source_lang, target_lang)
    finally:
        if browser:
            browser.quit()


# Example usage
if __name__ == '__main__':
    # Test translation
    try:
        text = "Hello, this is a test translation."
        translated = translate_text_simple(text, "en", "es")
        print(f"Original: {text}")
        print(f"Translated: {translated}")
    except Exception as e:
        print(f"Error: {e}")