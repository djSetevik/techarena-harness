# Этап 4: проверяемые эксперименты и контейнер
Прочитай AGENTS.md, текущие PROGRESS/OPEN_QUESTIONS, acceptance D01–D07.
Создай воспроизводимый generator синтетических пар/контрпримеров с seed и
отдельными labels/provenance. Изменение файла не считать автоматически
доказательством невыполнимости. Split по родительским шаблонам, не по мутациям.

Сделай evaluator без доступа runtime к expected. Метрики: проверенный reward,
actual/unresolved tokens, false skips и их reward, UNKNOWN, MAE/underprediction,
wall time. Отдельно показывай отсутствующие real traces, не выдумывай измерения.
Проведи доступные ablation offline; real API только при отдельном разрешении.

Проверь Dockerfile с явным COPY runtime, .dockerignore, pin зависимостей,
read-only/HOME=/tmp/task mount, отсутствие runtime downloads и секретов.
Ни docs/codex/materials с эталонами, ни регистрационные файлы в образ не копировать.
Docker-команды для привилегированного хоста подготовь владельцу для отдельного
запуска, не обходи sandbox через Docker socket. Актуальную финальную команду
организаторов не выдумывай. Обнови README и PROGRESS реальными результатами.
