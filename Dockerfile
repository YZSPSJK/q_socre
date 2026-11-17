FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QSCORE_PYTHON=/usr/local/bin/python \
    QSCORE_SERVE_STATIC=1

WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY manage.py start.sh ./
COPY qscore/ qscore/
COPY ratings/ ratings/
RUN QSCORE_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=5 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/login/', timeout=2).close()"]

ENTRYPOINT ["/app/start.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-", "qscore.wsgi:application"]
