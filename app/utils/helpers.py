import urllib.parse


def sanitize_filename(title: str, max_len: int = 50, fallback: str = "download") -> str:
    """
    Produces a safe ASCII filename from an arbitrary title string.
    Keeps alphanumerics, spaces, hyphens, and underscores; truncates to max_len.
    """
    safe = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
    return (safe[:max_len] or fallback)


def build_content_disposition(filename: str) -> str:
    """
    Builds an RFC 5987-compliant Content-Disposition header value.
    Provides both an ASCII-safe fallback and a full UTF-8 encoded filename.
    """
    ascii_name = filename.encode("ascii", "ignore").decode()
    encoded = urllib.parse.quote(filename)
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'
