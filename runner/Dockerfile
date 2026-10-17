# Лёгкий контейнер-клиент: Python + официальный trino-client + matplotlib для графиков
FROM python:3.12-slim
RUN pip install --no-cache-dir trino==0.340.0 matplotlib==3.10.8
WORKDIR /work
CMD ["python", "runner/lakehouse.py", "--help"]
