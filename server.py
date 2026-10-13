#!/usr/bin/env python3
"""網頁工具：貼上 StreamerSonglist 歌單網址，或從表格轉成 Elitesand 歌單。"""

import json
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765
ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
ALLOWED_HOSTS = {"streamersonglist.com", "www.streamersonglist.com"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{2,40}$")
PAGE_PATH_RE = re.compile(r"^/t/([A-Za-z0-9_]{2,40})(?:/songs)?/?$")
MAX_PAGES = 80
MAX_SONGS = 5000
YTDLP_TIMEOUT_SEC = 45

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
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/health":
            ytdlp = find_ytdlp()
            self.respond_json(
                200,
                {
                    "ok": True,
                    "ytdlp": bool(ytdlp),
                    "ytdlpPath": ytdlp,
                    "version": "0.3.1",
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


def main():
    ytdlp = find_ytdlp()
    if ytdlp:
        print(f"yt-dlp: {ytdlp}", flush=True)
    else:
        print("提醒：尚未找到 yt-dlp，YouTube 搜尋會失敗。請執行 pip install yt-dlp", flush=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"打開 http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
