import logging
import time
import random
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys


# --- Настройка логирования ---
log_formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(funcName)s - %(message)s')
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(log_formatter)
stream_handler.setLevel(logging.DEBUG)

app_log = logging.getLogger('google_translate_parser')
app_log.setLevel(logging.DEBUG)
app_log.addHandler(stream_handler)


# --- Константы ---
BASE_URL = "https://translate.google.com" 
INPUT_FILE = 'code_currency.csv'
OUTPUT_FILE = 'updated_currency_codes_russian_google.csv'
CHROMEDRIVER_PATH = "C:/chromedriver/chromedriver.exe"


# --- Настройка браузера ---
def setup_browser():
    app_log.info("Настройка браузера...")
    options = ChromeOptions()
    options.add_argument("--disable-infobars")
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("start-maximized")

    service = Service(executable_path=CHROMEDRIVER_PATH)
    browser = webdriver.Chrome(service=service, options=options)

    # Анти-детект headless-режима
    browser.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return browser


# --- Функция перевода текста ---
def translate_text(browser, text):
    try:
        app_log.debug(f"Перевод текста: '{text}'")

        # Ожидаем появления поля ввода
        input_area = WebDriverWait(browser, 60).until(
            EC.presence_of_element_located((By.XPATH, '//textarea[@aria-label="Исходный текст"]'))
        )

        # Очистка и ввод текста
        input_area.clear()
        input_area.send_keys(text)
        input_area.send_keys(Keys.ENTER)

        time.sleep(random.uniform(3, 5))  # Ждём завершения перевода

        # Проверка на капчу
        if "Please verify you are a human" in browser.page_source or "CAPTCHA" in browser.page_source:
            app_log.critical("Обнаружена капча! Google блокирует автоматизированный доступ.")
            browser.save_screenshot("captcha_detected.png")
            raise Exception("Капча обнаружена")

        # Явное ожидание появления результата перевода
        result_span = WebDriverWait(browser, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'span.ryNqvb[jsname="W297wb"]'))
        )

        result = result_span.text.strip()
        app_log.debug(f"Результат перевода: '{result}'")
        return result

    except Exception as e:
        app_log.error(f"Ошибка перевода '{text}': {e}")
        return "[ERROR]"


# --- Основная функция ---
def main():
    browser = setup_browser()
    try:
        app_log.info("Открытие страницы Google Translate...")
        browser.get(BASE_URL + "/?sl=en&tl=ru&op=translate")

        # Ждём загрузки поля ввода
        WebDriverWait(browser, 60).until(
            EC.presence_of_element_located((By.XPATH, '//textarea[@aria-label="Исходный текст"]'))
        )
        time.sleep(2)

        # Чтение CSV файла
        df = pd.read_csv(INPUT_FILE)
        app_log.info(f"Файл '{INPUT_FILE}' успешно прочитан. Количество строк: {len(df)}")

        # Перевод колонок
        app_log.info("Начинаю перевод колонки 'Currency Name'")
        df['Currency Name (Russian)'] = df['Currency Name'].apply(lambda x: translate_text(browser, x))

        app_log.info("Начинаю перевод колонки 'Country'")
        df['Country (Russian)'] = df['Country'].apply(lambda x: translate_text(browser, x))

        # Сохранение результата
        df.to_csv(OUTPUT_FILE, index=False)
        app_log.info(f"Результат сохранён в файл '{OUTPUT_FILE}'")

    finally:
        browser.quit()
        app_log.info("Браузер закрыт. Программа завершена.")


if __name__ == '__main__':
    main()