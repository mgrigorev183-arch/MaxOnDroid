# Changelog / Изменения

The format follows [Keep a Changelog](https://keepachangelog.com/); versions follow [Semantic Versioning](https://semver.org/).
Формат по Keep a Changelog, номера версий по Semantic Versioning.

## 0.9.0 — 2026-11-13

The first release with a Windows installer. / Первый выпуск с установщиком для Windows.

### Добавлено
- Установщик для Windows 10 и 11 (64-бит): ставится только для текущего пользователя, без прав администратора, по умолчанию в `%LOCALAPPDATA%\Programs\MaxOnDroid`. Папку можно выбрать; папки, которым нужны права администратора (Program Files, Windows, ProgramData), установщик не принимает и объясняет почему. Русский и английский языки.
- Внутри установщика scrcpy 5.0.1 вместе с adb: отдельно ставить Platform-Tools и scrcpy не нужно. Архив scrcpy при сборке сверяется с опубликованной SHA-256.
- Проверка обновлений: раз в день программа спрашивает у GitHub номер последнего выпуска и, если он новее, показывает ссылку на страницу выпуска. Сама ничего не скачивает и не устанавливает. Выключается в настройках, проверить вручную можно в меню «Справка».
- Самопроверка собранной программы (`MaxOnDroid.exe --self-test отчёт.json`): adb, scrcpy, база пакетов, оба языка, окно. Сборка в GitHub Actions проверяет так и собранную папку, и установленную копию.
- Выпуск по тегу в GitHub Actions: тесты, сборка, тихая установка, самопроверка, удаление, публикация установщика и файла `.sha256`.
- Проверка безопасности перед выпуском: отчёт в `docs/security-review.md`.

### Исправлено (по итогам проверки безопасности)
- Текст с устройства (имена пакетов и файлов, ответы adb) больше не может отрисоваться в окне как HTML: подписи и подтверждения выводятся простым текстом.
- Код сопряжения не сохраняется в истории консоли (там остаётся «••••••»).
- Сетевые запросы (база UAD-ng и проверка обновлений) не идут по перенаправлению с HTTPS на HTTP и ограничены по размеру.
- Сборочные зависимости закреплены по версии и SHA-256, действия GitHub Actions закреплены по коммиту, у рабочих процессов минимальные права.

### Возможности, накопленные с этапов 1–4
- Список устройств с номерками, подключение по USB, адресу, коду сопряжения, QR и поиску в сети, автоматическое переподключение.
- Вкладки «Обзор», «Приложения», «Чистка» (база UAD-ng, риск 1–4, пресеты, отмена изменений), «Пульт», «Экран» (scrcpy, запись в MP4, скриншоты), «Файлы» (с поиском по имени, расширению и типу), «Консоль».
- Журнал команд и журнал диагностики, русский и английский языки, светлая и тёмная темы.

### Added (English)
- Per-user Windows installer (no administrator rights, folder choice, admin-only folders refused), Russian and English.
- scrcpy 5.0.1 with adb bundled; the archive is checked against its published SHA-256 at build time.
- Daily update check that only shows a link to the release page; never downloads. Can be turned off; Help → Check for updates.
- `--self-test REPORT.json` for the built app; the release workflow runs it on the build and on the installed copy.
- Tag-driven GitHub Actions release with the installer's SHA-256.
- Security review fixes: device text shown as plain text, pairing code masked in console history, HTTPS-only redirects and size limits for network requests, hash-pinned build dependencies, commit-pinned actions with least privileges.
