# Проверки итогового контейнера — offline PASS

После явного разрешения владельца Docker-проверки выполнены. Ранее отмеченный
блокер отсутствия SDK в native Python снят: в исходном hack:latest и итоговом
контейнере установлен openJiuwen 0.1.19. Ничего не устанавливалось в host Python
или production JiuwenSwarm. Старый hack:latest сохранён.

Итоговый образ: **techarena:validated**, ID
`sha256:b4f7d86efecf4a844faeac0991f11d1b16392c6a433550b7e22ae03c7f58dad0`.
Размер по docker images **1.36GB**, UID/GID 10001:10001, HOME=/tmp.
[Полная сводка](evaluation/container-validation.json).

| Проверка | Результат |
|---|---|
| Закреплённая сборка / pip check / 160 pins | PASS; холодная сборка <=604s с учётом approval delay, интервал новых слоёв около 329s |
| Read-only /app, tmpfs, writable fresh tasks | PASS |
| Сеть runtime --network none | PASS; proxy env не передавался |
| Полная suite в финальном контейнере | 71/71 PASS, без пропусков |
| Настоящий oJ Model/provider + fake HTTP transport | PASS; counters/max output/retries/timeout проверены |
| Реальные coding-подпроцессы на синтетике | PASS; UID10001, чистое env, timeout/output, два патча/commit |
| Свежие примеры и внешний grader | 6/6 non-coding, reward=16; input hashes неизменны |
| Все слои, known forbidden paths и /app allowlist | PASS, 9 слоёв; не универсальное сканирование секретного содержимого |
| SIGTERM непосредственно финальному контейнеру | PASS, exit143, один целый answer сохранён, частичных нет |
| C07 настоящий прокси | NOT RUN, требуется отдельное разрешение/модель/usage |
| D07 финальный контракт организаторов | NOT RUN/pending по доступным материалам |

## Повторная сборка и smoke

Команды для этого проекта, не финальная команда организаторов. При новой сборке
зависимости скачиваются только в build-stage: четыре параллельные exact-wheel
группы, затем offline constrained install и pip check. В runtime нет build helper
или wheelhouse. На валидированном кеше пересборка проверена с --network none.

```bash
docker build --memory 4g --cpu-period 100000 --cpu-quota 200000 -t techarena:validated .
docker images techarena:validated --format '{{.Repository}}:{{.Tag}} -> {{.Size}}'
python docs/codex/tools/prepare_samples.py --out /tmp/techarena-owner-fresh
python -c "from pathlib import Path; p=Path('/tmp/techarena-owner-fresh/tasks'); [d.chmod(d.stat().st_mode | 0o222) for d in [p, *p.rglob('*')] if d.is_dir()]"
docker run --rm --read-only --network none --tmpfs /tmp:rw,size=512m \
  --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 4g --pids-limit 128 \
  -e HOME=/tmp -e BUDGET=0 -v /tmp/techarena-owner-fresh/tasks:/data/tasks:rw \
  techarena:validated --tasks-dir /data/tasks --max-llm-calls 0 --isolated-coding
python docs/codex/tools/grade_non_coding.py --tasks-dir /tmp/techarena-owner-fresh/tasks --labels /tmp/techarena-owner-fresh/evaluation/official_answers.json
```

Использовать новый путь fixtures при каждом прогоне. Права меняются только
у свежих временных директорий. Labels не монтируются в runtime. Answer 0644
доступен внешнему grader другого UID. В текущих исходных coding-примерах tests
падают; при BUDGET=0 они не ремонтируются и DONE не записывается.

## Полная offline suite

Только validation-контейнер получает read-only тесты, tools и исходные архивы.
Они не входят в образ. Ни host HOME, ни Docker socket, ни реальные ключи не
монтируются. TECHARENA_CONTAINER_TESTS=1 явно разрешает исполнение синтетических
coding-программ; в native root-тестах они пропускаются.

```bash
docker run --rm --read-only --network none --tmpfs /tmp:rw,size=512m \
  --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 4g --pids-limit 128 \
  -e HOME=/tmp -e BUDGET=0 -e TECHARENA_CONTAINER_TESTS=1 \
  -v "$PWD/tests:/app/tests:ro" -v "$PWD/tools:/app/tools:ro" \
  -v "$PWD/docs/codex/tools:/app/docs/codex/tools:ro" \
  -v "$PWD/docs/codex/materials/original/task-dir.zip:/app/docs/codex/materials/original/task-dir.zip:ro" \
  -v "$PWD/docs/codex/materials/baseline/techarena-harness-starter.zip:/app/docs/codex/materials/baseline/techarena-harness-starter.zip:ro" \
  -v "$PWD/Dockerfile:/app/Dockerfile:ro" -v "$PWD/.dockerignore:/app/.dockerignore:ro" \
  --entrypoint python techarena:validated -m unittest discover -s /app/tests -v
```

Настоящий SDK использует fake transport: настоящего Qwen/network calls здесь нет.
Реальный coding-runner выполняет синтетические тесты без секретов и сети; этого
недостаточно, чтобы объявить доступ к parent /proc/env безопасным при live coding
одного UID. Для такого режима остаётся нужна внешняя политика изоляции credentials.

## Аудит слоёв

```bash
docker image save techarena:validated | python tools/audit_image.py
```

Проверяются имена файлов во всех слоях без извлечения/печати содержимого:
known credential/artifact paths и runtime-only /app. Первоначальный аудит выявил
лишние pyc, после сужения allowlist финальный прошёл. Статический allowlist сам
по себе не заменяет этот реальный аудит образа.

Логи выполненной проверки: /tmp/techarena-final-build.log,
/tmp/techarena-final-container-suite.log, /tmp/techarena-final-container-cli.log,
/tmp/techarena-final-docker-sigterm.log. Машиночитаемые результаты сохранены
в docs/evaluation/container-*.json. C07/D07 не помечены PASS.
