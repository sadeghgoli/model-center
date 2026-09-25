FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages packages
COPY apps/api apps/api
COPY apps/worker apps/worker
COPY tests tests
COPY pytest.ini pytest.ini
WORKDIR /srv/apps/api
ENV PYTHONPATH=/srv/packages/shared:/srv/packages/auth:/srv/packages/runtimes:/srv/packages/router:/srv/packages/gateway:/srv/apps/api:/srv/apps/worker
COPY apps/api/docker-entrypoint.sh /srv/docker-entrypoint.sh
RUN chmod +x /srv/docker-entrypoint.sh
EXPOSE 8000
CMD ["sh", "/srv/docker-entrypoint.sh"]
