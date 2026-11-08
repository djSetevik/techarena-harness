# TechArena 2026: пакет постановки задачи для Codex CLI

**Что это:** инструкция, техническое задание, исходные материалы и вспомогательные
скрипты проверки. **Что это не:** готовый окончательный харнесс.
Код конкурса нужно доработать в существующем Git. Редакция пакета: v2.

## 0. Codex разрешён для разработки
По уточнению владельца проекта после телефонного согласования с организаторами
Codex разрешён сугубо для разработки системы. Этот вопрос закрыт; повторно
запрашивать разрешение на написание, отладку и проверку кода через Codex не нужно.
Источник U1: `materials/clarifications/codex-development-authorization.ru.md`.

Разделяйте два режима:
- Разработка: Codex помогает создать и проверить код конкурсного харнесса.
- Оцениваемый запуск: openJiuwen, разрешённые модели и прокси организаторов;
  без Codex, его учётных данных и вызовов его API в финальном контейнере.

Не направляйте сам Codex в конкурсный прокси: это отдельная от разрешения
интеграция, совместимость не проверена, и можно потратить конкурсный бюджет.
Остальные вопросы о модели финального прогона, версии SDK и запуске сохраняются.
Исходные R1/Q1 не изменены; U1 хранится отдельно от регламента.

## 1. Что внутри
- AGENTS.md — постоянные правила для агента в корне Git-репозитория.
- START_PROMPT.md — готовое первое задание для вставки в CLI.
- PROJECT_BRIEF.md — описание цели, формата входа/выхода и исходного состояния.
- RULES_AND_OPEN_QUESTIONS.md — конфликты правил и непроверенные предположения.
- BASELINE_AUDIT.md — найденные ограничения исторического starter.
- IMPLEMENTATION_SPEC.md — детектор, бюджет, прогноз, scheduler, oJ, безопасность.
- ACCEPTANCE_TESTS.md — позитивные/негативные сценарии и критерии завершения.
- DEVELOPMENT_PLAN.md, EXPERIMENTS.md — этапы, собственные трассы и сравнения.
- prompts/ — пять отдельных заданий, не одна неограниченная генерация всего проекта.
- materials/original/ — исходный регламент, текст встречи и task-dir.zip.
- materials/clarifications/ — U1, разрешение Codex для разработки по сообщению владельца.
- materials/baseline/ — исходный starter как справка, не замена Git-дерева.
- tools/ — подготовка fixtures без expected, внешний grader 6 non-coding задач,
  проверка контрольных сумм пакета. Скрипты не вызывают модели и не запускают код задач.
- templates/ — дополнения gitignore/dockerignore и пример env без секретов.

## 2. Скопировать пакет в существующий репозиторий
Если предыдущая версия уже установлена, не применяйте `cp -an` для обновления:
он оставит старые файлы. Распакуйте новый ZIP отдельно и запустите обновлятор:

```bash
unzip -n /root/techarena-codex-kit-v2.zip -d /root/techarena-kit-update-v2
python3 /root/techarena-kit-update-v2/techarena-codex-kit/tools/apply_permission_update.py \
  --repo /root/techarena-harness
```

При работе в отдельном клоне укажите его путь и запустите обновлятор от владельца
клона. Инструмент сохраняет резервные копии и меняет только материалы пакета
и корневой AGENTS.md. Он не трогает исходники харнесса, Git-историю или службы.
Незнакомые правки в заменяемых фрагментах приводят к остановке до записи файлов;
в таком случае объедините изменения вручную. Собственные правки вне этих
фрагментов сохраняются. Для них проверка официального manifest может показать
CHANGED — это не повод стирать пользовательские инструкции.

Для первой установки на Windows PowerShell, если архив сохранён в Downloads:

```powershell
scp "$HOME\Downloads\techarena-codex-kit-v2.zip" root@SERVER_IP:/root/
```

На Ubuntu от владельца сервера (не поручать это Codex):

```bash
cd /root/techarena-harness
git status --short
```

Если есть несохранённые изменения, сначала просмотрите и сохраните именно их.
Не применяйте reset/clean. Следующие команды рассчитаны на чистое рабочее дерево.

```bash
git switch -c codex/feasibility-v1
unzip -n /root/techarena-codex-kit-v2.zip -d /root/techarena-kit-staging-v2
mkdir -p docs/codex
cp -an /root/techarena-kit-staging-v2/techarena-codex-kit/. docs/codex/
python3 docs/codex/tools/verify_package.py
```

Корневой AGENTS.md автоматически читается Codex. Создайте его из шаблона, если
его ещё нет. Если он уже существует, объедините правила вручную; не затирайте.

```bash
if [ ! -e AGENTS.md ]; then
  cp docs/codex/AGENTS.md AGENTS.md
else
  printf 'AGENTS.md exists; merge docs/codex/AGENTS.md manually.\n'
fi
```

Однократно дополните исключения, предварительно просмотрев файлы шаблонов:

```bash
cat docs/codex/templates/gitignore.append >> .gitignore
cat docs/codex/templates/dockerignore.append >> .dockerignore

git add AGENTS.md docs/codex .gitignore .dockerignore
git diff --cached --stat
git diff --cached --name-only
# После просмотра содержимого и проверки отсутствия секретов:
git commit -m "Add Codex project brief, contest sources and acceptance plan"
```

Не используйте git add . для каталогов с ключами и регистрацией. Пакет не содержит
этих данных. Не добавляйте .local, .venv, .env и ~/.codex/auth.json.

## 3. Безопасное рабочее место
На сервере уже работают JiuwenSwarm, ssh-agent и heartbeat от root. Не давайте
агенту разработки root-доступ к ним. Рекомендуется отдельный клон под обычным
пользователем без sudo и без членства в группе docker. Sandbox флаги сами по себе
не делают root безопасной учётной записью и не гарантируют закрытость чтения всех
секретов. Ниже готовый путь миграции только конкурсного Git-кода.

После коммита из шага 2, от root:

```bash
# Выполнить один раз; при существующем пользователе/каталоге не перезаписывать.
adduser --disabled-password --gecos "" techarena-dev
git clone --no-hardlinks /root/techarena-harness /home/techarena-dev/techarena-harness
REMOTE_URL=$(git -C /root/techarena-harness remote get-url origin)
git -C /home/techarena-dev/techarena-harness remote set-url origin "$REMOTE_URL"
chown -R techarena-dev:techarena-dev /home/techarena-dev/techarena-harness
chmod 700 /home/techarena-dev
su - techarena-dev
```

Клон получает закоммиченные файлы и текущую ветку; незакоммиченные правки не копируются.
Не копировать root .ssh/.codex/.config/gh и не добавлять пользователя в sudo/docker.
Дальнейшая разработка идёт в `/home/techarena-dev/techarena-harness`.
Работающая установка `/root/TechArena2026` остаётся как была.

GitHub-авторизация root автоматически не переносится; для будущего ручного push
нужна отдельная авторизация разработчика либо перенос проверенного коммита владельцем.
Это не мешает локальной разработке. Настройте автора коммитов отдельно, если будете
коммитить под новым пользователем.

## 4. Установить/авторизовать Codex CLI
Codex используется в разрешённом режиме разработки, описанном в пункте 0.
Официальные ссылки — REFERENCES.md. Если CLI уже установлен, достаточно:

```bash
codex --version
codex login status
```

Официальный standalone installer для Ubuntu не требует установки полного Node-стека.
Загрузите и просмотрите скрипт, затем выполните его от обычного пользователя:

```bash
curl -fsSL https://chatgpt.com/codex/install.sh -o "$HOME/codex-install.sh"
less "$HOME/codex-install.sh"
sh "$HOME/codex-install.sh"
# Следуйте выводу установщика о PATH; при стандартном ~/.local/bin:
export PATH="$HOME/.local/bin:$PATH"
codex --version
```

Альтернатива при уже установленном совместимом Node/npm:

```bash
npm install -g --prefix "$HOME/.local" @openai/codex
export PATH="$HOME/.local/bin:$PATH"
codex --version
```

На Linux актуальному sandbox может требоваться bubblewrap; при соответствующей
ошибке владелец устанавливает пакет через apt, не отключает sandbox. Не выдавайте
агенту sudo и не используйте --yolo/--dangerously-bypass-approvals-and-sandbox.

На headless-сервере:

```bash
codex login --device-auth
codex login status
```

Откройте адрес, который напечатает CLI, в браузере Windows и введите код. Не
прерывайте терминальную команду до её завершения. В аккаунте/организации может
потребоваться разрешить device-code login. Не передавайте коды/токены в чат.
Ключ Qwen-прокси — не ключ для авторизации Codex. Финальный контейнер не должен
содержать Codex, его учётные данные или обращения к его API.

## 5. Проверка материалов без LLM
В клоне разработчика:

```bash
cd /home/techarena-dev/techarena-harness
python3 docs/codex/tools/verify_package.py
python3 docs/codex/tools/prepare_samples.py --out .local/samples-before-01
python3 run_agent.py --tasks-dir .local/samples-before-01/tasks --max-llm-calls 0
python3 docs/codex/tools/grade_non_coding.py \
  --tasks-dir .local/samples-before-01/tasks \
  --labels .local/samples-before-01/evaluation/official_answers.json
```

Исторический baseline: шесть non-coding ответов/16 баллов на образцах. Две coding
этот grader не исполняет и не оценивает. Для следующего прогона используйте новый
--out (например .local/samples-after-01), не старые answers или изменённый код.
В Docker монтируйте только каталог tasks, никогда evaluation или весь репозиторий.

## 6. Первый запуск Codex

```bash
cd /home/techarena-dev/techarena-harness
codex \
  --sandbox workspace-write \
  --ask-for-approval on-request \
  "Прочитай AGENTS.md и docs/codex/START_PROMPT.md. Выполни только этап 1 из docs/codex/prompts/01_AUDIT_AND_OFFLINE.md."
```

Смысл флагов — ограниченный режим записи и согласование расширенных команд, а не
абсолютная гарантия от чтения секретов. Поэтому отдельный непривилегированный
пользователь важнее обещаний в промпте. Проверяйте запрашиваемые команды.
Не разрешайте трогать службы, root home, Docker socket и оплачиваемый прокси.

При проблеме sandbox не обходить защиту; использовать поддерживаемую среду и
официальную диагностику. На этом этапе конкурсный код не вызывает Qwen; сам
Codex, конечно, обращается к собственной модели для разработки.

## 7. Как принимать изменения
После этапа выполните в обычном терминале:

```bash
git status --short
git diff --stat
git diff --check
```

Прочитайте docs/PROGRESS.md и реально запустите перечисленные там тесты.
Не считайте таблицу «PASS» доказательством без результата команды. Затем владелец
вручную выбирает файлы для коммита и push. Ниже пример будущих шагов, не запускайте
их слепо до появления перечисленных файлов:

```bash
git add src run_agent.py tests README.md docs/PROGRESS.md docs/OPEN_QUESTIONS.md
# Проверить staged diff, затем:
git commit -m "Add conservative feasibility checks and offline tests"
git push -u origin codex/feasibility-v1
```

Платные API-вызовы и Docker-сборки — отдельные этапы с ручным разрешением.
Сначала prompt 02, затем 03, 04 и 05; не пытайтесь получить весь проект за один
неограниченный прогон. Реальный бюджет разработки у прокси может быть общим:
не давать долгие benchmark-циклы без установленного владельцем лимита.

## 8. Граница готовности этого пакета
Подготовлены инструкции и исходные материалы. Наличие этого ZIP не означает,
что реализованы Feasibility Detector, BudgetManager, scheduler или SDK-upgrade.
Вспомогательные скрипты проверяются отдельно; results — в PACKAGE_VALIDATION.md.
Правила по моделям, версии SDK и окончательной команде остаются в OPEN_QUESTIONS.
