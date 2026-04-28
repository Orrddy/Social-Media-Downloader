"""
Corrected main.py with fixes applied:
- Safe logging without sensitive data
- Better CORS configuration with credential support
- Health check endpoint
- Rate limit response headers
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.api.endpoints import downloader, health
from app.core.config import settings
from app.core.security import setup_rate_limiting
import logging
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# ✅ Response compression for bandwidth efficiency
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ✅ FIXED: Better CORS configuration
# - Allow credentials for future auth support
# - Add Authorization header
# - Expose rate limit headers to client
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_HOSTS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["X-RateLimit-Remaining", "X-RateLimit-Limit"],
    max_age=3600,  # Cache preflight for 1 hour
)


def redact_sensitive_params(url: str) -> str:
    """
    ✅ FIXED: Redact sensitive query parameters from logs
    
    Prevents logging of:
    - Video URLs (might contain tokens)
    - Format IDs (could be user traceable)
    - Other PII
    """
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return parsed.path

        params = parse_qs(parsed.query)
        safe_params = {}

        # Redact sensitive parameters
        redacted_keys = ['url', 'format_id']
        
        for key, values in params.items():
            if key in redacted_keys:
                safe_params[key] = '[REDACTED]'
            else:
                # Truncate other params for privacy
                value = values[0] if values else ''
                safe_params[key] = value[:20] if len(value) > 20 else value

        # Rebuild query string
        query_parts = [f"{k}={v}" for k, v in safe_params.items()]
        query_str = "&".join(query_parts) if query_parts else ""
        
        return f"{parsed.path}?{query_str}" if query_str else parsed.path

    except Exception as e:
        logger.debug(f"Failed to redact URL params: {e}")
        return "[PARSE_ERROR]"


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    ✅ FIXED: Safe request/response logging
    - Redacts sensitive query parameters
    - Hides user information
    - Logs timing for performance monitoring
    """
    import time
    
    # Log only path and safe params, not full URL
    safe_url = redact_sensitive_params(str(request.url))
    request_line = f"{request.method} {safe_url}"
    
    start_time = time.time()
    logger.info(f"Incoming request: {request_line}")
    
    try:
        response = await call_next(request)
        
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"Response status: {response.status_code} (duration: {duration_ms:.1f}ms)"
        )
        
        return response
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            f"Request failed after {duration_ms:.1f}ms: {str(e)[:100]}"
        )
        raise


# ✅ Rate limiting setup
setup_rate_limiting(app)

# Routers
app.include_router(health.router, tags=["health"])
app.include_router(
    downloader.router,
    prefix=settings.API_V1_STR,
    tags=["downloader"]
)


@app.get("/")
async def root():
    """Root endpoint with API info"""
    return {
        "message": "Social Media Downloader API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health")
async def health_check():
    """
    ✅ Simple health check endpoint
    Returns 200 if service is operational
    """
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME
    }


# ✅ Error handlers with safe logging
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler with safe logging"""
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {str(exc)[:100]}",
        exc_info=True
    )
    
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error. Please try again later."
        }
    )
