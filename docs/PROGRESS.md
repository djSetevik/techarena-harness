# Этап 1 — аудит и offline-ядро, 2026-11-08

Актуальный итог: контейнер techarena:validated, openJiuwen 0.1.19, **71/71 tests PASS**;
проверки C01 и D01–D06 выполнены в Docker. Полная новая запись — в конце файла,
машиночитаемая сводка — docs/evaluation/container-validation.json. Более ранние
NOT RUN/blocked ниже являются историей до разрешения контейнерных проверок.
Разрешённый live-прогон 2026-11-09 также завершён: **8/8 примеров, reward20**,
два запроса qwen3.8-27b, 733.7 выходного эквивалента. См. последнюю запись
и docs/evaluation/live-samples-20261109.json; прежний C07 NOT RUN — история.

Ниже сначала сохранена запись предыдущего выполнения. Актуальная повторная
проверка и состояние дерева при начале текущей сессии приведены в конце.

Ветка main. До изменений: только неотслеживаемый `.local/`, не читался и не менялся.
Прочитаны AGENTS.md, START_PROMPT, brief, R1/Q1/U1, baseline audit,
implementation spec, acceptance и 01_AUDIT_AND_OFFLINE. Коммиты/push не выполнялись.
Системные службы, SSH, heartbeat, чужие конфиги и установки не затрагивались.

## Аудит и изменения

`run_agent.py`, `src/solvers.py`, Dockerfile и requirements.txt побайтно совпали
с соответствующими файлами B1. Baseline на свежей копии сохранил 6/8 ответов;
внешний grader подтвердил все 6 non-coding и 16 баллов. Дубли ответов в workspace
были воспроизведены; в новом writer устранены.

- `src/domain.py`: неизменяемый whitelist TaskSpec, Status, Evidence и FeasibilityResult.
- `src/task_loader.py`: проверка типа/reward, scope после resolve, bounded read;
  expected и остальные неизвестные поля не передаются решателю.
- `src/answer_writer.py`: один output рядом с task.json, уникальный временный
  файл, flush/fsync/replace/cleanup, пустые ответы отвергаются, существующие сохраняются.
- `src/feasibility.py`: полный ограниченный обход KB без cross-task cache,
  aliases/дубли/цепочки, UNKNOWN при непонятной семантике/неполном scope;
  проверяемые свидетельства для явно закрытой скалярной схемы.
  CSV: точная целочисленная сумма, ноль по пустому фильтру, два возможных итога
  при пустых units релевантных строк; malformed/формулы/IO → UNKNOWN.
- `src/solvers.py`: search/CSV используют общий detector вместо первого regex-факта.
- `run_agent.py`: TaskSpec, detector, writer; UNKNOWN не помечается UNSOLVABLE.
  CLI совместим по параметрам; coding/live временно отключён до ledger и изоляции.
- `tests/test_offline.py`: 18 тестов, F01–F12 и P0; mock запрет сети,
  LLM и исполнения task-программ в integration.
- `README.md`, `docs/OPEN_QUESTIONS.md`: актуальные команды, границы, конфликты;
  допуск Codex к разработке закрыт ссылкой на U1.
- `.dockerignore`: исключены dev-материалы и локальные credentials/build artifacts.

Закрытая KB v1 — наш явно включаемый синтетический контракт, не правило
организаторов. Для обычной KB отсутствие факта даёт UNKNOWN. Приоритеты/даты
не поддержаны и дают UNKNOWN. Feasibility для math/coding ещё UNKNOWN.
Первый этап не реализует budget/estimator/scheduler или реальную oJ-интеграцию.
Старый coding/SDK-код сохранён, но недоступен из текущего CLI и не проверен.
Math baseline сохранён; известный риск частично распознанных новых операций
остаётся для этапа специализированных решателей.

## Реально выполненные команды

```bash
git status --short
git branch --show-current
python docs/codex/tools/prepare_samples.py --out /tmp/techarena-stage1-baseline
python run_agent.py --tasks-dir /tmp/techarena-stage1-baseline/tasks --max-llm-calls 0
python docs/codex/tools/grade_non_coding.py --tasks-dir /tmp/techarena-stage1-baseline/tasks --labels /tmp/techarena-stage1-baseline/evaluation/official_answers.json
python -m compileall -q run_agent.py src tests
python -m unittest discover -s tests -v
git diff --check
```

Integration готовит две новые временные копии из исходного архива и удаляет их
после проверки. Grader запускается отдельно от runtime; task-программы не исполняются.
Проверяются исходные байты всех runtime inputs после прогона и SHA256 архива.
Никаких установок зависимостей, сетевых обращений к прокси или Docker запусков.

| Критерий | Результат | Проверка |
|---|---|---|
| Синтаксис | PASS | compileall |
| Offline unit/integration | PASS | 18 тестов unittest |
| A01 | PASS | 8 задач без labels/answers, два fresh prepare |
| A02 | PASS | baseline 6/6 non-coding, verified reward=16; новый runtime то же |
| A03 | PASS | fake expected не меняет TaskSpec/результат, whitelist |
| A04 | PASS | task_id/reward и сущность переименованы в unit; независимые temp dirs |
| A05 | PASS | единственное место ответа, пустые/существующие ответы, cleanup ошибки |
| A06 | PASS | inputs побайтно неизменны, архив SHA256, две свежие копии |
| A07 | PASS | одинаковая сущность в двух KB даёт разные собственные ответы |
| F01–F05 | PASS | закрытая missing/дубли/aliases, свободный текст → UNKNOWN |
| F06 | PASS | неподдержанный приоритет → UNKNOWN, не ложный UNSOLVABLE |
| F07 | PASS | лимиты файлов/байт → UNKNOWN, scope_complete=false |
| F08–F11 | PASS | zero sum, missing units evidence, recovery → UNKNOWN, irrelevant blanks |
| F12 | PASS | неизвестный dialect, malformed CSV, PermissionError → UNKNOWN |
| Ложные UNSOLVABLE на T1 | PASS | 0/8, потерянный reward=0 |
| C01/C07 real oJ/API | NOT RUN | отдельный этап, live требует согласования |
| Coding task execution | NOT RUN | нет разрешённой изолированной среды |
| D01–D05 Docker/runtime | NOT RUN | Docker не запускался |
| D07 финальная команда/модели | NOT RUN | нет окончательного контракта |

Результат относится только к видимым примерам и синтетическим контрпримерам,
не к скрытому набору. NOT RUN не означает PASS. Остальные этапы не выполнялись.

## Повторный аудит этапа 1 — 2026-11-08

При старте текущей сессии ветка `main` уже содержала незакоммиченные изменения:
README.md, run_agent.py, src/solvers.py; неотслеживаемые .dockerignore, .local/,
docs/OPEN_QUESTIONS.md, этот отчёт, src/answer_writer.py, src/domain.py,
src/feasibility.py, src/task_loader.py и tests/. Это отличается от исходного
состояния, описанного в предыдущей записи. Существующая реализация сохранена;
.local/ не читался и не менялся. Утверждение предыдущей записи о побайтном
совпадении текущего дерева с B1 к началу этой сессии не относится.

Прочитаны AGENTS.md, START_PROMPT, PROJECT_BRIEF, RULES_AND_OPEN_QUESTIONS,
R1/Q1/U1, BASELINE_AUDIT, IMPLEMENTATION_SPEC, ACCEPTANCE_TESTS и задание 01.
Проверены текущие runtime-модули, Dockerfile, requirements, тесты и dev-tools.
Открытые вопросы уже отражены в docs/OPEN_QUESTIONS.md, включая закрытие U1;
дополнительных изменений правил не потребовалось.

Изменения этой сессии:

- `src/feasibility.py`: конфликт промежуточных работодателей даёт UNKNOWN.
  Разные работодатели или два alias одной компании могут вести к одному городу;
  конфликт ребра сам по себе не доказывает неоднозначность итогового ответа.
- `src/task_loader.py`: запрещены symlink для task.json и каталога задачи.
  Resolve только относительно общего batch ранее позволял подставить контекст
  другой задачи из того же batch.
- `tests/test_offline.py`: три дополнительных регрессионных теста для этих случаев.
- `tests/test_baseline.py`: самостоятельное воспроизведение архивного B1.
  Три необходимых исходных файла извлекаются в свежий TemporaryDirectory;
  fixtures готовит prepare_samples.py, вызов идёт с --max-llm-calls 0.
  Сеть и subprocess внутри baseline запрещены mock-guards, окружение дочернего
  процесса содержит только фиксированный PATH и PYTHONDONTWRITEBYTECODE.
  Labels читает отдельный grader, не baseline. Проверены SHA256 обоих архивов
  и байты runtime inputs; старый дефект четырёх workspace/answer.txt воспроизведён.

Реально выполненные команды текущей сессии:

```bash
git status --short
git branch --show-current
git diff --stat
python -m compileall -q run_agent.py src tests docs/codex/tools
python -m unittest discover -s tests -v
git diff --check
```

`unittest` реально вызывает prepare_samples.py как модуль для трёх свежих копий:
одной для B1 и двух для текущего runtime. Внешний grade_non_coding.py запускается
отдельным процессом для каждой копии. Код из coding-задач не исполняется.

| Проверка | Статус | Фактический результат |
|---|---|---|
| Синтаксис | PASS | compileall, exit 0 |
| Offline unit/integration | PASS | 22 теста, 0 ошибок |
| A01, A03–A07 | PASS | свежие fixtures, whitelist labels, scope, writer, неизменность inputs |
| A02, архив B1 | PASS | 6/6 non-coding, внешний verified reward=16; 2 coding пропущены |
| Текущий runtime | PASS | обе свежие копии: 6/6 non-coding, verified reward=16 |
| F01–F12 | PASS | включая новые контрпримеры промежуточных связей |
| Ложные UNSOLVABLE на T1 | PASS | 0/8, потерянный из-за классификации reward=0 |
| Whitespace diff | PASS | git diff --check, exit 0 |
| C01/C07 SDK/live API | NOT RUN | этап 1 не подтверждает интеграцию oJ |
| Coding-программы / Docker D01–D05 | NOT RUN | изолированная среда не запускалась |
| Финальный контракт D07 | NOT RUN | остаётся открытым по исходным материалам |

Ограничения предыдущей записи сохраняются: узкие query/CSV-схемы, UNKNOWN для
неподдержанных приоритетов/формул, отсутствие budget/estimator/scheduler и
подтверждённого execution path oJ. Ветвящиеся search-цепочки пока дают UNKNOWN,
а не реализованный перебор альтернатив. Math baseline оставлен без расширения.
Моки доказывают только offline-поведение этого прогона, не live API и не скрытый
набор. Установок, обновлений зависимостей, обращений к прокси, Docker-запусков,
коммитов и push в этой сессии не было. Другие этапы не реализованы.

## Этап 2 — бюджет и планировщик, 2026-11-08

Последовательно после этапа 1 реализованы src/budget.py, src/estimator.py,
src/scheduler.py, src/telemetry.py; CLI подключён к общему ledger и прогнозам.
Исходные незакоммиченные изменения сохранены, push/commit не выполнялись.

BudgetManager хранит целые десятые доли: input + 10*output. Usage включает
reasoning ровно один раз по явно указанной схеме; cached input не вычитается.
Резервы атомарны под RLock; отмена до отправки возвращает резерв, после отправки
сохраняет unresolved. Timeout/некорректный или отсутствующий usage останавливает
новые платные запросы, поскольку резерв — приблизительный, не доказанный cap.
При недооценке фактический расход не обрезается и ledger также закрывается.
Одна execute-операция — одна попытка, без автоматических retries. Декодирование
результата решателем происходит после фиксации usage. Схема реального прокси
пока не подтверждена: нормализация проверена только на явных mock-форматах.

Прогноз static-v1-uncalibrated неизменяемый, признаки: тип и UTF-8 размер
инструкции. Никаких expected/task_id/reward в cost features. Вероятности успеха
не заявляются; планировщик использует одинаковый вес успеха и reward/cost.
Исходный task_prediction записывается для всех задач до detector/solve;
события task scope и последовательность, flush после каждой записи.
По умолчанию JSONL идёт в stdout; --metrics-path создаёт новый файл вне
runtime-исходников и задач. Re-estimate — отдельное событие, не замена prediction.
Пропуски не становятся обучающими примерами с целевой стоимостью 0.

Детерминированные действия идут первыми даже при BUDGET=0. Нерешённые UNKNOWN
передаются планировщику. UNSOLVABLE отфильтровываются до adapter. Пока adapter
этапа 3 не подключён, платные кандидаты получают явный adapter_unavailable;
недостаток бюджета — skip_reason=budget, не UNSOLVABLE. Отсутствующий BUDGET
в offline означает 0; live-парсер требует явный BUDGET. Некорректное значение
отклоняется CLI до решения задач.

Команды:

```bash
python -m compileall -q run_agent.py src tests
python -m unittest discover -s tests -v > /tmp/techarena-stage2-tests.log 2>&1
git diff --check
python -c "import importlib.util as u; print(u.find_spec('openjiuwen'))"
```

| Проверка | Статус | Результат |
|---|---|---|
| Синтаксис / whitespace | PASS | обе команды exit 0 |
| Offline suite | PASS | 34 теста, 0 ошибок; лог /tmp/techarena-stage2-tests.log |
| B01–B03 | PASS | 2000+500 → 700 выходных; separate reasoning; cached; дроби |
| B04–B06 | PASS | CLI BUDGET=0 сохраняет 6 ответов; invalid budget; конкурирующие резервы |
| B07–B11 | PASS | timeout/cancel/usage absent/invalid, post-response error, retry accounting, exhaustion |
| B12 | PASS | immutable forecast; 8 initial events до первого solve; re-estimate отдельно |
| B13–B15 | PASS | UNKNOWN выбран, proven UNSOLVABLE 0 fake calls; порядок high/mid/low, расход 90/100 units; skip не training label |
| A/F regression и B1 | PASS | 0 false UNSOLVABLE на 8 примерах; grader 6/6 non-coding, reward=16 |
| Real proxy / SDK / Docker | NOT RUN | сетевых LLM-вызовов и установок не было |

Первый прогон выявил конфликт blanket mock socket с внутренним socketpair
asyncio. Исправлен runtime: при отсутствии adapter синхронная часть планировщика
не создаёт event loop. После исправления повторная полная suite PASS.

Для этапа 3 текущий Python сообщает openjiuwen NOT INSTALLED. Запрошено отдельное
разрешение на установку в окружение проекта; production .venv не используется.
Общий goal остаётся активным, этапы 3–5 ещё не объявляются завершёнными.

## Этап 3 — реализована offline-часть, 2026-11-08

Перед работой повторно проверены git status, текущие модули и задание 03;
предыдущий goal-turn дал прогресс (ledger, scheduler и проверенные 34 теста).
Незакоммиченные изменения сохранены, .local/ и внешние установки не читались.

Текущий Python: openjiuwen NOT INSTALLED (importlib.util.find_spec и metadata
на этапе 2). Разрешение на установку, запрошенное отдельно, ещё не получено.
Ничего не устанавливалось. Проверены официальные web-исходники по адресам:

- https://raw.githubusercontent.com/openJiuwen-ai/agent-core/v0.1.19/openjiuwen/core/foundation/llm/model.py
  — Model.__init__ и async Model.invoke, параметры model/messages/max_tokens/timeout.
- https://raw.githubusercontent.com/openJiuwen-ai/agent-core/v0.1.19/openjiuwen/core/foundation/llm/schema/config.py
  — ModelClientConfig, ModelRequestConfig, max_retries/verify_ssl.
- https://raw.githubusercontent.com/openJiuwen-ai/agent-core/v0.1.19/openjiuwen/core/foundation/llm/model_clients/openai_model_client.py
  — _parse_response передаёт input/output/cache/reasoning в usage_metadata;
  _build_async_openai_client создаёт transport с max_retries=0.

Это проверка опубликованного исходного контракта, не доказательство идентичности
установленному wheel: пакета пока нет. Именно поэтому C01 остаётся NOT RUN;
конфликт требуемой версии/последнего релиза не закрыт.

Изменения:

- src/oj_adapter.py: единственная модельная граница через BudgetManager,
  фиксированная модель, timeout/max output, общий call cap (включая ремонты),
  резерв по полному prompt с файлами/диагностикой, usage до разбора ответа,
  raw usage whitelist отдельно от normalized, explicit reasoning schema.
  SDK грузится лениво, проверяется pin 0.1.19; нет auto-retry/warmup/embeddings.
- src/coding.py: явный поддержанный контракт исходника/теста из инструкции;
  пути/симлинки ограничены scope; свежие копии, контроль байтов всех tests/data,
  синтаксис без исполнения, до двух исправлений, краткая диагностика,
  timeout/mutation → без DONE. До успеха исходник задачи не меняется;
  после успеха атомарно заменяется только разрешённый source.
  Исходный код проверяется до платной попытки, возможен DONE при BUDGET=0.
- src/verification.py: настоящий ограниченный subprocess-runner подготовлен,
  но не запускался. Требует explicit isolated deployment и euid != 0,
  не наследует окружение, ограничивает CPU/RAM/output/time/processes/fds,
  убивает группу процессов. Это defense in depth, НЕ sandbox; общий UID и /proc,
  сетевую/файловую изоляцию обеспечивает контейнерная политика оператора.
- src/model_solver.py: bounded task-local контекст для остальных типов;
  expected/task.json/другие задачи не отправляются модели, abstention отдельно
  от формального UNSOLVABLE. Format check не объявлен доказательством ответа.
- src/solvers.py: старый прямой SDK/coding-subprocess путь удалён, чтобы не было
  обхода общего ledger. Math полностью потребляет поддержанные операции;
  неизвестная операция/нулевой divisor/новая suffix-семантика → None/UNKNOWN.
- run_agent.py: модельный путь подключён, по умолчанию offline. Для live нужны
  --enable-llm, явный Q1 --model, BUDGET, proxy env и --reasoning-usage;
  --isolated-coding требует отдельного non-root container deployment.
- tests/test_solvers.py: fake repair/timeout/mutation/env/paid runtime;
  C01 реального SDK с fake нижним transport подготовлен и автоматически skipped
  без зависимости. Ранее написанные offline network guards перенесены на новые
  module boundaries; исходные конкурсные данные/тесты не изменялись.
- tools/live_smoke.py: готов отдельный opt-in C07 с cap=16, max_calls=1,
  BUDGET<=1000; NOT RUN, требуется разрешение и подтверждение модели/usage.

Команды:

```bash
python -m compileall -q run_agent.py src tests tools
python -m unittest discover -s tests -v > /tmp/techarena-stage3-tests.log 2>&1
git diff --check
```

| Проверка | Статус | Свидетельство |
|---|---|---|
| Синтаксис / whitespace | PASS | exit 0 |
| Offline suite | PASS | 45 discovered: 44 passed, 1 skipped |
| A/F/B regression | PASS | видимые 6/6 non-coding, reward=16; fake expected не отправляется |
| C01 | NOT RUN | SDK отсутствует, установка ожидает подтверждения |
| C02 | PASS (fake) | неверный patch → исправление; обе usage учтены, tests неизменны |
| C03 | PASS (fake) | compile error и timeout не меняют оригинал и не дают DONE |
| C04/C05 | PASS | ../, absolute, test/config, symlink; mutation копии отвергнута |
| C06 | PASS (configuration/fake) | root/unisolated отказ, env whitelist, timeout/output/kill group |
| Реальное исполнение coding | NOT RUN | нет одобренной изолированной non-root среды |
| C07 live Qwen | NOT RUN | нет отдельного разрешения/подтверждённой модели/usage |

Остаётся проверить SDK wheel и C01 после подтверждения установки. Реальный
coding-runner, Docker и live API не запускались. Fake-тесты не подтверждают
работу настоящего Qwen, SDK transport или скрытого checker. Этап 3 нельзя
считать полностью проверенным; offline-реализация и подготовленные проверки
готовы к следующему подтверждению. Goal активен, этапы 4–5 ещё впереди.

## Этап 4 — offline-эксперименты и подготовка контейнера, 2026-11-08

При старте проверен текущий git status, прочитаны задание 04/05, требования D,
актуальные модули и отчёт. Предыдущий goal-turn дал прогресс: реализация
модельного/coding пути и 44 PASS + C01 NOT RUN. Разрешения установки SDK,
live API и Docker по-прежнему нет. Ничего из этого не запускалось.

Добавлены tools/generate_synthetic.py и tools/evaluate_offline.py. Генератор
с seed=2026 создаёт 28 задач (по два экземпляра семи вариантов, пары на экземпляр).
Labels/expected/provenance остаются в evaluation/, runtime task.json их не содержит.
Для UNSOLVABLE явно указаны два допустимых результата и причина: missing closed
scalar или blank relevant units без recovery. Проза/точная формула с известным
ответом остаются SOLVABLE во внешней разметке, даже когда detector возвращает
UNKNOWN. Мутация сама по себе не считается доказательством.

Split по ТРЁМ семантическим родителям: birth_query, employer_hq_query,
filtered_units_sum. Born prose, company aliases, empty sums и formula — варианты
этих родителей, а не независимые шаблоны для split. Все их мутации/экземпляры
остаются вместе. Seed=2026: первые два train-родителя employer_hq_query и
filtered_units_sum; test — birth_query. Это tiny quality corpus, не доказательство
обобщения и не репрезентативный финальный benchmark; обучение не проводилось.
Первоначальный черновой split по семи синтаксическим семействам был отклонён
до фиксации итогового отчёта: связанная проза/aliases иначе могли разойтись.

Evaluator копирует только runtime-задачи выбранного split в свежий temp-root,
labels читает только внешний процесс. Дочерний runtime получает BUDGET=0,
не наследует proxy env; сеть и subprocess заблокированы guards. Проверяются
неизменность входов и наличие исходного прогноза для каждой задачи.
Метрики: external verified reward, actual/unresolved units и output equivalents,
false UNSOLVABLE, false skip/reward, UNKNOWN, skip reasons, wall time.
MAE/underprediction/high coverage считаются только для отправленных попыток
с известным usage, а не для skipped=0; без наблюдений возвращается null.

Реально выполненные команды:

```bash
python -m compileall -q run_agent.py src tests tools
python -m unittest discover -s tests -v > /tmp/techarena-stage4-tests.log 2>&1
python tools/generate_synthetic.py --out /tmp/techarena-stage4-corpus-parentgroups-2026 --seed 2026 --instances 2
python tools/evaluate_offline.py --corpus /tmp/techarena-stage4-corpus-parentgroups-2026 --out docs/evaluation/stage4-seed2026.json > /tmp/techarena-stage4-ablations.log
git diff --check
```

Сохранённый отчёт: docs/evaluation/stage4-seed2026.json (6 реальных offline-прогонов).

| Split / режим | Задач | Правильных ответов | Verified reward | UNKNOWN | Wall time, s |
|---|---:|---:|---:|---:|---:|
| train / full | 20 | 10 | 34 | 2 | 0.231 |
| train / no_gate | 20 | 10 | 34 | 2 | 0.209 |
| train / no_deterministic | 20 | 0 | 0 | 2 | 0.231 |
| test / full | 8 | 4 | 13 | 2 | 0.224 |
| test / no_gate | 8 | 4 | 13 | 2 | 0.188 |
| test / no_deterministic | 8 | 0 | 0 | 2 | 0.195 |

Всего в full 14 правильных из 18 решаемых, reward=47; ещё четыре положительных
примера без ответа (UNKNOWN), десять отрицательных пропущены доказательно.
False UNSOLVABLE=0, false skips=0, false skip reward=0. Это не означает отсутствия
потерянного reward из-за всех UNKNOWN: такие пропуски отдельно видны в coverage.
Все режимы: 0 LLM requests, actual=0, unresolved=0, cost observations=0,
MAE/underprediction/coverage=null. Одинаковый reward full/no_gate при BUDGET=0
не является измерением экономии токенов. No_gate выключает доказательный пропуск,
а дешёвые search/CSV-инструменты сохраняют собственное безопасное воздержание.
No_deterministic выключает сохранение дешёвых ответов; платный путь в ablations
запрещён. Real model traces отсутствуют и прямо отмечены в отчёте.

Упаковка: Dockerfile сохраняет прямой pin и базовый tag, добавляет USER 10001:10001
и HOME=/tmp; .dockerignore переведён на allowlist Python runtime/requirements.
COPY явно ограничен runtime. Base digest и transitive lock НЕ выдуманы, pending
после одобренного resolver/build. docs/DOCKER_CHECKS.md содержит owner-only команды
build/read-only/network-none/fresh task mount/grader/inspection и условия записи
для UID 10001. Эти команды НЕ исполнялись.

Добавлен handler SIGTERM/KeyboardInterrupt с exit 143/130 и сохранением ledger.
tests/test_interrupt.py реально запускает доверенный Python-харнесс (не task code),
останавливает его SIGTERM во время второго детерминированного решения и проверяет
первый сохранённый answer, отсутствие второго/временных файлов и run_interrupted.
tests/test_evaluation.py проверяет seeded воспроизводимость, parent split,
separation, external ablations, cost aggregation и статическую упаковку.

| Критерий | Статус | Основание |
|---|---|---|
| Синтаксис / diff whitespace | PASS | exit 0 |
| Offline suite | PASS | 50 discovered, 49 PASS, C01 skipped; /tmp/techarena-stage4-tests.log |
| Генератор / evaluator / ablation | PASS | 6 запусков, входы неизменны, source labels hash в отчёте |
| D01 build/size/time | NOT RUN | Docker не запускался, digest/transitive pins pending |
| D02 read-only container | NOT RUN | статический профиль подготовлен; runtime не проверен |
| D03 network-none Docker | NOT RUN | native guards PASS, Docker не запускался |
| D04 image layers/секреты | NOT RUN | runtime-only COPY/allowlist статически PASS, образ не инспектирован |
| D05 SIGTERM | PASS native / NOT RUN Docker | настоящий SIGTERM trusted harness, контейнер не запускался |
| D06 README | PASS | реальные команды/метрики/ограничения/NOT RUN описаны |
| D07 final contract | NOT RUN | публикации финальной команды/SDK/модели в пакете нет |
| C01/C07 и coding subprocess | NOT RUN | сохраняются ограничения этапа 3 |

Push/commit, установки, системные изменения и чужие конфиги не выполнялись.
Offline-часть этапа 4 выполнена; SDK/Docker/final gates не закрыты.
Goal активен; следующий доступный шаг — ревью этапа 5 с фиксацией находок до правок.

## Этап 5 — review, исправления и completion audit, 2026-11-08

Текущий status проверен до изменений; прочитаны AGENTS, R1/Q1/U1,
OPEN_QUESTIONS, implementation/acceptance, задание 05 и реальные логи этапа 4.
Предыдущий goal-turn дал прогресс (генератор/evaluator, шесть offline ablations,
native SIGTERM и 49 PASS). Этот проход не является внешним независимым ревью:
его выполнил тот же агент отдельно от реализации.

Список находок зафиксирован пользователю и в docs/REVIEW.md ДО runtime-правок.
R01–R05 воспроизведены на свежих временных данных read-only review-скриптом;
R06–R10 установлены дальнейшей проверкой кода/полноты приёмки. Код задач/LLM
не исполнялся. Рутинные исправления выполнены в рамках запроса владельца
последовательно реализовать этапы. Разрешение на установку/live/Docker из этого
запроса не выводилось.

Исправлены:

- R01/R02: полное покрытие query-контекста вместо игнорирования нового правила;
  CSV product сравнивается точно, пустой ключ фильтра → UNKNOWN;
  search различает case-distinct сущности, неоднозначный alias → UNKNOWN.
- R03/R04: неверный объект normalized usage не возвращает резерв отправленного
  запроса; известный usage фиксируется до telemetry. Ошибка записи события
  сохраняет actual. Два concurrent unresolved события не дублируют глобальную сумму.
- R05: atomic publish writer через hardlink без overwrite, в том числе при двух
  конкурентных writer; temp cleanup сохранён. Вместо небезопасного exists+replace
  выбрана atomic no-clobber операция, что уточняет инженерное предложение спецификации.
- R06: один bounded binary read, stat/fstat регулярного файла, nonblocking/no-follow
  open; snapshot не перечитывает файл без лимита. FIFO отвергается до блокировки.
- R07/R08: call limit по фактическим вызовам adapter, а не кандидатам;
  existing_answer пропускается до solve без начисления баллов или resume-обещаний.
- R09: src/math_solver.py поддерживает явное условие arbitrary integer и
  целочисленные полиномы +,-,* без eval. F13 — два допустимых значения,
  F14 — точное сокращение x*0/x-x; неподдержанная семантика остаётся UNKNOWN.
- R10/F20: отсутствие credentials/SDK отключает только платный путь и сохраняет
  дешёвые решения; skip_reason отдельно от feasibility. Верифицирован случай
  math SOLVABLE/UNSOLVABLE и coding UNKNOWN при отсутствующих credentials.

Добавлены tests/test_review.py (13 тестов), поддержаны существующие тесты новых
boundaries. Конкурсные входы/тесты не менялись. В SIGTERM-тесте pause перенесён
на detector, поскольку math теперь получает точный answer непосредственно из
FeasibilityResult. Тест по-прежнему реально прерывает доверенный CLI между
первым сохранённым и вторым ещё не записанным ответом.

Commands:

```bash
python -m compileall -q run_agent.py src tests tools
python -m unittest discover -s tests -v > /tmp/techarena-stage5-tests.log 2>&1
python tools/evaluate_offline.py --corpus /tmp/techarena-stage4-corpus-parentgroups-2026 --out docs/evaluation/stage5-seed2026.json > /tmp/techarena-stage5-ablations.log
python -c "import importlib.util; print('openjiuwen:', 'present' if importlib.util.find_spec('openjiuwen') else 'NOT INSTALLED')"
git diff --check
git status --short
```

Повторные ablations: train full/no_gate — 10 ответов, reward=34; test — 4 ответа,
reward=13; no_deterministic=0. Во всех шести запусках false skips/reward=0,
LLM requests=actual=unresolved=0; cost metrics=null. Корпус не менялся, его labels
hash сохранён. Новый отчёт содержит runtime_sha256 для атрибуции результатов;
старый stage4 отчёт остаётся историческим результатом до review-правок.

### Completion audit по исходной цели

| Требование | Текущее свидетельство | Итог |
|---|---|---|
| Этап 1: аудит/fixtures/baseline/TaskSpec/writer/detector | Архив B1 и текущий runtime: 6/6 non-coding, reward=16; свежие inputs/архив неизменны | PASS offline |
| A01–A07 | test_baseline.py, test_offline.py, test_review.py: whitelist, scope, rename, атомарная публикация/конкуренция | PASS |
| F01–F12 | test_offline.py и новые CSV/query/alias контрпримеры review | PASS в поддержанных схемах |
| F13–F15 | polynomial two-world witness, cancellation, unsupported operator → UNKNOWN | PASS в явном math-классе |
| F16–F19 | полная/неполная coding спецификация, нет source/tests, падающие tests не дают UNSOLVABLE | PASS консервативный UNKNOWN |
| F20 | missing credentials сохраняет статусы и дешёвые ответы; бюджетные skip отдельно | PASS |
| Этап 2 / B01–B15 | integer ledger, concurrency/cancel/invalid/absent usage, prediction order, scheduler, call count | PASS fake/offline |
| SDK retries/usage настоящего прокси | конфиг max_retries=0 подготовлен, runtime SDK не установлен, live не запускался | NOT RUN |
| Этап 3 / C01 | подготовлен условный real Model.invoke test с fake transport, skipped | NOT RUN, нужен SDK |
| C02–C05 | fake patch/repair/compile/timeout/allowed paths/input immutability | PASS fake |
| C06 | root refusal/env/timeout/output/process-group configuration | PASS fake; реальное исполнение NOT RUN |
| C07 | opt-in live_smoke.py подготовлен, explicit cap и BUDGET | NOT RUN, нет разрешения/подтверждённой модели/usage |
| Этап 4 generator/evaluator/ablation | seeded parent-disjoint 28 задач, два мира, separate labels, 6 прогонов | PASS offline, не benchmark финала |
| D01–D04 | runtime-only COPY/allowlist/non-root/HOME статически; owner commands готовы | NOT RUN build/run/layers; pins pending |
| D05 | native signal integration | PASS native; Docker NOT RUN |
| D06 | README/PROGRESS/DOCKER_CHECKS/REVIEW отражают факты и ограничения | PASS |
| D07 | финальная публикация в предоставленных материалах отсутствует | NOT RUN/pending |
| Этап 5 review и исправления | docs/REVIEW.md, регрессионные контрпримеры R01–R10 | PASS внутренний review; внешнего нет |
| Нет Codex/API Codex в repo runtime | статический поиск runtime Python/COPY без совпадений/alternate-provider пути | PASS исходники; образ NOT RUN |
| Синтаксис/полная suite/whitespace | compileall exit 0; 63 discovered, 62 PASS + C01 skipped; diff check exit 0 | PASS |
| Запрещённые действия | установок, proxy calls, Docker, system changes, commit/push не было | Соблюдено |

Полное достижение цели НЕ доказано: обязательное подтверждение SDK и остальные
release gates отсутствуют. Реальная версия повторно проверена: NOT INSTALLED.
Блокирующее условие повторяется с этапа 2, затем на goal-turn этапа 3, этапа 4
и текущего review: ответ на запрос отдельной установки SDK так и не получен.
Теперь доступные offline-реализации, эксперименты, исправления и отчёты сделаны;
для следующего содержательного шага требуется ответ владельца об отдельном
окружении проекта. Никаких зависимостей из production .venv не заимствовалось.
Реальные API/Docker не запускаются без отдельного разрешения. Цель нельзя
помечать complete; после этого completion/blocked audit её статус — blocked
до разрешения внешних проверок. Это блокировка дальнейшей проверки, не отмена
исходной цели и не утверждение готовности финального конкурсного агента.

## Проверка контейнера и завершение последовательности этапов — 2026-11-08

Владелец прямо разрешил проверить контейнер и продолжить. Сначала проверен
git status; в Docker не было работающих/остановленных контейнеров. Найдены
hack:latest 1.36GB и локальный python:3.12.12-slim-bookworm. В одноразовом
read-only/network-none/non-root запуске hack:latest подтверждён SDK **0.1.19**,
путь /usr/local/lib/python3.12/site-packages/openjiuwen. Прежнее утверждение об
отсутствии SDK было ограничено native /usr/bin/python, а не контейнером.
Оно НЕ является основанием блокировать контейнерную проверку.

Граница доступа сохранена: host Python/production .venv/JiuwenSwarm/heartbeat,
конфиги/ключи/службы не читались и не менялись. Docker daemon использовался
штатным CLI по явному запросу владельца, без privileged mounts/socket bypass.
Проверочные контейнеры: UID10001, network none, cap-drop ALL, no-new-privileges,
read-only rootfs, tmpfs, CPU2/RAM4GB/pids128. Только свежие tasks writable;
для suite выбранные tests/tools/архивы монтировались read-only. Ключи/host HOME
не передавались, real API не запускался. Исходный hack:latest не перетегирован.

### Реальные контейнерные находки и исправления

R11: SDK import пытался создать /app/logs и C01 реально FAIL на read-only FS.
Изучены установленные logging/log_config.py и default/config_provider.py;
configure_log_config вызывается до импорта Model, путь /tmp, SDK file/payload
handlers отключены. C01 повторно PASS.

R12: Atomic writer оставлял tempfile mode0600. Host external grader реально
получил PermissionError на UID10001 answer. Добавлен fchmod0644 до publish;
повторный CLI + внешний grader 6/6 PASS. Task inputs не переписывались.

R13: Статическая .dockerignore-проверка не заметила, что !src/**/ повторно
включает pyc. Первый аудит docker image save FAIL (15 pyc в /app/src/__pycache__).
Allowlist сужен до текущих flat Python-модулей, явные pycache/pyc/pyo исключения.
Новый образ пересобран без сети на pinned dependency cache; полный слой-аудит PASS.
Первый FAIL сохранён в docs/evaluation/container-image-audit.json, итоговый PASS
отдельно в container-image-audit-final.json; отрицательная проверка не скрыта.

C01 test boundary также уточнён: Model.__init__ заменяет lower.invoke callback
wrapper, поэтому ссылка на AsyncMock сохраняется до оборачивания. Добавлены
тесты настоящего provider с fake HTTP transport и его timeout: usage 2000+500
включая reasoning100/cached1000 нормализуется в 700 выходных, retries=0,
max output передан, timeout вызывает ровно один transport attempt и unresolved.
Это реальный SDK execution path, НЕ настоящий Qwen/proxy.

### Закрепление сборки и измерения

constraints.txt содержит 160 наблюдённых exact pins, base digest взят из
локального RepoDigests. Обновлений версий не делалось. Первая последовательная
загрузка отменена (exit137 вследствие нашей остановки build-контейнера), чтобы
не рисковать лимитом 1000s при медленном канале. Удалён только этот собственный
остановленный промежуточный контейнер; глобальный prune не выполнялся.

tools/install_locked.py в отдельном dependency-stage скачивает четыре группы
точно закреплённых wheels с --no-deps, затем offline constrained install/pip check.
Final stage получает /usr/local и runtime, без helper/wheels/dev-материалов.
Cold build before-CLI timestamp: 17:56:47.799 UTC; первый новый слой 18:01:22.340;
итоговый locked image создан 18:06:51.321. Консервативный upper bound **604s**
включает approval delay; собственно интервал новых слоёв около **329s**.
Позднее время наблюдения завершённого процесса не подменяет время сборки.

Финальная очистка context пересобрана --network none на том же dependency cache.
Итоговый tag **techarena:validated**, ID
sha256:b4f7d86efecf4a844faeac0991f11d1b16392c6a433550b7e22ae03c7f58dad0.
`docker images ... --format` возвращает **1.36GB**, меньше 4GB. Raw inspect size
также сохранён в сводке без пересчёта в этот отображаемый показатель.

### Фактические команды/логи

```bash
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}'
docker build --pull=false --network default --memory 4g --cpu-period 100000 --cpu-quota 200000 -t techarena:locked .
docker build --pull=false --network none --memory 4g --cpu-period 100000 --cpu-quota 200000 -t techarena:validated .
docker images techarena:validated --format '{{.Repository}}:{{.Tag}} -> {{.Size}}'
docker image save techarena:validated | python tools/audit_image.py
python docs/codex/tools/prepare_samples.py --out /tmp/techarena-container-final-fixtures
python docs/codex/tools/grade_non_coding.py --tasks-dir /tmp/techarena-container-final-fixtures/tasks --labels /tmp/techarena-container-final-fixtures/evaluation/official_answers.json
python -m compileall -q run_agent.py src tests tools
python -m unittest discover -s tests -v
git diff --check
```

Полные docker run с read-only/network-none, mounts/limits, suite и smoke приведены
в docs/DOCKER_CHECKS.md. Реальные логи: /tmp/techarena-locked-build.log,
/tmp/techarena-final-build.log, /tmp/techarena-final-container-suite.log,
/tmp/techarena-final-container-cli.log, /tmp/techarena-final-docker-sigterm.log,
/tmp/techarena-final-native-suite.log. Необработанные env/ключи в них не выводились.

### Итоговый completion audit

| Критерий | Результат и авторитетное свидетельство |
|---|---|
| A01–A07 / исходные архивы и labels | PASS в полной container-suite; fresh copies, whitelist, baseline, task scope, input hashes |
| F01–F20 | PASS в поддержанных семантиках/консервативном UNKNOWN; новые review-контрпримеры включены |
| B01–B15 | PASS; реальные SDK-level normal/timeout paths также проверены с fake transport |
| C01 | PASS: настоящий Model.invoke + provider, source API/fingerprint в container-sdk-contract-final.json |
| C02–C05 | PASS: fake LLM и реальные non-root синтетические tests/patch/rollback/timeout; оригиналы неизменны |
| C06 | PASS в данном контейнере: actual subprocess env/output/time limits; не доказательство полной изоляции общего UID/proc |
| C07 | NOT RUN согласно условию задания: live proxy требует отдельного разрешения и модели/usage |
| D01 | PASS: pinned base/dependencies, pip check, 160 matches, build<=604s, docker images1.36GB |
| D02/D03 | PASS: final UID10001, read_only_rootfs=true, network none, fresh writable tasks, no runtime downloads |
| D04 | PASS по заявленному scope: 9 слоёв/57107 entries, known forbidden paths=[], в /app только runtime; не универсальная проверка содержимого на секреты |
| D05 | PASS: SIGTERM непосредственно techarena:validated, exit143, первый answer сохранён, частичных/temp нет |
| D06 | PASS: README/DOCKER_CHECKS/REVIEW/PROGRESS переписаны под реальные container results |
| D07 | NOT RUN/pending согласно acceptance: финальной публикации команды/модели/SDK в предоставленных материалах нет |
| Полная suite в итоговом образе | **71/71 PASS**, 0 skipped, 19.142s; no real proxy |
| Native suite | 71 discovered, 64 PASS + 7 intentional skipped (3 SDK/4 container execution), 1.590s; не заменяет container suite |
| Original sample reward | Внешний grader 6/6 non-coding, **16**; оба coding при BUDGET0 остаются без DONE, live repair NOT RUN |
| Совпадение образа с рабочим деревом | runtime_sha256=070897830c44cb80d72bc4a82d27d583a6f62e6a014c8f5ce4ed3ddede6b28d8, все160 pins совпали, SDK sources совпали с исходным проверенным контейнером |
| Codex в runtime | codex_executable_present=false, repo runtime без API Codex, build context/слои ограничены; U1 действует только для разработки |
| Синтаксис/whitespace | compileall и git diff --check exit0 |
| Git | commit/push не выполнялись; существующие изменения сохранены |
| Размер файлов репозитория | PASS: 544781 bytes по Git file list без .git/Git-ignored; только metadata, содержимое локальных конфигов не читалось |
| Завершение Docker-проверки | Работающих контейнеров после завершения нет; исходный hack:latest сохранён |

Машиночитаемая сводка: docs/evaluation/container-validation.json; fingerprints
runtime/SDK и final layer audit — отдельные container-*-final.json рядом.

Все пять заданных этапов выполнены последовательно, включая разрешённую теперь
контейнерную проверку и исправление найденных проблем. Прежний блокер C01 снят.
Условные NOT RUN C07/D07 оставлены в точном соответствии с формулировками заданий,
а не выданы за PASS: это отдельные внешние проверки перед сдачей, не обещание
проверки настоящего Qwen или скрытого набора. Никаких обходов запрета на live API,
самовольного выбора финальных правил, коммитов или push не было.

## Запрошенный live-прогон — разрешён, ожидает настройки прокси

Владелец разрешил LLM-прогон и после прерывания попросил продолжить. Разрешение
сохраняется, повторное согласование оплаты не запрашивалось. В текущей сессии
проверено ТОЛЬКО наличие (без значений) LLM_BASE_URL, LLM_API_KEY, LLM_MODEL,
BUDGET: все отсутствуют. Работающих Docker-контейнеров после прерывания не было.
Прерванная проверка среды вне sandbox не считается успешной и не доказывает
наличие credentials. .env, конфиги JiuwenSwarm/системы и ключи не читались.

Через вопрос запрошен конкретный способ предоставления настроек: окружение
или явно разрешённый файл внутри репозитория; сам ключ в чат не нужен.
До получения настроек реальных запросов **0**, live usage/reward не заявляются.

Подготовлены tools/live_evaluate.py и tools/live_worker.py для полного свежего
набора примеров (в том числе двух coding-задач). Global BudgetManager управляет
всеми запросами, BUDGET<=10000 output equivalents, максимум 4 попытки, fixed-model.
SDK-клиент исполняется в techarena:validated с proxy env, БЕЗ task-code execution.
Предложения проверяются в отдельных read-only/network-none/non-root workers,
без proxy env и без host HOME/Docker socket. В worker попадает только read-only
копия task workspace; внутри создаётся своя tmpfs-копия, tests/data контролируются
побайтно. Child SDK adapter также имеет per-request reservation в рамках global
controller reservation; фактические расходы агрегирует один controller ledger.
Это не добавляет дважды child usage к глобальному расходу.

Прогнозы/usage/events отделены от external labels; grader читает expected только
после solve. Разрешено менять только явно названный coding source на свежей копии.
До реального вызова требуются LLM_BASE_URL/LLM_API_KEY и явная схема reasoning.
Пример готовой команды (ещё НЕ live result):

```bash
python tools/live_evaluate.py --out /tmp/techarena-live-fresh --model qwen3.8-27b --reasoning-usage included --budget 10000 --max-calls 4
```

Схема included должна соответствовать прокси; параметр separate предусмотрен
для другого подтверждённого контракта. Сетевое имя model-контейнера задаётся
--network, по умолчанию bridge; verification всегда network none.

Проверено:

- compileall новых scripts — PASS.
- tests/test_live_evaluate.py — 3/3 PASS: отсутствие ключей останавливает запуск
  до Docker; модель требует global reserve; key не попадает в argv; verification
  не получает credentials и использует network none/read-only input.
- Реальный отдельный verification-worker в techarena:validated на синтетике:
  passed=true, тест также подтвердил отсутствие LLM_API_KEY в subprocess env.
- Preflight live_evaluate — exit2: Missing proxy environment; no paid calls sent.
  Каталог /tmp/techarena-live-pending не создавался и real proxy не вызывался.

Первоначальная threaded RPC-обвязка была отклонена после зависания теста на
thread→event-loop wakeup в sandbox. Собственные зависшие тестовые sessions
остановлены (exit130); serial bounded RPC прошёл 3 теста за 0.005s. Прогон
последовательный; per-worker timeout и cleanup ограничены, SIGTERM сохраняет
ledger и не запускает последующую external verification после прерывания.

Это подготовка запрошенного live-прогона, а не его завершение. Остаётся получить
разрешённые настройки прокси. Никаких токенов или секретных значений не выводилось.

## Разрешённый live-прогон — PASS, 2026-11-09

Владелец указал /root/llm.api.json и явно разрешил использовать его для тестовых
LLM-запросов. Это узкое разрешение на данный файл за пределами repo, не доступ
к другим конфигам /root/JiuwenSwarm. Прочитаны только названия полей и значения
двух нужных env-параметров для процесса контроллера; значения никогда не печатались.
Файл не копировался в Git, Docker context или контейнер. SDK-клиент получил
LLM_BASE_URL/LLM_API_KEY через env, без значений в argv. Внешние config/service/key
директории не читались. Исходный файл владельца не менялся и не удалялся.

Исполнена команда (логи без URL/key, показан только путь авторизованного файла):

```bash
python tools/live_evaluate.py --api-config /root/llm.api.json --out /tmp/techarena-live-20261109 --model qwen3.8-27b --reasoning-usage included --budget 10000 --max-calls 4
```

Общий cap=10000 output equivalents, дополнительно 5000 оставлены safety reserve
до наблюдения реального usage. Fixed-model qwen3.8-27b, максимум 4 попытки,
фактически **2**. Подготовлена новая копия восьми примеров без expected. До solve
записаны все первоначальные прогнозы. Бюджет/счётчики общие, без retries.

Режим проверки: trusted host-controller использует тот же core-код и ledger,
который совпадает с runtime образа. Реальный SDK Model.invoke выполняется внутри
techarena:validated. Клиентские контейнеры имеют сеть до прокси и proxy env,
но не исполняют код задач/модели. Каждая проверка предложенного Python выполняется
в отдельном non-root/network-none worker без proxy env, файла API, host HOME
и Docker socket. Worker получает только read-only task workspace, проверяет
свою tmpfs-копию и неизменность её tests/data. На host root код задач не исполнялся.
После завершения модельного solve external grader читает отделённые labels;
coding повторно проверены в независимых workers на уже сохранённых исходниках.

| Тип | Количество | Проверенных правильных | Reward |
|---|---:|---:|---:|
| math | 2 | 2 | 7 |
| search | 2 | 2 | 3 |
| data_analysis | 2 | 2 | 6 |
| coding | 2 | 2 | 4 |
| Всего | 8 | **8** | **20** |

Обе coding-задачи потребовали по одному запросу/патчу. Оригинальные tests до
модели падали; после правки модели прошли неизменённые tests, затем внешнюю
повторную проверку. Сохранены 8 ответов рядом с task.json; workspace/answer нет.
Доказано по SHA256: единственные изменённые inputs — два разрешённых mylib.py;
task.json, тесты, KB, CSV и исходный task-dir.zip неизменны.

| Запрос | Input | Output including reasoning | Reasoning subset | Cached | Cost units |
|---|---:|---:|---:|---:|---:|
| coding_0003 | 720 | 385 | 247 | 0 | 4570 |
| coding_0007 | 617 | 215 | 108 | 0 | 2767 |
| Всего | **1337** | **600** | **355** | **0** | **7337** |

Учёт по принятой included-схеме OpenAI-compatible SDK: input/10 + output =
133.7 + 600 = **733.7** приведённого выходного токена. Reasoning355 уже входит
в output600 и не прибавляется повторно. Unresolved=0, active reservations=0,
worker errors=[], ledger не закрыт. Это фактические возвращённые SDK счётчики,
не оценка денежной цены и не данные об остатке server-side quota.

Отчёт без секретов: docs/evaluation/live-samples-20261109.json; полные whitelist
события/прогнозы/usage: docs/evaluation/live-events-20261109.jsonl.
Контроллер сохранил исходный отчёт в /tmp/techarena-live-20261109/live_summary.json,
сами исправленные рабочие копии доступны в /tmp/techarena-live-20261109/tasks/.
Native regression после изменений helper: **74 discovered, 67 PASS, 7 intentional
skipped** (SDK и isolated-container-only cases), /tmp/techarena-post-live-native-tests.log.
compileall и diff --check PASS. Все одноразовые Docker workers завершились;
docker ps после прогона пуст. Оригинальный validated image не менялся.

C07 теперь **PASS для этого разрешённого sample-прогона**. Это не скрытый checker,
не 100 финальных задач и не доказательство окончательной single-container команды
организаторов. D07 и политика credentials для single-container live coding
остаются открытыми; разделённый режим использован намеренно для данного теста.
Тесты/метрики сборки предыдущего контейнера не заменены этим результатом:
71/71 контейнерная suite остаётся отдельным предыдущим подтверждением, новая
обвязка проверена 3 unit-тестами и фактическим live-прогоном. Push/commit не было.


## 2026-11-09 — выбор модели по сложности

Реализованы src/model_routing.py, выбор модели в общем OJAdapter, привязка
политики к задаче в ModelSolver и CLI run_agent.py. Fixed остаётся default;
complexity выбирает настраиваемые easy/hard профили без классифицирующего
LLM-запроса. Признаки: объём контекста, операции инструкции, AST/ветвления/
вложенность исходника. Нет task_id/reward/expected/числа строк. Неполный разбор
даёт hard, а не UNSOLVABLE. После провала coding-проверки следующая разрешённая
попытка переключается на hard. Единые BudgetManager и max-calls сохраняются;
API-ошибки/неизвестный usage не разрешают скрытые платные повторы.
События model_selected содержат причину/score/признаки/version. Политика
complexity-v1-uncalibrated — эвристика, превосходство моделей не установлено.

Добавлены 11 regression-тестов tests/test_model_routing.py, поддержка профилей
в tools/live_evaluate.py, отдельный tools/model_routing_smoke.py. README и
OPEN_QUESTIONS описывают opt-in и оставшийся конфликт финального регламента.

Проверки:
- python -m compileall -q run_agent.py src tests tools — PASS.
- python -m unittest discover -s tests -p test_model_routing.py -v — 11 PASS.
- python -m unittest discover -s tests -v — 85 discovered, 78 PASS, 7 intentional
  skipped (SDK/container-only); /tmp/techarena-model-routing-tests.log.
- docker build --pull=false --network none --memory 4g --cpu-period 100000
  --cpu-quota 200000 -t techarena:routing . — PASS; лог
  /tmp/techarena-model-routing-build.log. Предыдущий validated не заменён.
- Контейнер techarena:routing, unittest discover -s /app/tests -v: **85/85 PASS**,
  10.668s, без skip; read-only, network none, UID10001, cap-drop ALL, 2 CPU/4GiB,
  pids128, tmpfs, выбранные read-only mounts tests/tools/архивов/сборочных файлов.
  /tmp/techarena-routing-container-tests.log.
- python tools/model_routing_smoke.py --api-config /root/llm.api.json
  --out /tmp/techarena-routing-live-20261109 --image techarena:routing — PASS,
  ровно 2 реальных запроса: simple(score0) qwen3.8-27b; complex(score4)
  qwen3.6-35b-a3b. Оба ответа проверены внешними labels, которых нет в runtime
  task.json. Input256, output505 (reported reasoning37 включён), actual5306
  units = **530.6 output-equivalent tokens**; unresolved/reserved=0.
  Это smoke маршрутизации/связности, не калибровка качества или стоимости.

Whitelist отчёты: docs/evaluation/model-routing-live-20261109.json и
model-routing-events-20261109.jsonl. Секреты из явно разрешённого конфига не
копировались в repo/image/log; код задач на root-host не исполнялся. SDK-запросы
проходили через общий ledger и SDK-only workers. Коммитов и push нет.


## 2026-11-09 — подготовка коммита рабочей системы

По запросу владельца подготовлен единый локальный коммит текущей системы:
реализация харнесса, pinned Docker, тесты, инструменты и отчёты проверок.
.local/ и llm.api.json исключены через .gitignore. Проверка новых исходников,
тестов, инструментов и evaluation-отчётов на шаблоны секретов совпадений не дала.
Повторно: compileall PASS; unittest discover — 85 tests, 78 PASS/7 intentional
skipped на host (/tmp/techarena-precommit-tests.log); diff --check PASS.
Контейнерный результат 85/85 и API smoke выше остаются отдельными фактическими
проверками. Новых платных запросов при подготовке коммита не было. Push не выполняется.
