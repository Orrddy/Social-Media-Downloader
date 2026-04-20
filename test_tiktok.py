import asyncio
import yt_dlp
import httpx
import os
import http.cookiejar

os.environ["YTDLP_COOKIES"] = open("C:/My Web Sites/SOCIAL DOWNLOADER/backend/cookies.txt").read()

def test_tiktok():
    opts = {
        'cookiefile': "C:/My Web Sites/SOCIAL DOWNLOADER/backend/cookies.txt",
        'dump_single_json': True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info("https://www.tiktok.com/@eloghosaaaaa/video/7622924424454442261", download=False)
    
    video_format = None
    for f in info.get("formats", []):
        if f.get("vcodec") != "none":
            video_format = f
    
    url = video_format["url"]
    headers = video_format.get("http_headers", {})
    
    # Load cookies
    cookies = httpx.Cookies()
    cj = http.cookiejar.MozillaCookieJar(opts['cookiefile'])
    cj.load(ignore_discard=True, ignore_expires=True)
    for cookie in cj:
        cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
    
    # Test HTTPX request
    client = httpx.Client(cookies=cookies)
    r = client.head(url, headers=headers)
    print("HTTPX HEAD STATUS WITH COOKIES:", r.status_code)

if __name__ == "__main__":
    test_tiktok()
