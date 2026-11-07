# TechArena 2026 — starter harness

A starter, **not the final competition submission**. Implements an openJiuwen
model call for coding tasks and deterministic solvers for the sample-like
math / search / data-analysis patterns. Never reads `expected`.

## Run locally

```bash
python3 run_agent.py --tasks-dir /path/to/task-dir --max-llm-calls 0
```

If `LLM_BASE_URL` and `LLM_API_KEY` are missing, tasks requiring the model are
skipped rather than silently fabricated. Set `CODING_MODEL` to one of the four
allowed Qwen model names; default `qwen3.8-27b-noreason`.

## Run in Docker

```bash
docker build -t hack:latest .
docker run --rm --read-only --tmpfs /tmp:rw,size=2g \
  --network hack-net --cap-drop ALL --security-opt no-new-privileges \
  --cpus 4 --memory 16g --pids-limit 512 \
  -e LLM_BASE_URL -e LLM_API_KEY \
  -v "$TASKS:/data/tasks:rw" \
  --workdir /app hack:latest --tasks-dir /data/tasks
```

The competition's actual command overrides entrypoint with `python`, so
`python /app/run_agent.py --tasks-dir /data/tasks` works too.

Each completed task is saved immediately as `answer.txt` in the task directory;
if there is a `workspace/`, a matching `workspace/answer.txt` is also written.
For coding tasks, the source is updated only when `test_mylib.py` passes.

## What still needs work

- Real budget-aware task planner (token cost & success probability estimates).
- Model fallback, multi-step agent tools, and per-call token accounting.
- Better problem-type generalization; hidden tasks need not match regexes.
- Container build validation + security assessment, frozen transitive deps,
  base-image digest, and end-to-end trial on the organizer's environment.
- Confirm answer placement with the organizers if checker expects one location.

Do not put proxy keys, team members' personal data or SSH keys in Git.

## Observed starter baseline

Tested with the 8 supplied examples, using `--max-llm-calls 0`: 6/8
answers match the sample `expected` values (sum of rewards: 16). The 2
`coding` tasks require further testing with the official LLM proxy. This is
not a prediction of hidden-set performance.
