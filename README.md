# Social Media Downloader API 🚀

A production-ready, high-performance media extraction API built with **FastAPI**. This backend serves as the core engine for the Social Media Downloader platform, handling metadata extraction and on-the-fly media streaming.

## ✨ Features

- **Multi-Platform Support**: YouTube, TikTok, Facebook, Instagram, Twitter (X), and Telegram.
- **Fast Metadata Extraction**: Uses `yt-dlp` to fetch titles, thumbnails, and durations without full downloads.
- **On-the-Fly Conversion**: Real-time audio-to-MP3 streaming using **FFmpeg** pipes (no permanent file storage).
- **Security & Performance**:
  - Rate limiting (SlowAPI) to prevent abuse.
  - In-memory caching for faster repeated requests.
  - CORS security restricted to authorized frontends.
- **Containerized**: Ready for deployment on **Render** via Docker.

## 🛠️ Tech Stack

- **Framework**: FastAPI
- **Engine**: yt-dlp
- **Processor**: FFmpeg
- **Rate Limiting**: SlowAPI
- **Validation**: Pydantic v2

## 🚀 Deployment (Render)

1. **Create Web Service**: Connect this GitHub repository to Render.
2. **Runtime**: Select **Docker**.
3. **Environment Variables**:
   - `ALLOWED_HOSTS`: Your frontend URL (e.g., `https://your-app.netlify.app`).
   - `RATE_LIMIT_DEFAULT`: e.g., `5/minute`.
4. **Resources**: At least 512MB RAM is recommended for FFmpeg processing.

## 📡 API Endpoints

### `POST /api/download`
Fetches metadata and available formats for a given URL.
**Body:**
```json
{ "url": "https://www.youtube.com/watch?v=..." }
```

### `GET /api/stream`
Streams the media artifact directly to the user.
**Query Params:** `url`, `type`, `quality`.

---
*Created for the Ethereal Archivist Project.*
