FROM python:3.11-slim

WORKDIR /app

# Install system deps (ffmpeg for metadata, curl for yt-dlp updates)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install yt-dlp (latest)
RUN curl -sSL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp && chmod +x /usr/local/bin/yt-dlp

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app (exclude venv, __pycache__, video, music, logs from host)
COPY . .

# Create output dirs inside image (fallback, volumes override them)
RUN mkdir -p /app/video /app/music /app/logs

EXPOSE 1917

CMD ["python", "start.py"]
