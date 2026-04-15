import re
from fastapi import HTTPException

# Regex for supported platforms
# YouTube, TikTok, Facebook, Instagram, Twitter (X), Telegram
PLATFORMS_REGEX = {
    "youtube": r"(https?://)?(www\.|m\.)?(youtube\.com|youtu\.be)/.+",
    "tiktok": r"(https?://)?(www\.|vm\.|vt\.|v\.)?tiktok\.com/.+",
    "facebook": r"(https?://)?(www\.|m\.|web\.)?facebook\.com/.+",
    "instagram": r"(https?://)?(www\.)?instagram\.com/(p|reels|tv|stories)/.+",
    "twitter": r"(https?://)?(www\.|x\.|mobile\.)?(twitter|x)\.com/.+",
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
