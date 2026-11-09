# Digest and constraints come from the locally inspected container.
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS dependencies

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
COPY requirements.txt constraints.txt /build/
COPY tools/install_locked.py /build/install_locked.py
RUN python install_locked.py constraints.txt requirements.txt

FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
WORKDIR /app
COPY --from=dependencies /usr/local/ /usr/local/
COPY requirements.txt constraints.txt /app/
COPY run_agent.py /app/run_agent.py
COPY src/ /app/src/
USER 10001:10001
ENTRYPOINT ["python", "/app/run_agent.py"]
