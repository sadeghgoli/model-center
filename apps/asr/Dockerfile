FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/asr
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu124
RUN pip install --no-cache-dir --index-url "$TORCH_INDEX" torch==2.6.0
COPY apps/asr/requirements.txt .
RUN pip install --no-cache-dir -i https://mirror-pypi.runflare.com/simple -r requirements.txt
COPY apps/asr/server.py ./
ENV HF_HOME=/root/.cache/huggingface
EXPOSE 8011
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8011"]
