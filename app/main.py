from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.endpoints import downloader, health
from app.core.config import settings
from app.core.security import setup_rate_limiting

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Set CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_HOSTS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup Rate Limiting
setup_rate_limiting(app)

# Include Routers
app.include_router(health.router, tags=["health"])
app.include_router(downloader.router, prefix=settings.API_V1_STR, tags=["downloader"])

@app.get("/")
async def root():
    return {"message": "Welcome to the Media Downloader API. Visit /docs for documentation."}
