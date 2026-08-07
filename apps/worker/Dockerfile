FROM python:3.12-slim

WORKDIR /app

# Install the worker package (defines the open_signal package via hatch path)
COPY apps/worker/pyproject.toml /app/worker/
COPY python /app/python
RUN pip install --no-cache-dir /app/worker

CMD ["python", "-c", "import open_signal; print('Open Signal worker', open_signal.__version__)"]
