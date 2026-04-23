from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.api.endpoints import downloader, health
from app.core.config import settings
from app.core.security import setup_rate_limiting
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS — restricted to ALLOWED_HOSTS defined in config / .env.
# Previously hardcoded to "*", making ALLOWED_HOSTS a dead config value.
# Allow wildcard only if ALLOWED_HOSTS explicitly contains "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_HOSTS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# Request/response logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url}")
    response = await call_next(request)
    logger.info(f"Response status: {response.status_code}")
    return response

# Rate Limiting (per-route via @limiter.limit decorators — no global default)
setup_rate_limiting(app)

# Routers
app.include_router(health.router, tags=["health"])
app.include_router(downloader.router, prefix=settings.API_V1_STR, tags=["downloader"])


@app.get("/")
async def root():
    return {"message": "Welcome to the Media Downloader API. Visit /docs for documentation."}
