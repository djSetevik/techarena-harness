# Источники и технические ссылки

Дата подготовки пакета: 8 ноября 2026. Содержимое сайтов может меняться;
точную версию SDK и команды CLI сверять в момент установки.

## Первичные материалы соревнования
R1, Q1 и T1 поставлены пользователем и лежат в materials/original.
B1 — исторический код из переписки, не официальный образец организаторов.
U1 — уточнение владельца об отдельном разрешении организаторов использовать Codex
сугубо для разработки системы: materials/clarifications/codex-development-authorization.ru.md.
Вопрос допуска инструмента разработки закрыт по этому сообщению; R1/Q1 не переписаны.
В package_manifest.json записаны размеры и SHA-256 файлов пакета.
Инструкции разработки/архитектура/метрики в остальных документах — предложения,
которые не дополняют регламент новыми якобы официальными требованиями.

## Codex (проверенные официальные страницы)
- CLI: https://developers.openai.com/codex/cli/
- AGENTS.md: https://developers.openai.com/codex/guides/agents-md/
- CLI options: https://developers.openai.com/codex/cli/reference/
- Authentication: https://developers.openai.com/codex/auth/
- Security/sandbox: https://learn.chatgpt.com/docs/sandboxing
- Official repository/install: https://github.com/openai/codex

На момент проверки часть developers.openai.com/codex страниц перенаправляется
на learn.chatgpt.com. Использование AGENTS.md, --cd, --sandbox workspace-write,
--ask-for-approval on-request и login --device-auth подтверждено этими страницами.
Инструкция не требует конкретной модели Codex или опасного --yolo.

## openJiuwen (первичные проекты, не готовые гарантии совместимости)
- https://github.com/openJiuwen-ai/agent-core
- https://github.com/openJiuwen-ai/agent-core/blob/main/README.md
- https://github.com/openJiuwen-ai/jiuwenswarm

agent-core — SDK для агентов/workflow/модельных вызовов/инструментов. Это подходящая
точка интеграции; не нужно переносить весь GUI JiuwenSwarm в final Docker.
Не копировать пример отключённой проверки TLS из README без причины.
Проверить API именно закреплённого релиза и записать commit/version в проект.

## Не подтверждено этим пакетом
Окончательная команда запуска 9 ноября;
официальная метрика token estimator; точная финальная модель; версия oJ,
требуемая жюри; структура usage вашего прокси. Пакет не выполняет обращения
к вашим аккаунтам, Git-репозиторию или конкурсному API.
