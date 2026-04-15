import re
from fastapi import HTTPException

# Regex for supported platforms
# YouTube, TikTok, Facebook, Instagram, Twitter (X), Telegram
PLATFORMS_REGEX = {
    "youtube": r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+",
    "tiktok": r"(https?://)?(www\.|vm\.)?tiktok\.com/.+",
    "facebook": r"(https?://)?(www\.)?facebook\.com/.+",
    "instagram": r"(https?://)?(www\.)?instagram\.com/.+",
    "twitter": r"(https?://)?(www\.|x\.)?(twitter|x)\.com/.+",
    "telegram": r"(https?://)?(t\.)?me/.+"
}

def validate_url(url: str) -> bool:
    """
    Validates if the URL belongs to a supported platform.
    """
    for platform, pattern in PLATFORMS_REGEX.items():
        if re.match(pattern, url):
            return True
    return False

def get_platform(url: str) -> str:
    """
    Identifies the platform from the URL.
    """
    for platform, pattern in PLATFORMS_REGEX.items():
        if re.match(pattern, url):
            return platform
    return "unsupported"
