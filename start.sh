#!/bin/bash
set -e
python manage.py migrate --no-input
exec uvicorn api:app --host 0.0.0.0 --port 7860
