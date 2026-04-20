FROM python:3.11-slim

# Install FFmpeg and clean up apt cache to keep image size small
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application source code
COPY . .

# Start the FastAPI server on port binding used by Render
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10000"]
