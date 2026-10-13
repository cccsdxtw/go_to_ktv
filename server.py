#!/usr/bin/env python3
"""網頁工具：貼上 StreamerSonglist 歌單網址，或從表格轉成 Elitesand 歌單。"""

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 0.0.0.0：本機與遠端都能連；若只想本機可設 GO_TO_KTV_HOST=127.0.0.1
HOST = os.environ.get("GO_TO_KTV_HOST", "0.0.0.0").strip() or "0.0.0.0"
PORT = int(os.environ.get("GO_TO_KTV_PORT", "8765") or "8765")
ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
AUDIO_DIR = ROOT / "elitesand-audio"
APP_VERSION = "0.5.1"
ALLOWED_HOSTS = {"streamersonglist.com", "www.streamersonglist.com"}
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{2,40}$")
PAGE_PATH_RE = re.compile(r"^/t/([A-Za-z0-9_]{2,40})(?:/songs)?/?$")
MAX_PAGES = 80
MAX_SONGS = 5000
YTDLP_TIMEOUT_SEC = 45
DOWNLOAD_TIMEOUT_SEC = 180
AUDIO_EXTS = {".mp3", ".m4a", ".ogg", ".opus", ".aac", ".wav", ".flac", ".webm"}

HOLE = -1
NAN = -2
NEG_INF = -3
NEG_ZERO = -4
NULL = -5
POS_INF = -6
UNDEF = -7
UNDEF_SENTINEL = object()


class SongListError(Exception):
    pass


class Decoder:
    def __init__(self):
        self.values = []
        self.hydrated = {}

    def unflatten(self, parsed):
        if not isinstance(parsed, list) or not parsed:
            raise SongListError("歌單網站回傳的資料無法讀取。")
        start = len(self.values)
        self.values.extend(parsed)
        return self.hydrate(start)

    def hydrate(self, index):
        if index == UNDEF:
            return UNDEF_SENTINEL
        if index == NULL:
            return None
        if index == NAN:
            return float("nan")
        if index == POS_INF:
            return float("inf")
        if index == NEG_INF:
            return float("-inf")
        if index == NEG_ZERO:
            return -0.0
        if index < 0:
            raise SongListError("歌單網站回傳的資料無法讀取。")
        if index in self.hydrated:
            return self.hydrated[index]
        value = self.values[index]
        if isinstance(value, list):
            return self.hydrate_list(index, value)
        if isinstance(value, dict):
            return self.hydrate_object(index, value)
        self.hydrated[index] = value
        return value

    def hydrate_list(self, index, value):
        if value and isinstance(value[0], str):
            kind = value[0]
            if kind == "D":
                stamp = value[1]
                if stamp == "invalid":
                    result = None
                else:
                    result = datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat()
                self.hydrated[index] = result
                return result
            if kind in {"U", "B", "Y"}:
                self.hydrated[index] = value[1]
                return value[1]
            if kind == "R":
                flags = value[2] if len(value) > 2 else ""
                result = f"/{value[1]}/{flags}"
                self.hydrated[index] = result
                return result
            if kind == "S":
                result = []
                self.hydrated[index] = result
                for item in value[1:]:
                    result.append(self.hydrate(item))
                return result
            if kind == "M":
                result = {}
                self.hydrated[index] = result
                pairs = value[1:]
                for offset in range(0, len(pairs), 2):
                    key = self.hydrate(pairs[offset])
                    result[key] = self.hydrate(pairs[offset + 1])
                return result
            if kind == "N":
                return self.hydrate_object(index, value[1])
            if kind == "Z":
                return self.hydrate(value[1])
            if kind in {"P", "E"}:
                result = None
                self.hydrated[index] = result
                return result
            if kind == "SingleFetchRedirect":
                info = self.hydrate(value[1]) if len(value) > 1 else {}
                redirect = info.get("redirect") if isinstance(info, dict) else ""
                if isinstance(redirect, str) and "streamer-not-found" in redirect:
                    raise SongListError("找不到這個歌單，請確認網址。")
            raise SongListError("歌單網站回傳的資料無法讀取。")
        result = []
        self.hydrated[index] = result
        for item in value:
            result.append(None if item == HOLE else self.hydrate(item))
        return result

    def hydrate_object(self, index, value):
        result = {}
        self.hydrated[index] = result
        for key, ref in value.items():
            name = self.hydrate(int(key[1:]))
            item = self.hydrate(ref)
            if item is not UNDEF_SENTINEL:
                result[name] = item
        return result


def parse_username(raw_url):
    text = (raw_url or "").strip()
    if not text:
        raise SongListError("請貼上歌單網址。")
    if "://" not in text:
        text = "https://" + text
    parsed = urllib.parse.urlparse(text)
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise SongListError("目前只接受 streamersonglist.com 的歌單網址。")
    match = PAGE_PATH_RE.match(parsed.path)
    if not match:
        raise SongListError("請貼歌單頁網址，例如 https://streamersonglist.com/t/名稱/songs")
    username = match.group(1)
    if not USERNAME_RE.match(username):
        raise SongListError("這個網址裡的名稱無法辨認。")
    return username


def fetch_payload(url):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/x-script",
            "User-Agent": "go-to-ktv",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise SongListError("找不到這個歌單，請確認網址。") from error
        raise SongListError("歌單網站暫時沒有回應，請稍後再試。") from error
    except urllib.error.URLError as error:
        raise SongListError("連不上歌單網站，請稍後再試。") from error
    line = raw.split("\n", 1)[0]
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError as error:
        raise SongListError("歌單網站回傳的資料無法讀取。") from error
    return Decoder().unflatten(parsed)


def route_data(payload, route_id):
    route = payload.get(route_id)
    if isinstance(route, dict) and isinstance(route.get("data"), dict):
        return route["data"]
    if isinstance(route, dict):
        return route
    return {}


def day(value):
    if not value or not isinstance(value, str):
        return ""
    return value[:10]


def attribute_names(song):
    names = []
    for attribute in song.get("attributes") or []:
        if isinstance(attribute, dict) and attribute.get("name"):
            names.append(attribute["name"])
    return names


def fetch_songs(username):
    songs = []
    seen_ids = set()
    seen_tokens = set()
    token = ""
    total = None
    display_name = username
    for _ in range(MAX_PAGES):
        url = f"https://streamersonglist.com/t/{urllib.parse.quote(username)}/songs.data"
        if token:
            if token in seen_tokens:
                break
            seen_tokens.add(token)
            url += "?after=" + urllib.parse.quote(token, safe="")
        payload = fetch_payload(url)
        streamer = route_data(payload, "./routes/streamer/_streamer")
        profile = streamer.get("streamer") if isinstance(streamer.get("streamer"), dict) else {}
        platforms = profile.get("platforms") if isinstance(profile.get("platforms"), dict) else {}
        for platform in platforms.values():
            if isinstance(platform, dict) and platform.get("displayName"):
                display_name = platform["displayName"]
                break
        page = route_data(payload, "./routes/streamer/songs")
        if "songs" not in page:
            raise SongListError("找不到這個歌單，請確認網址。")
        batch = page.get("songs") or []
        total = page.get("total") if isinstance(page.get("total"), int) else total
        added = 0
        for song in batch:
            song_id = song.get("id")
            if song_id in seen_ids:
                continue
            seen_ids.add(song_id)
            songs.append(
                {
                    "id": song_id,
                    "title": song.get("title") or "",
                    "artist": song.get("artist") or "",
                    "attributes": attribute_names(song),
                    "lastPlayed": day(song.get("lastPlayed")),
                    "timesPlayed": song.get("timesPlayed") or 0,
                }
            )
            added += 1
            if len(songs) >= MAX_SONGS:
                break
        token = page.get("token") or ""
        if not batch or added == 0 or not token or (total is not None and len(songs) >= total):
            break
        if len(songs) >= MAX_SONGS:
            break
    return {
        "username": username,
        "displayName": display_name,
        "total": total if total is not None else len(songs),
        "songs": songs,
        "sourceUrl": f"https://streamersonglist.com/t/{username}/songs",
    }


def find_ytdlp():
    found = shutil.which("yt-dlp")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "yt-dlp"
    if local.is_file():
        return str(local)
    return None


COOKIE_BROWSERS = ("chrome", "edge", "firefox", "brave", "chromium", "opera", "safari")
BOT_ERROR_RE = re.compile(
    r"sign in to confirm|not a bot|login required|cookies?-from-browser|--cookies|use --cookies",
    re.I,
)
COOKIE_LOCK_RE = re.compile(
    r"could not copy|database is locked|failed to load cookies|unable to find|no such file",
    re.I,
)
_working_ytdlp = {"browser": None, "extractor": None}


def reset_ytdlp_auth():
    _working_ytdlp["browser"] = None
    _working_ytdlp["extractor"] = None


def normalize_browser(value):
    name = str(value or "").strip().lower().replace(" ", "-")
    aliases = {
        "msedge": "edge",
        "microsoft-edge": "edge",
        "google-chrome": "chrome",
        "googlechrome": "chrome",
    }
    name = aliases.get(name, name)
    return name if name in COOKIE_BROWSERS else ""


def ytdlp_output_text(completed):
    return ((getattr(completed, "stderr", None) or "") + "\n" + (getattr(completed, "stdout", None) or "")).strip()


def is_bot_block(text):
    return bool(BOT_ERROR_RE.search(text or ""))


def friendly_download_error(text, tried_cookies=False):
    if is_bot_block(text) or tried_cookies:
        return (
            "YouTube 把下載當成機器人擋住了。"
            "請先在 Chrome 或 Edge 打開 youtube.com 並登入，上面選好瀏覽器再按一次「下載全部音檔」。"
            "驗證過後會自動整批存到這台電腦，不用一首一首另存。"
        )
    detail = (text or "").strip().splitlines()
    return (detail[-1] if detail else "音檔下載失敗。")[:240]


def cookie_attempt_order(preferred=""):
    ordered = []
    for name in (
        preferred,
        os.environ.get("GO_TO_KTV_BROWSER", ""),
        _working_ytdlp.get("browser"),
        "chrome",
        "edge",
        "firefox",
        "brave",
    ):
        name = normalize_browser(name)
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def run_ytdlp(command, timeout, cookie_browser=None, extractor=None):
    cmd = list(command)
    if extractor:
        cmd.extend(["--extractor-args", extractor])
    if cookie_browser:
        cmd.extend(["--cookies-from-browser", cookie_browser])
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def download_attempts(preferred_browser=""):
    attempts = []
    working = (_working_ytdlp.get("browser"), _working_ytdlp.get("extractor"))
    if working[0] or working[1]:
        attempts.append(working)
    attempts.append((None, "youtube:player_client=android,ios"))
    for browser in cookie_attempt_order(preferred_browser):
        attempts.append((browser, "youtube:player_client=android,ios"))
        attempts.append((browser, None))
    unique = []
    seen = set()
    for item in attempts:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def build_search_query(title, artist):
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    artist = re.sub(r"\s+", " ", str(artist or "")).strip()
    if not title:
        raise SongListError("缺少歌名，無法搜尋。")
    # 歌回／KTV 用途優先找伴奏，避免搜到原唱有人聲的版本。
    parts = [title]
    if artist:
        parts.append(artist)
    parts.append("伴奏")
    return " ".join(parts)[:180]


INSTRUMENTAL_HINTS = (
    "伴奏",
    "カラオケ",
    "karaoke",
    "instrumental",
    "off vocal",
    "offvocal",
    "tv size instrumental",
    "マイナスワン",
)


def instrumental_score(item):
    title = str(item.get("title") or "").lower()
    score = 0
    for hint in INSTRUMENTAL_HINTS:
        if hint.lower() in title:
            score += 10
    # 明顯有人聲／翻唱的往後排
    for bad in ("cover", "歌ってみた", "covered by", "full vocal", "原曲"):
        if bad in title:
            score -= 3
    return score


def pick_youtube_entry(entries):
    candidates = [item for item in entries if isinstance(item, dict) and item.get("id")]
    if not candidates:
        return None
    ranked = sorted(
        enumerate(candidates),
        key=lambda pair: (-instrumental_score(pair[1]), pair[0]),
    )
    return ranked[0][1]


def search_youtube(title, artist):
    ytdlp = find_ytdlp()
    if not ytdlp:
        raise SongListError("找不到 yt-dlp。請先執行：pip install yt-dlp")
    query = build_search_query(title, artist)
    command = [
        ytdlp,
        f"ytsearch5:{query}",
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        "--skip-download",
        "--no-playlist",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=YTDLP_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise SongListError("YouTube 搜尋逾時，請稍後再試。") from error
    except OSError as error:
        raise SongListError("無法啟動 yt-dlp。") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        message = detail[-1] if detail else "YouTube 搜尋失敗。"
        raise SongListError(message[:240])
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise SongListError("YouTube 搜尋結果無法讀取。") from error
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if isinstance(entries, list):
        item = pick_youtube_entry(entries)
    elif isinstance(payload, dict) and payload.get("id"):
        item = payload
    else:
        item = None
    if not isinstance(item, dict) or not item.get("id"):
        raise SongListError("找不到這首歌的 YouTube 結果。")
    video_id = str(item["id"])
    return {
        "videoId": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "youtubeTitle": item.get("title") or "",
        "uploader": item.get("uploader") or item.get("channel") or "",
        "duration": item.get("duration"),
        "query": query,
    }


def find_ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "ffmpeg"
    if local.is_file():
        return str(local)
    return None


def sanitize_for_filename(name):
    cleaned = re.sub(r'[\\/:*?"<>|]', " ", str(name or ""))
    return re.sub(r"\s+", " ", cleaned).strip()[:80]


def build_track_filename(artist, title, ext):
    clean_title = sanitize_for_filename(title) or "未知歌曲"
    clean_artist = sanitize_for_filename(artist)
    base = f"{clean_artist} - {clean_title}" if clean_artist else clean_title
    if not str(ext).startswith("."):
        ext = "." + str(ext)
    return base + ext


def unique_path(directory, filename):
    path = directory / filename
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 80):
        candidate = directory / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem}-{int(time.time())}{suffix}"


def parse_watch_url(raw_url):
    text = str(raw_url or "").strip()
    if not text:
        raise SongListError("請提供 YouTube 網址。")
    if "://" not in text:
        text = "https://" + text
    parsed = urllib.parse.urlparse(text)
    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        raise SongListError("目前只接受 YouTube 網址。")
    video_id = ""
    if host == "youtu.be":
        video_id = (parsed.path or "/").strip("/").split("/")[0]
    elif parsed.path == "/watch":
        video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
    else:
        match = re.match(r"^/(?:embed|shorts|v)/([A-Za-z0-9_-]{6,18})", parsed.path or "")
        video_id = match.group(1) if match else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,18}", video_id or ""):
        raise SongListError("這不是有效的 YouTube 影片網址。")
    return video_id, f"https://www.youtube.com/watch?v={video_id}"


def existing_download(video_id):
    marker = AUDIO_DIR / f".{video_id}.done"
    if not marker.is_file():
        return None
    saved = marker.read_text(encoding="utf-8").strip()
    if not saved:
        return None
    path = AUDIO_DIR / saved
    if path.is_file() and path.stat().st_size > 1024:
        return path
    return None


def produced_audio_file(video_id):
    matches = []
    for candidate in AUDIO_DIR.glob(f"{video_id}.*"):
        if candidate.suffix.lower() in AUDIO_EXTS and candidate.is_file():
            matches.append(candidate)
    if not matches:
        return None
    matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return matches[0]


def download_youtube_audio(raw_url, title, artist, browser=""):
    ytdlp = find_ytdlp()
    if not ytdlp:
        raise SongListError("找不到 yt-dlp。請先執行：pip install yt-dlp")
    video_id, watch_url = parse_watch_url(raw_url)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    already = existing_download(video_id)
    if already:
        return {
            "filename": already.name,
            "folder": str(AUDIO_DIR),
            "skipped": True,
            "videoId": video_id,
        }
    ffmpeg = find_ffmpeg()
    ext = ".mp3" if ffmpeg else ".m4a"
    final_path = unique_path(AUDIO_DIR, build_track_filename(artist, title, ext))
    command = [
        ytdlp,
        watch_url,
        "--no-playlist",
        "--no-warnings",
        "--newline",
        "-o",
        str(AUDIO_DIR / f"{video_id}.%(ext)s"),
    ]
    if ffmpeg:
        command.extend(["-x", "--audio-format", "mp3", "--audio-quality", "0"])
    else:
        command.extend(["-f", "bestaudio[ext=m4a]/bestaudio/best", "--no-keep-video"])

    produced = None
    last_text = ""
    tried_cookies = False
    used_browser = None
    used_extractor = None
    for cookie_browser, extractor in download_attempts(browser):
        try:
            completed = run_ytdlp(
                command,
                DOWNLOAD_TIMEOUT_SEC,
                cookie_browser=cookie_browser,
                extractor=extractor,
            )
        except subprocess.TimeoutExpired as error:
            raise SongListError("音檔下載逾時，請稍後再試。") from error
        except OSError as error:
            raise SongListError("無法啟動 yt-dlp。") from error
        last_text = ytdlp_output_text(completed)
        produced = produced_audio_file(video_id)
        if completed.returncode == 0 and produced:
            used_browser = cookie_browser
            used_extractor = extractor
            _working_ytdlp["browser"] = cookie_browser
            _working_ytdlp["extractor"] = extractor
            break
        produced = None
        if cookie_browser:
            tried_cookies = True
        if (
            completed.returncode != 0
            and not is_bot_block(last_text)
            and not COOKIE_LOCK_RE.search(last_text or "")
        ):
            # 不是機器人／Cookie 問題就不要把每種瀏覽器都試一遍
            if cookie_browser:
                break
    if not produced:
        raise SongListError(friendly_download_error(last_text, tried_cookies))
    try:
        produced.replace(final_path)
    except OSError:
        shutil.copy2(produced, final_path)
        produced.unlink(missing_ok=True)
    marker = AUDIO_DIR / f".{video_id}.done"
    marker.write_text(final_path.name, encoding="utf-8")
    return {
        "filename": final_path.name,
        "folder": str(AUDIO_DIR),
        "skipped": False,
        "videoId": video_id,
        "format": ext.lstrip("."),
        "cookieBrowser": used_browser or "",
        "extractor": used_extractor or "",
    }


def open_audio_folder():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    folder = str(AUDIO_DIR)
    if os.name == "nt":
        os.startfile(folder)
        return folder
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return folder


def read_json_body(handler, max_length, empty_error):
    length = int(handler.headers.get("Content-Length") or "0")
    if length <= 0 or length > max_length:
        raise SongListError(empty_error)
    try:
        incoming = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SongListError(empty_error) from error
    if not isinstance(incoming, dict):
        raise SongListError(empty_error)
    return incoming


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in {"/", "/index.html"}:
            if not INDEX.is_file():
                self.send_error(404)
                return
            body = INDEX.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/health":
            ytdlp = find_ytdlp()
            ffmpeg = find_ffmpeg()
            self.respond_json(
                200,
                {
                    "ok": True,
                    "ytdlp": bool(ytdlp),
                    "ytdlpPath": ytdlp,
                    "ffmpeg": bool(ffmpeg),
                    "audioDir": str(AUDIO_DIR),
                    "version": APP_VERSION,
                },
            )
            return
        self.send_error(404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/songs":
            try:
                incoming = read_json_body(self, 4000, "請貼上歌單網址。")
                username = parse_username(incoming.get("url"))
                result = fetch_songs(username)
            except SongListError as error:
                self.respond_json(400, {"error": str(error)})
                return
            print(f"{username}: {len(result['songs'])} songs", flush=True)
            self.respond_json(200, result)
            return
        if path == "/api/youtube-search":
            try:
                incoming = read_json_body(self, 8000, "請提供歌名。")
                result = search_youtube(incoming.get("title"), incoming.get("artist"))
            except SongListError as error:
                self.respond_json(400, {"error": str(error)})
                return
            print(f"yt: {result['query']} -> {result['videoId']}", flush=True)
            self.respond_json(200, result)
            return
        if path == "/api/youtube-download":
            try:
                incoming = read_json_body(self, 12000, "請提供 YouTube 網址。")
                result = download_youtube_audio(
                    incoming.get("url"),
                    incoming.get("title"),
                    incoming.get("artist"),
                    incoming.get("browser"),
                )
            except SongListError as error:
                self.respond_json(400, {"error": str(error)})
                return
            skipped = " skip" if result.get("skipped") else ""
            print(f"dl{skipped}: {result['videoId']} -> {result['filename']}", flush=True)
            self.respond_json(200, result)
            return
        if path == "/api/open-audio-folder":
            length = int(self.headers.get("Content-Length") or "0")
            if length > 0:
                self.rfile.read(min(length, 8000))
            try:
                folder = open_audio_folder()
            except OSError as error:
                self.respond_json(400, {"error": f"無法打開資料夾：{error}"})
                return
            self.respond_json(200, {"ok": True, "folder": folder})
            return
        self.send_error(404)

    def respond_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}", flush=True)


def local_ips():
    names = {"127.0.0.1"}
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            names.add(info[4][0])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            names.add(sock.getsockname()[0])
    except OSError:
        pass
    return sorted(names)


def pids_listening(port):
    pids = set()
    me = os.getpid()
    parent = os.getppid()
    if os.name == "nt":
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        needle = f":{port}"
        for line in (completed.stdout or "").splitlines():
            if "LISTENING" not in line.upper() or needle not in line:
                continue
            parts = line.split()
            if not parts:
                continue
            try:
                pid = int(parts[-1])
            except ValueError:
                continue
            if pid not in {0, me, parent}:
                pids.add(pid)
        return sorted(pids)
    completed = subprocess.run(
        ["lsof", "-ti", f"tcp:{port}"],
        capture_output=True,
        text=True,
        check=False,
    )
    for raw in (completed.stdout or "").split():
        try:
            pid = int(raw)
        except ValueError:
            continue
        if pid not in {me, parent}:
            pids.add(pid)
    return sorted(pids)


def ask_close_old(pids, port):
    names = "、".join(str(pid) for pid in pids)
    message = (
        f"埠 {port} 還被舊程式佔用（PID {names}）。\n\n"
        "這通常是之前的「哈娜比77 歌單」還在背景跑。\n\n"
        "要關掉舊程式，改開新版「歌單轉入」嗎？"
    )
    print(message.replace("\n\n", "\n"), flush=True)
    if os.name == "nt":
        try:
            import ctypes
            # MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND
            result = ctypes.windll.user32.MessageBoxW(0, message, "歌單轉入", 4 | 32 | 0x10000)
            return result == 6
        except Exception:
            return True
    return True


def stop_pids(pids):
    for pid in pids:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            else:
                os.kill(pid, signal.SIGTERM)
            print(f"已結束舊程式 PID {pid}", flush=True)
        except OSError as error:
            print(f"無法結束 PID {pid}：{error}", flush=True)


def bind_server(host, start_port, tries=20):
    occupants = pids_listening(start_port)
    if occupants:
        if ask_close_old(occupants, start_port):
            stop_pids(occupants)
            time.sleep(0.8)
        else:
            print("已略過關閉舊程式，改試其他埠。", flush=True)
    last_error = None
    for port in range(start_port, start_port + tries):
        try:
            server = ThreadingHTTPServer((host, port), Handler)
            if port != start_port:
                print(f"注意：{start_port} 仍被占用，已改用 {port}。", flush=True)
            return server, port
        except OSError as error:
            last_error = error
            print(f"埠 {port} 無法使用，改試 {port + 1}…", flush=True)
    raise OSError(f"找不到可用埠（從 {start_port} 試了 {tries} 個）。最後錯誤：{last_error}") from last_error


def open_browser(port):
    url = f"http://127.0.0.1:{port}"
    try:
        webbrowser.open(url)
    except Exception as error:
        print(f"無法自動打開瀏覽器：{error}", flush=True)
        print(f"請手動打開 {url}", flush=True)


def main():
    ytdlp = find_ytdlp()
    if ytdlp:
        print(f"yt-dlp: {ytdlp}", flush=True)
    else:
        print("提醒：尚未找到 yt-dlp，YouTube 搜尋會失敗。啟動器會試著自動安裝。", flush=True)
    server, port = bind_server(HOST, PORT)
    print(f"歌單轉入 v{APP_VERSION}", flush=True)
    print(f"監聽 {HOST}:{port}", flush=True)
    print(f"請打開 http://127.0.0.1:{port}", flush=True)
    print("正確畫面標題是「歌單轉入」，不是「哈娜比77 歌單」。", flush=True)
    if HOST in {"0.0.0.0", "::"}:
        for ip in local_ips():
            if ip != "127.0.0.1":
                print(f"遠端／區網可試 http://{ip}:{port}", flush=True)
    if os.environ.get("GO_TO_KTV_NO_BROWSER", "").strip() not in {"1", "true", "yes"}:
        threading.Timer(0.6, lambda: open_browser(port)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
