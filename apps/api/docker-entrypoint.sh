#!/bin/sh
set -eu
alembic upgrade head
python -m mc_api.bootstrap
exec uvicorn mc_api.main:app --host 0.0.0.0 --port 8000
