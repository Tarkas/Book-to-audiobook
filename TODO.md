# TODO — Исправление сборки Android APK в Colab

Проблема: в Colab сборка падает с `:lintVitalRelease` — `ExpiredTargetSdkVersion`
(targetSdkVersion 30 < 31). Google Play требует target API ≥ 31.

## Шаги

- [x] Собрать информацию (build_report, spec, ноутбук)
- [x] `android_client/buildozer.spec`: `android.api = 30` → `android.api = 33`
      (target API 33 / Android 13; minapi остаётся 21, APK ставится на Android 5.0+)
- [x] `android_client/buildozer.spec`: bump `version` 1.1.1 → 1.2.0,
      `version.code` 3 → 4 (новая сборка ставится поверх старой как обновление)

## Перенос keystore с GitHub на Google Drive (безопасность)

- [x] Keystore размещён на Google Drive (ссылка для скачивания)
- [x] `Notebooks/build_android_apk.ipynb` (ячейка 2): скачивание keystore
      через `gdown --id <FILE_ID>` из Google Drive (без монтирования Drive)
- [x] `Notebooks/build_android_apk.ipynb` (ячейка 0, markdown): обновлена документация
- [x] `.gitignore`: keystore больше не коммитится (`*.keystore` игнорируется)
- [x] `android_client/README.md`: обновлена документация по ключу
- [x] `android_client/ebook2audiobook-release.keystore` удалён из git (`git rm --cached`);
      локальная копия сохранена + бэкап у пользователя (`C:\Users\Devuser\ebook2audiobook-release.keystore.backup`)

## Осталось (за пользователем)

- [ ] Закоммитить изменения + push в GitHub (включая удаление keystore из индекса)
- [ ] Убедиться, что keystore на Google Drive доступен **по ссылке** ("Anyone with the link")
- [ ] Проверить `KEY_FILE_ID` в ячейке (2) ноутбука = id из ссылки
- [ ] Пересборка в новом рантайме Colab через `Notebooks/build_android_apk.ipynb`
- [ ] Проверка `.apk` версии 1.2.0 (code 4) в `bin/`
- [ ] Установка APK на телефон (Android 10 подходит)
