#!/bin/sh
set -eu

cd "$(dirname "$0")"
python_bin=${QSCORE_PYTHON:-.venv/bin/python}

"$python_bin" manage.py migrate --noinput

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

exec "$python_bin" manage.py runserver 127.0.0.1:8000
