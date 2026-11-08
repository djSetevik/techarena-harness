# Первая задача Codex: аудит и offline-ядро

Ты разрабатываешь конкурсный харнесс TechArena на openJiuwen. Прочитай AGENTS.md,
docs/codex/PROJECT_BRIEF.md, RULES_AND_OPEN_QUESTIONS.md, BASELINE_AUDIT.md,
IMPLEMENTATION_SPEC.md и ACCEPTANCE_TESTS.md. Исходники правил — в materials/original.
Учитывай U1 из materials/clarifications/codex-development-authorization.ru.md:
владелец сообщил о разрешении Codex сугубо для разработки системы. Вопрос закрыт,
повторное подтверждение не нужно; в финальном runtime Codex/API Codex не использовать.
Цель не «решать любой ценой», а получать максимальный проверенный reward при
BUDGET, избегая расхода на доказуемо недоопределённые задачи.

Работай с существующим репозиторием, не переписывай всё с нуля. Сначала проверь
ветку/status и прочитай текущие run_agent.py, src, Dockerfile, requirements.
Составь короткий план и затем выполняй его, не останавливаясь на одном описании.

В ЭТОМ ЭТАПЕ:
1. Создай или обнови docs/OPEN_QUESTIONS.md с оставшимися конфликтами R1/Q1,
   не решая их самовольно. Допуск Codex к разработке уже закрыт по U1:
   существующий пункт отметь решённым и не создавай его заново.
2. Подготовь свежие fixtures скриптом docs/codex/tools/prepare_samples.py.
   Runtime не должен читать expected; внешнему grader разрешены отдельные labels.
3. Воспроизведи baseline с --max-llm-calls 0, сверяя 6 non-coding ответов вне runtime.
4. Введи TaskSpec и один atomic answer_writer: answer только рядом с task.json.
5. Добавь FeasibilityResult(SOLVABLE/UNSOLVABLE/UNKNOWN) с evidence и scope_complete.
   Реализуй консервативные, доказуемые проверки для структурированных search/CSV.
   Неизвестная формулировка/пустой regex/поломанный CSV → UNKNOWN, не UNSOLVABLE.
6. Добавь отрицательные и положительные контрпримеры F01–F12 из acceptance.
   Отдельно протестируй разделение kb между задачами и неизменность данных.
7. Сохрани совместимость текущего CLI и детерминированных решателей.
8. Выполни offline-тесты и составь docs/PROGRESS.md: что изменено, какие команды
   реально запускались, PASS/FAIL/NOT RUN, оставшиеся проблемы.

Никаких вызовов прокси, оплаты токенов, системных изменений, обновления SDK,
перезапуска JiuwenSwarm/heartbeat, root-shell инструментов, Git push.
Не выполняй coding-тесты/сгенерированный код на production root-хосте.
Если зависимостей для будущего SDK-теста нет, пометь этот тест NOT RUN;
детектор/парсеры/сохранение/стандартные Python-тесты сделай сейчас.
Итог: рабочие изменения и тесты этапа 1, а не обещание полного финального агента.
