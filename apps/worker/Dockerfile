FROM python:3.12-slim

WORKDIR /app

COPY python /app/python
COPY infra /app/infra
COPY fixtures /app/fixtures
COPY apps/worker /app/worker

RUN pip install --no-cache-dir /app/python \
    && pip install --no-cache-dir /app/worker

ENV PYTHONPATH=/app/python

CMD ["python", "-m", "open_signal_worker", "--mode", "once"]
