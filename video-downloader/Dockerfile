FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
# yt-dlp sem versão fixa: sempre pega a mais nova (os sites mudam muito)
RUN pip install --no-cache-dir -U -r requirements.txt
COPY . .
ENV PORT=8000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
