# Этап 2: бюджет и прогноз до запуска
Прочитай AGENTS.md, docs/PROGRESS.md, docs/OPEN_QUESTIONS.md и разделы E/F
IMPLEMENTATION_SPEC. Не меняй production/сырой набор задач.

Реализуй общий BudgetManager по BUDGET; десятые единицы input+10*output,
недвойной reasoning, полный cached input, резерв перед каждым запросом.
Покрой отправленный запрос с timeout, usage absent, exception после ответа,
SDK retries, конкурирующие резервы и отмену. Моки не делают сетевых запросов.
При BUDGET=0 разрешены только детерминированные действия.

Сохраняй неизменный исходный прогноз затрат до solve, отделяй re-estimate.
Сделай базовый estimator без expected/task_id/reward в cost features и scheduler,
который использует reward как ценность, а не как признак выполнимости.
UNKNOWN не выбрасывай безусловно. Для отказа из-за бюджета используй skip_reason,
не UNSOLVABLE. Дешёвые безопасные вычисления выполняй до дорогих попыток,
но сохрани исходные прогнозы заранее.

Выполни B01–B15, regression A/F. Добавь проверку fake LLM call count=0 для
доказанных невыполнимых задач. Никаких real API и авто-push. Обнови PROGRESS.
