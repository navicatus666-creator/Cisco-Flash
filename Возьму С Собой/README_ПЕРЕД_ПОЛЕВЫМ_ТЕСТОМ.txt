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
- Последнюю папку `%LOCALAPPDATA%\CiscoAutoFlash\sessions\<session_id>\`
- `session_bundle_*.zip` из этой папки
- При наличии: соответствующие log/report/transcript файлы

Что не входит в комплект
- Прошивка/образ Cisco
- MCP, тесты, demo automation, dev tooling
