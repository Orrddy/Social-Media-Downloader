from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List, Any


class Settings(BaseSettings):
    PROJECT_NAME: str = "Media Downloader API"
    ALLOWED_HOSTS: Any = ["https://orrddyhd.netlify.app", "http://localhost:3000"]
    API_V1_STR: str = "/api"

    # Rate limiting
    RATE_LIMIT_DEFAULT: str = "5 per minute"

    @field_validator("ALLOWED_HOSTS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        return [v] if v else []

    # Use Pydantic v2 SettingsConfigDict — replaces deprecated inner `Config` class
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


settings = Settings()
