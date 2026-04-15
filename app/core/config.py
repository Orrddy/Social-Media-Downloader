from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List, Union

class Settings(BaseSettings):
    PROJECT_NAME: str = "Media Downloader API"
    ALLOWED_HOSTS: List[str] = ["https://orrddyhd.netlify.app", "http://localhost:3000"]
    API_V1_STR: str = "/api"
    
    # Rate limiting
    RATE_LIMIT_DEFAULT: str = "5 per minute"

    @field_validator("ALLOWED_HOSTS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)
    
    class Config:
        env_file = ".env"

settings = Settings()
