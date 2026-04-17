import re

# Anchored regexes for supported platforms.
# Using re.fullmatch to prevent partial matches (e.g. "me/foo" matching Telegram pattern).
PLATFORMS_REGEX = {
    "youtube":   r"^(https?://)?(www\.|m\.)?(youtube\.com|youtu\.be)/.+$",
    "tiktok":    r"^(https?://)?(www\.|vm\.|vt\.|v\.)?tiktok\.com/.+$",
    "facebook":  r"^(https?://)?(www\.|m\.|web\.)?facebook\.com/.+$",
    "instagram": r"^(https?://)?(www\.)?instagram\.com/(p|reels|reel|tv|stories)/.+$",
    "twitter":   r"^(https?://)?(www\.|x\.|mobile\.)?(twitter|x)\.com/.+$",
    "telegram":  r"^https?://(t\.me|telegram\.me)/.+$",  # require scheme for Telegram
}

def validate_url(url: str) -> bool:
    """
    Validates if the URL belongs to a supported platform.
    Returns True if the URL matches any known platform pattern.
    """
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    for pattern in PLATFORMS_REGEX.values():
        if re.fullmatch(pattern, url):
            return True
    return False

def get_platform(url: str) -> str:
    """
    Identifies the platform from the URL.
    Returns the platform name or 'unsupported'.
    """
    if not url:
        return "unsupported"
    url = url.strip()
    for platform, pattern in PLATFORMS_REGEX.items():
        if re.fullmatch(pattern, url):
            return platform
    return "unsupported"
