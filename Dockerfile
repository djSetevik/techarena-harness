# Pin the Python base tag. Pin digest + transitive Python dependencies before final submission.
FROM python:3.12.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY run_agent.py /app/run_agent.py
COPY src/ /app/src/
ENTRYPOINT ["python", "/app/run_agent.py"]
