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

## Перегенерация keystore (2026-08) — старый ключ был в git history

- [x] Сгенерирован НОВЫЙ keystore (`keytool -genkeypair`, RSA 2048, 10000 дней)
      на месте `android_client/ebook2audiobook-release.keystore`
- [x] Новый пароль: `ebook2audiobook2026` — проверен через `keytool -list` (RC=0)
- [x] `android_client/buildozer.spec`: `android.storepass` / `android.keypass`
      обновлены на `ebook2audiobook2026`
- [x] `Notebooks/build_android_apk.ipynb` (ячейка 2): добавлена заметка о
      перегенерации и необходимости загрузить НОВЫЙ keystore на Drive

## Исправление: APK собирался БЕЗ подписи → не ставился ни на один Android

Симптом: сборка в Colab "успешна", но APK не устанавливается ни на Android 8,
ни на Android 11 ("App not installed"). Причина — в `build_report.txt`:
`# Asking for release but P4A_RELEASE_* is missing--sign will not be passed`
и итоговый файл `...-release-unsigned.apk`. Android не ставит неподписанные APK.

Причина: buildozer НЕ передаёт `android.sign_key/keystore/...` из `buildozer.spec`
в python-for-android. p4a подписывает только если заданы переменные окружения
`P4A_RELEASE_KEYSTORE / KEYALIAS / KEYSTORE_PASSWD / KEYALIAS_PASSWD`.

- [x] (пробовали) `Notebooks/build_android_apk.ipynb` (ячейка 2): экспорт env-переменных
      `os.environ['P4A_RELEASE_*']` перед `buildozer android release` — НЕ сработало
      (файл всё ещё выходил `...-unsigned.apk`), т.к. встроенная подпись p4a
      ненадёжна и зависит от версии.
- [x] **Окончательное решение** — подпись через `apksigner` ПОСЛЕ сборки
      (ячейка 2 ноутбука): после `buildozer android release` APK подписывается
      напрямую `apksigner` из Android build-tools (уже скачанных buildozer'ом)
      постоянным keystore. Это детерминированно и всегда работает.
      Итоговый файл — `ebook2audiobook_client-...-signed.apk` (без `unsigned`).
- [x] `android_client/buildozer.spec`: комментарий, что подпись идёт через apksigner
- [x] Keystore проверен `keytool -list` (alias `ebook2audiobook`, пароль `ebook2audiobook2026` — OK)

## Осталось (за пользователем)

- [ ] Пересобрать APK в Colab через `Notebooks/build_android_apk.ipynb` (ячейки 1-3)
- [ ] Убедиться, что в `bin/` файл называется `ebook2audiobook_client-1.2.0...apk`
      (НЕ `...-unsigned...`) — значит APK подписан
- [ ] Установить подписанный APK на Android 8 и Android 11
- [ ] Закоммитить изменения + push в GitHub (включая удаление keystore из индекса)
- [ ] Убедиться, что keystore на Google Drive доступен **по ссылке** ("Anyone with the link")
- [ ] Проверить `KEY_FILE_ID` в ячейке (2) ноутбука = id из ссылки
