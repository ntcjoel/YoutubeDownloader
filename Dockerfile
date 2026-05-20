FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (ffmpeg for yt-dlp post-processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY config.yaml .
COPY app.py .
COPY start.py .
COPY downloader.py .
COPY tasks.py .
COPY config.py .
COPY requirements.txt .
COPY templates/ ./templates/
COPY static/ ./static/

# Create output directories
RUN mkdir -p video music

# Default server port
EXPOSE 1917

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:1917/')" || exit 1

# Run
CMD ["python", "start.py"]
