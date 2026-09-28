FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/tts
COPY apps/tts/requirements.txt .
RUN pip install --no-cache-dir -i https://mirror-pypi.runflare.com/simple -r requirements.txt
COPY apps/tts/pocket_engine.py apps/tts/server.py ./
ENV HF_HOME=/root/.cache/huggingface
EXPOSE 8010
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8010"]
