CiscoAutoFlash — полевой комплект для Cisco 2960-X

Как запускать
- Открой `Запустить CiscoAutoFlash.bat`
- Если bat не сработает, запусти `CiscoAutoFlash\CiscoAutoFlash.exe`

Что делать на месте
- Подключись к Cisco 2960-X по Serial/USB
- Пройди реальный smoke по шагам в приложении
- Встроенная вкладка `Памятка` читает документы из `docs/pre_hardware`,
  они уже включены в bundle

Где будут логи и артефакты
- `%LOCALAPPDATA%\CiscoAutoFlash\logs\`
- `%LOCALAPPDATA%\CiscoAutoFlash\reports\`
- `%LOCALAPPDATA%\CiscoAutoFlash\transcripts\`
- `%LOCALAPPDATA%\CiscoAutoFlash\sessions\<session_id>\`

Что привезти обратно
- `session_bundle_*.zip` из `%LOCALAPPDATA%\CiscoAutoFlash\sessions\<session_id>\`
- Если bundle не экспортировался:
  вся папка `%LOCALAPPDATA%\CiscoAutoFlash\sessions\<session_id>\`
- При наличии: соответствующие log/report/transcript файлы

Что сделать потом на dev-машине
- Запусти:
  `python C:\PROJECT\scripts\triage_session_return.py `
  `"<bundle-or-session-folder>" --output-dir C:\PROJECT\triage_out`
- Это соберёт короткую сводку по manifest/report/transcript/log без ручного копания
- Сначала смотри в ней `failure_class`, `most likely cause`, `recommended next capture` и `inspect next`

Что не входит в комплект
- Прошивка/образ Cisco
- MCP, тесты, demo automation, dev tooling
