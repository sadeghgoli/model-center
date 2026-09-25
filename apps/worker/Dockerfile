FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages packages
COPY apps/api apps/api
COPY apps/worker apps/worker
ENV PYTHONPATH=/srv/packages/shared:/srv/packages/auth:/srv/packages/runtimes:/srv/packages/router:/srv/packages/gateway:/srv/apps/api:/srv/apps/worker
CMD ["python", "/srv/apps/worker/health.py"]
