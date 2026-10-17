# Superset 4.1 + драйвер Trino (в базовом образе его нет)
FROM apache/superset:4.1.2
USER root
RUN pip install --no-cache-dir "trino[sqlalchemy]==0.340.0"
USER superset
