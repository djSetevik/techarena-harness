# TechArena 2026 — конкурсный харнесс

Конкурсный Python-харнесс на openJiuwen: дешёвый анализ → доказательная проверка
выполнимости → детерминированные ответы → ограниченные модельные попытки через
общий BudgetManager. Это отдельный проект, не установка JiuwenSwarm/heartbeat.

## Проверенный контейнер

`techarena:validated`, openJiuwen **0.1.19**, Python **3.12.12**, UID/GID **10001**.
Размер по `docker images` — **1.36 GB**. Холодная закреплённая сборка завершилась
в пределах 1000s (консервативная верхняя граница 604s, включая ожидание approval).
Base digest и 160 версий пакетов закреплены; `pip check` и сверка всех pins PASS.

**71/71 тестов PASS без пропусков** в read-only контейнере с `--network none`.
Проверены настоящий oJ Model.invoke и provider/usage/retries с fake HTTP transport,
реальные coding-подпроцессы на синтетике, timeout, ограничение вывода, очищенное
окружение и SIGTERM контейнера. На свежих видимых задачах внешний grader подтвердил
**6/6 non-coding ответов, 16 баллов**; все входные байты сохранились.
Это не проверка скрытого набора. Позднее выполнен разрешённый live-прогон
qwen3.8-27b: **8/8 примеров, 20 баллов**, включая обе coding-задачи.
Два запроса, 1337 input + 600 output (включая reasoning355), расход **733.7**
выходного эквивалента по input/10+output. [Отчёт](docs/evaluation/live-samples-20261109.json).

[Сводка](docs/evaluation/container-validation.json),
[SDK API/fingerprint](docs/evaluation/container-sdk-contract-final.json),
[аудит слоёв](docs/evaluation/container-image-audit-final.json).
В слоях не обнаружены известные запрещённые пути/артефакты; это не универсальное
сканирование содержимого на секреты. В /app только runtime и зависимости;
тесты/dev-материалы подключались read-only исключительно в validation-контейнеры.

## Сборка и offline-запуск

```bash
docker build -t techarena:validated .
python docs/codex/tools/prepare_samples.py --out /tmp/techarena-fresh
python -c "from pathlib import Path; p=Path('/tmp/techarena-fresh/tasks'); [d.chmod(d.stat().st_mode | 0o222) for d in [p, *p.rglob('*')] if d.is_dir()]"
docker run --rm --read-only --network none --tmpfs /tmp:rw,size=512m \
  --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 4g --pids-limit 128 \
  -e HOME=/tmp -e BUDGET=0 -v /tmp/techarena-fresh/tasks:/data/tasks:rw \
  techarena:validated --tasks-dir /data/tasks --max-llm-calls 0 --isolated-coding
python docs/codex/tools/grade_non_coding.py --tasks-dir /tmp/techarena-fresh/tasks --labels /tmp/techarena-fresh/evaluation/official_answers.json
```

Каждый повтор — новая копия fixtures. Разрешения в примере меняются только
у свежих временных директорий, чтобы UID 10001 мог писать ответы/источники.
Labels остаются снаружи runtime. Без --isolated-coding никакие task-программы
не запускаются. При BUDGET=0 coding проверяет только оригинал, без ремонта моделью.
В Dockerfile четыре build-only процесса скачивают точные wheels без зависимостей,
потом выполняется offline constrained install и pip check. Build helper/wheels
не переносятся в runtime-stage. Runtime ничего не скачивает.

## Контракт и стратегия

TaskSpec содержит whitelist полей без expected; task_id используется для логов,
не как признак стоимости/ответа. Факты и контекст разных задач изолированы.
Answer атомарно публикуется рядом с task.json с правами 0644; два writer не могут
перезаписать друг друга. Существующий answer сохраняется без новой платной попытки
и без присвоения его reward; это не механизм верифицированного resume.

Feasibility: SOLVABLE / UNSOLVABLE / UNKNOWN. Последний остаётся кандидатом
планировщика. UNSOLVABLE имеет проверяемое свидетельство в поддержанной семантике.
Search читает весь ограниченный task scope: markdown, scalar facts, aliases,
цепочки и дубли. Доказательство отсутствия допустимо только при явном
`Closed KB schema v1` (наш синтетический контракт, не правило организаторов).
Иная проза/приоритеты/неполный scope → UNKNOWN. Разные работодатели могут вести
к одному городу: конфликт промежуточного ребра сам по себе не UNSOLVABLE.

CSV: сумма целых units по точному product и диапазону month. Пустой фильтр даёт 0;
пустые units релевантной строки без правила восстановления допускают разные суммы.
Пустой product, неизвестное дополнительное правило/формула/dialect → UNKNOWN.
Math: полностью разобранные warehouse-операции и явный класс
`Let x be an arbitrary integer. Evaluate <expression>.` с полиномами +,-,*.
Зависимость x*0 сокращается; для x*2 строятся два допустимых ответа. Нераспознанная
операция не приводит к частичному ответу. Ограничения: 2 MiB, 256 entries, глубина 8;
для полиномов AST<=128, степень<=8. Это ограниченные парсеры, не универсальный анализ.

BudgetManager считает input+10*output в целых десятых выходного токена; cached
input не вычитается, reasoning учитывается один раз по явной схеме. Перед каждой
попыткой резерв, при timeout/неизвестном usage — unresolved и остановка платных
попыток. Известный usage фиксируется до разбора ответа и telemetry. Прогнозы
неизменны, записываются до solve в JSONL stdout или новый --metrics-path вне задач.
Estimator — некалиброванная эвристика типа/размера инструкции. Планировщик использует
reward/cost; reward/expected/task_id не входят в cost features. Skipped не обучает cost=0.

## Модельный и coding-путь

Единственная граница — OJAdapter → BudgetManager → oJ Model.invoke.
Для будущего live нужны --enable-llm, явный --model qwen3.8-27b либо qwen3.6-35b-a3b,
--reasoning-usage included|separate по подтверждённой схеме прокси,
BUDGET и LLM_BASE_URL/LLM_API_KEY. --max-llm-calls общий, включая ремонты.
Отсутствие credentials отключает только платный путь; дешёвые решения сохраняются.
SDK logging настроен до импорта Model: без file handlers/сырых prompts/config,
путь /tmp, что проверено при read-only /app. Ключи в образ не помещаются.
`tools/live_smoke.py` подготовлен отдельно. Разрешённый прогон всех примеров
выполнен через `tools/live_evaluate.py`: общий controller ledger на host,
SDK-only контейнеры с ключом и отдельные network-none verification workers
без ключа. Host не исполняет task/model code, labels читает только внешний grader.
Это не проверка окончательной команды организаторов или single-container
профиля live coding с общим UID. Конфиг подключается только явно через
--api-config, не копируется в repo/image и не передаётся verification workers.

Coding поддерживает исходник, явно названный `Fix the bugs in module.py`, и entry
из `python3 checks.py`. До оплаты проверяется оригинал. Предложения проверяются
на свежих копиях, tests/data фиксируются побайтно; только после успеха атомарно
заменяется разрешённый исходник и сохраняется DONE. До двух ремонтов, без скрытых
ретраев. Timeout/compile error/mutation не даёт ложного DONE и не меняет оригинал.

Runner требует явно изолированную non-root среду и не является sandbox.
Очищенное subprocess env и лимиты не скрывают parent credentials от общего UID
или /proc: для реального live coding нужна внешняя политика изоляции. Проверенные
coding-контейнеры были без сети и настоящих ключей. На root-хосте task code не исполнялся.

## Выбор модели по сложности

По умолчанию сохранён `--model-mode fixed` с явным `--model`.
Автоматический выбор включается параметрами (в дополнение к обычным путям,
`--enable-llm`, бюджету, credentials и `--reasoning-usage included|separate`):

```text
--model-mode complexity --easy-model qwen3.8-27b --hard-model qwen3.6-35b-a3b --routing-threshold 4
```

В этом режиме не передавайте `--model` или `LLM_MODEL`: используются два профиля.
Сложность оценивается без LLM по объёму инструкции/контекста, операциям в запросе,
структуре AST и вложенности coding-исходника. При score>=4 либо неполном разборе
выбирается hard-профиль, иначе easy. После неудачной проверки coding-патча
следующая разрешённая попытка использует hard-профиль. Все модели делят один
BudgetManager и общий лимит вызовов. Ошибки API не запускают скрытые ретраи.
Событие `model_selected` сохраняет признаки, score, модель и причину выбора.

Профили и порог настраиваются; названия easy/hard обозначают роли, а качество
моделей и порог пока не откалиброваны. task_id, reward, expected и число строк
не являются признаками. Конфликт финальных правил о фиксированной модели
сохранён в OPEN_QUESTIONS; маршрутизация включается явно.

Образ `techarena:routing`: **85/85 контейнерных тестов PASS**. Два разрешённых
реальных API-запроса подтвердили выбор обеих моделей и правильные ответы на
двух пробах; расход **530.6 приведённого выходного токена**. Это проверка
работоспособности, а не сравнительный benchmark качества.
[Отчёт](docs/evaluation/model-routing-live-20261109.json).

## Воспроизводимая оценка и ограничения

```bash
python -m compileall -q run_agent.py src tests tools
python -m unittest discover -s tests -v
python tools/generate_synthetic.py --out /tmp/techarena-synthetic-fresh --seed 2026 --instances 2
python tools/evaluate_offline.py --corpus /tmp/techarena-synthetic-fresh --out /tmp/techarena-evaluation-fresh.json
```

Native SDK/coding tests пропускаются, если нет SDK или явно разрешённого non-root
контейнера. Это не отсутствие SDK в Docker: контейнерная suite прошла полностью.
Синтетика: 28 задач, separate labels/provenance/two-world witnesses, split по трём
семантическим родителям, включая все их aliases/prose/formula-мутации. Tiny quality
corpus, не репрезентативный финальный benchmark; обучения/real traces нет.
Full/no_gate: 14 правильных ответов, reward=47; no_deterministic: 0. Четыре
положительных UNKNOWN без ответа; false UNSOLVABLE/false skips=0. При BUDGET=0
все вызовы/actual/unresolved=0; MAE/underprediction/coverage=null. Это не доказательство
экономии live-токенов. [Исторический отчёт](docs/evaluation/stage5-seed2026.json).

[PROGRESS](docs/PROGRESS.md) — команды/проверки, [REVIEW](docs/REVIEW.md) — находки,
[DOCKER_CHECKS](docs/DOCKER_CHECKS.md) — повторная проверка,
[OPEN_QUESTIONS](docs/OPEN_QUESTIONS.md) — конфликты модели/SDK/финального контракта.
C07 выполнен с разрешения владельца в описанном разделённом режиме; D07 остаётся
pending: окончательной спецификации организаторов в доступных материалах нет. Финальная
команда, совместимость opt-in параметров и writable UID требуют сверки перед сдачей.
Коммитов и push не выполнялось. Codex используется только для разработки по U1,
в runtime его CLI/API нет.
