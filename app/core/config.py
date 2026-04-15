from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    PROJECT_NAME: str = "Media Downloader API"
    ALLOWED_HOSTS: List[str] = ["https://orrddyhd.netlify.app", "http://localhost:3000"]
    API_V1_STR: str = "/api"
    
    # Rate limiting
    RATE_LIMIT_DEFAULT: str = "5 per minute"
    
    class Config:
        env_file = ".env"

settings = Settings()
