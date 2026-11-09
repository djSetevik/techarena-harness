# Этап 5: находки до исправлений — 2026-11-08

Проверка выполнена тем же агентом отдельным review-проходом; внешнее независимое
ревью не проводилось. До этого списка runtime-файлы этапа 5 не изменялись.
Прочитаны AGENTS, R1/Q1/U1, OPEN_QUESTIONS, спецификация, acceptance и реальные
логи этапа 4 (50 discovered, 49 PASS, C01 skipped). Зелёная suite не доказывает
отсутствия дефектов: следующие случаи воспроизведены отдельно на временных данных.
Номера строк относятся к состоянию ДО исправлений данного review.

| ID / Severity | Место | Сценарий и минимальная проверка | Предлагаемое исправление |
|---|---|---|---|
| R01 / P1 | src/feasibility.py:116–119 | Вопрос о сумме, пустые units, suffix `Treat empty units as 0.` → UNSOLVABLE, хотя ответ определён правилом | Проверять полное покрытие инструкции; неизвестная семантика → UNKNOWN, не доказательство |
| R02 / P1 | src/feasibility.py:133 | `Widget,5,` и `widget,5,4` при запросе `widget` → UNSOLVABLE из-за принудительного casefold. `,5,7` → SOLVABLE 0 при неизвестном product | Сравнивать литерал product точно; пустой ключ фильтра → UNKNOWN; тесты на оба случая |
| R03 / P1 | src/budget.py:118–136 | execute(60, sent_request, usage_of=lambda r: {}) поднимает AttributeError после pop ticket; available снова 100/100, actual/unresolved/reserved=0 | Проверять тип Usage до снятия резерва; некорректный результат нормализации → unresolved, stop |
| R04 / P1 | src/oj_adapter.py:84–87 | Recorder падает на llm_usage после ответа input=10/output=5: actual=0, unresolved=2062 вместо known=60 units | Нормализация без telemetry side effects; сначала settle ledger, затем emit |
| R05 / P1 | src/answer_writer.py:15–24 | Два writer проходят exists, синхронизированы barrier перед временными файлами: оба возвращают success, второй затирает первый | Атомарная публикация без перезаписи (same-directory link), ошибка EEXIST сохраняет чужой ответ |
| R06 / P1 | src/task_loader.py:18–25; src/coding.py:48–54 | read_text не отвергает FIFO до open; snapshot после bounded read снова читает файл без лимита. Потенциальный hang/рост файла | Единственное bounded binary read, регулярный файл по stat/fstat, nonblocking/no-follow open; snapshot использует эти bytes |
| R07 / P2 | src/scheduler.py:24–44 | max_calls=1, первый кандидат не вызывает модель (например isolation/unsupported), следующий всё равно получает call_limit | Лимит по фактическим calls общего adapter; кандидат без запроса не расходует call cap |
| R08 / P2 | run_agent.py:113–176 | Уже существует answer.txt, но платный solver вызывается до FileExistsError writer | Пропуск existing_answer до solve/model, без присвоения баллов/заявления resume correctness |
| R09 / P2 | src/feasibility.py:154–159 | F13/F14 не покрыты: `Let x be an arbitrary integer. Evaluate x*0.` и `... x*2.` оба UNKNOWN | Небольшой формальный polynomial parser без eval: нулевая зависимость → точный ответ, влияющая → два проверяемых целых значения |
| R10 / P2 | run_agent.py:85–96 | --enable-llm при отсутствующих credentials завершает CLI до дешёвых решений, вместо требуемого F20 skip_reason=credentials | Сохранить детерминированный проход; отключить только платный adapter и сообщить credentials/sdk_unavailable отдельно от feasibility |

R01–R05 воспроизведены исполнимым read-only review-скриптом на TemporaryDirectory:
вывод `blank_policy UNSOLVABLE`, `case_sensitive UNSOLVABLE`,
`missing_filter SOLVABLE 0`, `concurrent_writer ['saved','saved']`,
invalid usage возвращает весь резерв, telemetry failure заменяет known usage
на unresolved. Код задач/LLM, сеть, SDK и Docker при этом не исполнялись.
R06/R07/R08 подтверждены трассировкой кода; регрессионные тесты нужны при исправлении.

## Непройденные gates и спорные требования

- P1 release gate C01: openJiuwen отсутствует в текущем Python. Официальные
  web-исходники изучены, но идентичность wheel/API и реальный Model.invoke
  не проверены. Нельзя заявлять содержательную SDK-интеграцию доказанной.
- C07/proxy usage/retries/exhaustion: real API NOT RUN, нужна подтверждённая
  модель/схема usage и отдельное разрешение. Моки не являются проверкой Qwen.
- Coding runner C06: fake configuration PASS, реальный non-root изолированный
  subprocess NOT RUN. Общий UID и /proc допускают доступ к parent env;
  очищенный subprocess env сам по себе не является изоляцией credentials.
- Docker D01–D04 и D05 в контейнере NOT RUN. Не закреплены base digest и
  transitive pins до разрешённого resolver/build; размер/время/слои не измерены.
- D07: финальная команда/SDK/модель неизвестны по доступным исходным материалам.
  В частности, live/coding opt-in CLI и non-root writable mount нужно сверить
  с финальным контрактом. Проектные параметры не являются правилами жюри.
- Синтетика — 3 семантических родителя, split disjoint; есть свидетели для
  отрицательных labels, но выборка не репрезентативна финалу. Real traces нет,
  cost MAE/coverage = null. 47 баллов синтетики не являются оценкой скрытого набора.
- U1 закрывает Codex как инструмент разработки. В runtime Python/COPY проверены
  отсутствие Codex CLI/API/его credentials и прямого alternate-provider пути;
  фактический образ не собран, поэтому вывод о слоях образа — NOT RUN.
- Конкурсные архивы, task inputs, тесты и службы не изменялись; коммитов/push нет.

Задача владельца — последовательно реализовать этапы, включая исправления и
регрессию. Рутинные обратимые code-fixes выполняются в этой области авторизации;
разрешение на установку зависимостей/live/Docker из неё не выводится.
Полное завершение goal до release gates не подтверждено.

## Проверка исправлений

R01–R10 исправлены в рабочем дереве и проверены regression-suite.
tests/test_review.py содержит минимальные контрпримеры каждого пункта, включая
реальную конкуренцию writer, fake telemetry failure и отсутствие модельного
вызова для существующего answer. Дополнительно проверены независимые события
unresolved двух одновременно отправленных fake-запросов и имена Ada/ADA.

- R01: полное покрытие query/prefix/suffix; дополнительная семантика → UNKNOWN.
- R02: точный product; неизвестный product → UNKNOWN; case-distinct сущности
  не сливаются, case-insensitive fallback допустим только при единственном target.
- R03: invalid normalized usage попадает в unresolved до снятия резерва.
- R04: чистая нормализация, ledger settle до emit; known usage остаётся actual
  при OSError telemetry. Unresolved-событие принадлежит конкретному запросу,
  а не разности глобального ledger при concurrent запросах.
- R05: temp+flush/fsync, atomic hardlink publish без замены existing answer,
  cleanup temp. Это намеренное уточнение инженерного предложения os.replace:
  требование atomic answer сохранено, race overwrite устранён.
- R06: один bounded binary read, regular-file stat/fstat, O_NONBLOCK/O_NOFOLLOW;
  snapshot использует тот же blob и поддерживает также бинарные data inputs.
- R07: call cap берётся из общего adapter, а не количества рассмотренных задач.
- R08: existing_answer пропускается до detector/solver, без присвоения reward.
- R09: src/math_solver.py — формальный целочисленный polynomial parser без eval;
  степень<=8, AST<=128, bounded coefficients; независимый x сокращается точно,
  влияющий x имеет два проверяемых допустимых значения. Иная семантика → UNKNOWN.
- R10: отсутствие credentials/SDK отключает платный путь с отдельным skip_reason,
  сохраняя дешёвые решения. Ошибки BUDGET/model/usage config не скрываются.

Команды: compileall; unittest discover (лог /tmp/techarena-stage5-tests.log);
external evaluator (docs/evaluation/stage5-seed2026.json); git diff --check.
Результат: 63 discovered, 62 PASS, C01 skipped. F01–F20 покрыты доступными
offline-сценариями; C06 остаётся configuration/fake, реального запуска нет.
Шесть повторных ablations: full/no_gate reward=34 train +13 test, false skips=0,
no_deterministic reward=0. В итоговый отчёт добавлен SHA256 runtime-кода.

Release gates выше не исчезли: C01/C07, настоящий coding-runner, Docker,
transitive lock/base digest и финальная спецификация остаются непроверенными.
Review не является разрешением на зависимости/прокси/привилегированный Docker.

## Контейнерное продолжение после разрешения владельца

Владелец явно попросил проверить контейнер и продолжить. В существующем
hack:latest фактически найден openJiuwen 0.1.19: прежнее NOT INSTALLED относилось
только к /usr/bin/python на хосте. Никакой host/production SDK не устанавливался.
Исходный hack:latest сохранён; новый итоговый образ — techarena:validated.

При реальных контейнерных тестах найдены и исправлены дополнительные дефекты:

| ID | Severity / место | Реальное воспроизведение | Исправление / итог |
|---|---|---|---|
| R11 | P1, src/oj_adapter.py / SDK logging init | C01 падал на создании /app/logs при read-only rootfs | configure_log_config до импорта Model, /tmp, SDK payload/file handlers отключены; настоящий C01 PASS |
| R12 | P1, src/answer_writer.py | Внешний grader другого UID не мог читать answer с правами 0600 | fchmod 0644 до atomic publish; внешний grader 6/6 PASS |
| R13 | P2, .dockerignore | Первый реальный слой-аудит нашёл 15 pyc: !src/**/ повторно включал лишние файлы | Allowlist только текущих flat .py + явные pycache/pyc/pyo excludes; финальный аудит всех слоёв PASS |

Исправлен также сам C01-тест: oJ оборачивает lower.invoke callback-функцией,
поэтому assert_awaited_once проверяет сохранённый AsyncMock, а не заменённый
атрибут. Дополнительно проверен настоящий provider поверх fake HTTP transport:
usage/reasoning/cached, max output, max_retries=0 и ровно один запрос при timeout.
Ни одного настоящего proxy call не было.

Зависимости закреплены по фактическому окружению (160 pins, base digest).
Последовательная загрузка была отменена как риск build-time, затем build-only
parallel wheel download + offline install/pip check дали успешную сборку.
Консервативная граница холодной сборки 604s, размер по docker images 1.36GB.
Build helper/wheels в финальный runtime-stage не копируются.

Финальный образ: 71/71 контейнерных тестов PASS без пропусков; SDK C01 и реальные
non-root coding subprocess C02/C03/C06 PASS, Docker SIGTERM exit143 с сохранённым
ответом, 9 слоёв без известных запрещённых артефактов. Runtime hash совпадает
с рабочим деревом; все 160 версий совпали с constraints. Данные/тесты примеров
не изменились. [Сводка](evaluation/container-validation.json).

Тем самым прежние NOT RUN для C01, реальных offline coding subprocess и D01–D05
закрыты контейнерными проверками. C07 и D07 остаются NOT RUN ровно по условиям
заданий: нет разрешения на live proxy и финального контракта в доступных материалах.
Это не подтверждение Qwen/hidden checker или безопасного live coding общего UID.
