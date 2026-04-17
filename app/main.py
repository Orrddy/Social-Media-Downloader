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

# CORS — only allow configured origins; credentials not needed for this public API
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

# Setup Rate Limiting (global via SlowAPIMiddleware)
setup_rate_limiting(app)

# Include Routers
app.include_router(health.router, tags=["health"])
app.include_router(downloader.router, prefix=settings.API_V1_STR, tags=["downloader"])

@app.get("/")
async def root():
    return {"message": "Welcome to the Media Downloader API. Visit /docs for documentation."}
