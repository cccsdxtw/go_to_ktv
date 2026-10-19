#!/usr/bin/env python3
"""網頁工具：貼上 StreamerSonglist 歌單網址，或從表格轉成 Elitesand 歌單。"""

import html
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
APP_VERSION = "1.0.6"
_httpd = None
_bound_port = PORT
_released = False
ALLOWED_HOSTS = {"streamersonglist.com", "www.streamersonglist.com"}
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
KKBOX_HOSTS = {
    "kkbox.com",
    "www.kkbox.com",
    "play.kkbox.com",
    "open.kkbox.com",
    "widget.kkbox.com",
    "kkbox.fm",
}
KKBOX_PATH_RE = re.compile(
    r"^/(?:[a-z]{2}/[a-z]{2}/)?(playlist|album|song)/([^/?#]+)/?$",
    re.I,
)
SPOTIFY_HOSTS = {
    "open.spotify.com",
    "play.spotify.com",
    "spotify.link",
    "spotify.app.link",
}
SPOTIFY_URI_RE = re.compile(r"^spotify:(playlist|album|track):([A-Za-z0-9]{22})$", re.I)
SPOTIFY_PATH_RE = re.compile(
    r"^/(?:embed/)?(?:intl-[a-z]{2}/)?(playlist|album|track)/([A-Za-z0-9]{22})(?:/.*)?$",
    re.I,
)
PLAYLIST_YTDLP_TIMEOUT_SEC = 120
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{2,40}$")
PAGE_PATH_RE = re.compile(r"^/t/([A-Za-z0-9_]{2,40})(?:/songs)?/?$")
MAX_PAGES = 80
MAX_SONGS = 5000
YTDLP_TIMEOUT_SEC = 45
DOWNLOAD_TIMEOUT_SEC = 180
ELITESAND_TIMEOUT_SEC = 300
ELITESAND_PORTS = list(range(3000, 3011))
ELITESAND_VERSION_RE = re.compile(r"^\d+\.\d+")
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
        raise SongListError("這不是 streamersonglist.com 的歌單網址。")
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
        "sourceKind": "streamersonglist",
        "sourceLabel": "StreamerSonglist",
    }


def normalize_url(raw_url):
    text = str(raw_url or "").strip()
    if not text:
        raise SongListError("請貼上歌單網址。")
    uri = SPOTIFY_URI_RE.match(text)
    if uri:
        return f"https://open.spotify.com/{uri.group(1).lower()}/{uri.group(2)}"
    if "://" not in text:
        text = "https://" + text
    return text


def split_title_artist(raw):
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return "", ""
    parts = re.split(r"\s+[-–—]\s+", text, maxsplit=1)
    if len(parts) == 2:
        left, right = parts[0].strip(), parts[1].strip()
        if 1 < len(left) <= 80 and 1 < len(right) <= 80:
            return right, left
    return text, ""


def http_get_text(url, headers=None, timeout=25):
    request = urllib.request.Request(
        url,
        headers=headers
        or {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.geturl(), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise SongListError("找不到這個歌單，請確認網址。") from error
        raise SongListError("歌單網站暫時沒有回應，請稍後再試。") from error
    except urllib.error.URLError as error:
        raise SongListError("連不上歌單網站，請稍後再試。") from error


def parse_youtube_playlist_ref(raw_url):
    text = normalize_url(raw_url)
    parsed = urllib.parse.urlparse(text)
    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        return None
    query = urllib.parse.parse_qs(parsed.query)
    list_id = (query.get("list") or [""])[0].strip()
    mix = list_id.startswith("RD")
    if list_id and not mix:
        return {"kind": "youtube", "listId": list_id, "url": f"https://www.youtube.com/playlist?list={list_id}"}
    try:
        video_id, watch_url = parse_watch_url(text)
        return {"kind": "youtube", "videoId": video_id, "url": watch_url}
    except SongListError:
        if list_id:
            return {"kind": "youtube", "listId": list_id, "url": f"https://www.youtube.com/playlist?list={list_id}"}
        raise SongListError("請貼 YouTube 播放清單或單支影片網址。") from None


def parse_kkbox_ref(raw_url):
    text = normalize_url(raw_url)
    parsed = urllib.parse.urlparse(text)
    host = (parsed.hostname or "").lower()
    if host not in KKBOX_HOSTS:
        return None
    if host == "kkbox.fm":
        final_url, _body = http_get_text(text)
        parsed = urllib.parse.urlparse(final_url)
        host = (parsed.hostname or "").lower()
        text = final_url
    query = urllib.parse.parse_qs(parsed.query)
    item_id = (query.get("id") or [""])[0].strip()
    item_type = (query.get("type") or [""])[0].strip().lower()
    if not item_id:
        path = parsed.path or ""
        play = re.match(r"^/(playlist|album|song)/([^/?#]+)/?$", path, re.I)
        match = play or KKBOX_PATH_RE.match(path)
        if not match:
            raise SongListError("請貼 KKBOX 歌單、專輯或歌曲網址。")
        item_type = match.group(1).lower()
        item_id = match.group(2)
    if item_type not in {"playlist", "album", "song"}:
        item_type = "playlist"
    if not item_id:
        raise SongListError("請貼 KKBOX 歌單、專輯或歌曲網址。")
    return {"kind": "kkbox", "itemType": item_type, "itemId": item_id, "url": text}


def parse_spotify_ref(raw_url):
    text = normalize_url(raw_url)
    parsed = urllib.parse.urlparse(text)
    host = (parsed.hostname or "").lower()
    if host not in SPOTIFY_HOSTS:
        return None
    if host in {"spotify.link", "spotify.app.link"}:
        final_url, _body = http_get_text(text)
        parsed = urllib.parse.urlparse(final_url)
        text = final_url
    match = SPOTIFY_PATH_RE.match(parsed.path or "")
    if not match:
        raise SongListError("請貼 Spotify 歌單、專輯或歌曲網址。")
    return {
        "kind": "spotify",
        "itemType": match.group(1).lower(),
        "itemId": match.group(2),
        "url": text,
    }


def detect_playlist(raw_url):
    text = normalize_url(raw_url)
    parsed = urllib.parse.urlparse(text)
    host = (parsed.hostname or "").lower()
    if host in ALLOWED_HOSTS:
        return {"kind": "streamersonglist", "username": parse_username(text), "url": text}
    youtube = parse_youtube_playlist_ref(text)
    if youtube:
        return youtube
    kkbox = parse_kkbox_ref(text)
    if kkbox:
        return kkbox
    spotify = parse_spotify_ref(text)
    if spotify:
        return spotify
    raise SongListError(
        "目前支援 StreamerSonglist、YouTube 播放清單／單支影片、KKBOX、Spotify 歌單／專輯／歌曲。請貼其中一種網址。"
    )


def ytdlp_dump_json(url):
    ytdlp = find_ytdlp()
    if not ytdlp:
        raise SongListError("找不到 yt-dlp。請先執行：pip install yt-dlp")
    command = [
        ytdlp,
        url,
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        "--skip-download",
        "--yes-playlist",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PLAYLIST_YTDLP_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise SongListError("YouTube 播放清單讀取逾時，請稍後再試。") from error
    except OSError as error:
        raise SongListError("無法啟動 yt-dlp。") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        message = detail[-1] if detail else "YouTube 播放清單讀取失敗。"
        raise SongListError(message[:240])
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise SongListError("YouTube 播放清單無法讀取。") from error
    if not isinstance(payload, dict):
        raise SongListError("YouTube 播放清單無法讀取。")
    return payload


def songs_from_youtube_payload(payload, source_url):
    entries = payload.get("entries")
    if not isinstance(entries, list):
        entries = [payload] if payload.get("id") else []
    songs = []
    for index, item in enumerate(entries, start=1):
        if not isinstance(item, dict):
            continue
        video_id = str(item.get("id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,18}", video_id):
            continue
        raw_title = str(item.get("title") or "").strip() or f"未命名 {index}"
        title, artist = split_title_artist(raw_title)
        if not artist:
            channel = str(item.get("uploader") or item.get("channel") or "").strip()
            channel = re.sub(r"\s*-\s*Topic$", "", channel).strip()
            artist = channel
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        songs.append(
            {
                "id": f"yt-{video_id}",
                "title": title or raw_title,
                "artist": artist,
                "attributes": ["YouTube"],
                "lastPlayed": "",
                "timesPlayed": 0,
                "youtubeUrl": watch_url,
                "videoId": video_id,
                "youtubeTitle": raw_title,
            }
        )
        if len(songs) >= MAX_SONGS:
            break
    if not songs:
        raise SongListError("這個 YouTube 網址裡沒有可讀的影片。")
    display = str(payload.get("title") or "").strip() or "YouTube 播放清單"
    username = str(payload.get("id") or "youtube-playlist")
    return {
        "username": username,
        "displayName": display,
        "total": len(songs),
        "songs": songs,
        "sourceUrl": source_url,
        "sourceKind": "youtube",
        "sourceLabel": "YouTube",
    }


def fetch_youtube_playlist(raw_url):
    ref = parse_youtube_playlist_ref(raw_url)
    payload = ytdlp_dump_json(ref["url"])
    return songs_from_youtube_payload(payload, ref["url"])


def kkbox_tracks_from_widget(data):
    songs = []
    if isinstance(data.get("song_name"), str) and data.get("song_name").strip():
        rows = [data]
        display = data.get("song_name")
    else:
        rows = data.get("songlist") if isinstance(data.get("songlist"), list) else []
        display = data.get("playlist_title") or data.get("album_name") or "KKBOX 歌單"
    for index, item in enumerate(rows, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("song_name") or "").strip()
        artist = str(item.get("artist_name") or "").strip()
        if not artist:
            names = item.get("artist_names")
            if isinstance(names, list):
                artist = "、".join(str(name).strip() for name in names if str(name).strip())
            elif isinstance(names, str):
                artist = names.strip()
        if not title:
            continue
        song_id = str(item.get("song_crypt_id") or item.get("song_id") or index)
        songs.append(
            {
                "id": f"kkbox-{song_id}",
                "title": title,
                "artist": artist,
                "attributes": ["KKBOX"],
                "lastPlayed": "",
                "timesPlayed": 0,
            }
        )
        if len(songs) >= MAX_SONGS:
            break
    if not songs:
        raise SongListError("這個 KKBOX 網址裡沒有可讀的歌曲。")
    return str(display or "KKBOX 歌單").strip(), songs


def fetch_kkbox_playlist(raw_url):
    ref = parse_kkbox_ref(raw_url)
    widget = f"https://widget.kkbox.com/v1/?id={urllib.parse.quote(ref['itemId'])}&type={urllib.parse.quote(ref['itemType'])}"
    _final, body = http_get_text(widget)
    match = re.search(r'data-state="([^"]+)"', body)
    if not match:
        raise SongListError("KKBOX 歌單讀不到內容。請確認是公開歌單／專輯網址。")
    raw_state = html.unescape(match.group(1))
    try:
        state = json.loads(raw_state)
    except json.JSONDecodeError as error:
        raise SongListError("KKBOX 歌單資料無法讀取。") from error
    data = state.get("feed", {}).get("data") if isinstance(state, dict) else None
    if not isinstance(data, dict):
        raise SongListError("找不到這個 KKBOX 歌單，請確認網址。")
    display, songs = kkbox_tracks_from_widget(data)
    return {
        "username": ref["itemId"],
        "displayName": display,
        "total": len(songs),
        "songs": songs,
        "sourceUrl": ref["url"],
        "sourceKind": "kkbox",
        "sourceLabel": "KKBOX",
    }


def spotify_artist_text(item):
    subtitle = str(item.get("subtitle") or "").replace("\xa0", " ").strip()
    if subtitle:
        return subtitle
    artists = item.get("artists")
    if isinstance(artists, list):
        names = []
        for artist in artists:
            if isinstance(artist, dict) and artist.get("name"):
                names.append(str(artist["name"]).strip())
            elif isinstance(artist, str) and artist.strip():
                names.append(artist.strip())
        return "、".join(names)
    return ""


def songs_from_spotify_entity(entity, source_url, item_id):
    if not isinstance(entity, dict):
        raise SongListError("找不到這個 Spotify 歌單，請確認網址是公開的。")
    rows = entity.get("trackList")
    if not isinstance(rows, list) or not rows:
        title = str(entity.get("title") or entity.get("name") or "").strip()
        if title:
            rows = [entity]
        else:
            rows = []
    songs = []
    for index, item in enumerate(rows, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        if not title:
            continue
        uri = str(item.get("uri") or "")
        track_id = ""
        match = re.search(r"spotify:track:([A-Za-z0-9]{22})", uri)
        if match:
            track_id = match.group(1)
        elif re.fullmatch(r"[A-Za-z0-9]{22}", str(item.get("id") or "")):
            track_id = str(item.get("id"))
        else:
            track_id = str(index)
        songs.append(
            {
                "id": f"spotify-{track_id}",
                "title": title,
                "artist": spotify_artist_text(item),
                "attributes": ["Spotify"],
                "lastPlayed": "",
                "timesPlayed": 0,
            }
        )
        if len(songs) >= MAX_SONGS:
            break
    if not songs:
        raise SongListError("這個 Spotify 網址裡沒有可讀的歌曲。請確認歌單是公開的。")
    display = str(entity.get("title") or entity.get("name") or "Spotify 歌單").strip()
    return {
        "username": item_id,
        "displayName": display,
        "total": len(songs),
        "songs": songs,
        "sourceUrl": source_url,
        "sourceKind": "spotify",
        "sourceLabel": "Spotify",
    }


def fetch_spotify_playlist(raw_url):
    ref = parse_spotify_ref(raw_url)
    embed = f"https://open.spotify.com/embed/{ref['itemType']}/{ref['itemId']}"
    _final, body = http_get_text(embed)
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', body, re.S)
    if not match:
        raise SongListError("Spotify 歌單讀不到內容。請確認是公開歌單／專輯網址。")
    try:
        state = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise SongListError("Spotify 歌單資料無法讀取。") from error
    entity = (
        state.get("props", {})
        .get("pageProps", {})
        .get("state", {})
        .get("data", {})
        .get("entity")
        if isinstance(state, dict)
        else None
    )
    return songs_from_spotify_entity(entity, ref["url"], ref["itemId"])


def import_playlist(raw_url):
    detected = detect_playlist(raw_url)
    kind = detected["kind"]
    if kind == "streamersonglist":
        return fetch_songs(detected["username"])
    if kind == "youtube":
        return fetch_youtube_playlist(detected["url"])
    if kind == "kkbox":
        return fetch_kkbox_playlist(detected["url"])
    if kind == "spotify":
        return fetch_spotify_playlist(detected["url"])
    raise SongListError("不支援這個歌單來源。")


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
    r"could not copy|database is locked|failed to load cookies|unable to find|no such file|profile",
    re.I,
)
_working_ytdlp = {"browser": None, "extractor": None}


def reset_ytdlp_auth():
    _working_ytdlp["browser"] = None
    _working_ytdlp["extractor"] = None


def normalize_browser(value):
    raw = str(value or "").strip()
    if ":" in raw:
        browser, profile = raw.split(":", 1)
    else:
        browser, profile = raw, ""
    browser = browser.strip().lower().replace(" ", "-")
    aliases = {
        "msedge": "edge",
        "microsoft-edge": "edge",
        "google-chrome": "chrome",
        "googlechrome": "chrome",
    }
    browser = aliases.get(browser, browser)
    profile = profile.strip()
    if browser not in COOKIE_BROWSERS:
        return ""
    if profile:
        return f"{browser}:{profile}"
    return browser


def ytdlp_output_text(completed):
    return ((getattr(completed, "stderr", None) or "") + "\n" + (getattr(completed, "stdout", None) or "")).strip()


def is_bot_block(text):
    return bool(BOT_ERROR_RE.search(text or ""))


def friendly_download_error(text, tried_cookies=False):
    locked = bool(COOKIE_LOCK_RE.search(text or ""))
    if not tried_cookies and (is_bot_block(text) or locked):
        return (
            "YouTube 把自動化下載擋住了。"
            "那些免登入網站也不是用你的帳號，是網站伺服器假裝成瀏覽器去抓。"
            "這個工具已改成本機模擬 Chrome，預設仍不讀你的 Google 帳號。"
            "若還是失敗，多半是這台電腦的網路被 YouTube 標成機器人。"
        )
    if is_bot_block(text) or tried_cookies or locked:
        return (
            "專用帳號仍被擋。請用下載專用 Google 帳號登入後，把該瀏覽器關乾淨再試。"
            "Cookie 只在這台電腦給 yt-dlp 用，不會傳到網路上。"
        )
    detail = (text or "").strip().splitlines()
    return (detail[-1] if detail else "音檔下載失敗。")[:240]


def browser_user_data(browser):
    browser = normalize_browser(browser).split(":")[0]
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
    if os.name == "nt":
        mapping = {
            "chrome": local / "Google" / "Chrome" / "User Data",
            "edge": local / "Microsoft" / "Edge" / "User Data",
            "brave": local / "BraveSoftware" / "Brave-Browser" / "User Data",
            "chromium": local / "Chromium" / "User Data",
        }
    elif sys.platform == "darwin":
        mapping = {
            "chrome": home / "Library" / "Application Support" / "Google" / "Chrome",
            "edge": home / "Library" / "Application Support" / "Microsoft Edge",
            "brave": home / "Library" / "Application Support" / "BraveSoftware" / "Brave-Browser",
            "chromium": home / "Library" / "Application Support" / "Chromium",
            "firefox": home / "Library" / "Application Support" / "Firefox",
            "safari": home / "Library" / "Safari",
        }
    else:
        mapping = {
            "chrome": home / ".config" / "google-chrome",
            "edge": home / ".config" / "microsoft-edge",
            "brave": home / ".config" / "BraveSoftware" / "Brave-Browser",
            "chromium": home / ".config" / "chromium",
            "firefox": home / ".mozilla" / "firefox",
        }
    return mapping.get(browser)


def browser_profiles(browser):
    root = browser_user_data(browser)
    names = []
    if root and root.is_dir():
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in {"Default", "Guest Profile", "System Profile"} or entry.name.startswith("Profile "):
                if (entry / "Cookies").is_file() or (entry / "Network" / "Cookies").is_file() or (entry / "Preferences").is_file():
                    names.append(entry.name)
    if "Default" not in names:
        names.insert(0, "Default")
    # Default 先試
    names.sort(key=lambda item: (0 if item == "Default" else 1, item))
    return names


def cookie_specs(preferred=""):
    specs = []
    preferred = normalize_browser(preferred) or normalize_browser(os.environ.get("GO_TO_KTV_BROWSER", "")) or "chrome"
    base = preferred.split(":")[0]
    if ":" in preferred:
        specs.append(preferred)
    for profile in browser_profiles(base):
        specs.append(f"{base}:{profile}")
    specs.append(base)
    if base != "edge":
        specs.append("edge")
        specs.append("edge:Default")
    unique = []
    seen = set()
    for spec in specs:
        spec = normalize_browser(spec) or spec
        if spec and spec not in seen:
            seen.add(spec)
            unique.append(spec)
    return unique[:6]


def curl_cffi_available():
    try:
        import curl_cffi  # noqa: F401
        return True
    except ImportError:
        return False


def impersonate_client(cookie_browser=None):
    # 跟免登入網站同一招：模擬真實瀏覽器的 TLS，不讀你的 Google 帳號。
    if cookie_browser or not curl_cffi_available():
        return None
    if os.name == "nt":
        return "chrome"
    return "chrome"


def run_ytdlp(command, timeout, cookie_browser=None, extractor=None):
    cmd = list(command)
    if "--remote-components" not in cmd:
        cmd.extend(["--remote-components", "ejs:github"])
    impersonate = impersonate_client(cookie_browser)
    if impersonate:
        cmd.extend(["--impersonate", impersonate])
    if extractor:
        cmd.extend(["--extractor-args", extractor])
    if cookie_browser:
        cmd.extend(["--cookies-from-browser", cookie_browser])
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    text = ytdlp_output_text(completed)
    if impersonate and completed.returncode != 0 and "Impersonate target" in text:
        cmd = [part for part in cmd if part not in {"--impersonate", impersonate}]
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    return completed


def download_attempts(preferred_browser="", use_cookies=False):
    extractors = (
        "youtube:player_client=tv_embedded,tv",
        "youtube:player_client=web_safari",
        "youtube:player_client=android,ios",
        "youtube:player_client=web,mweb",
    )
    attempts = []
    working = (_working_ytdlp.get("browser"), _working_ytdlp.get("extractor"))
    if working[1] and (use_cookies or not working[0]):
        attempts.append(working)
    if use_cookies:
        for spec in cookie_specs(preferred_browser):
            attempts.append((spec, "youtube:player_client=web,mweb"))
            attempts.append((spec, "youtube:player_client=tv_embedded,tv"))
    else:
        for extractor in extractors:
            attempts.append((None, extractor))
    unique = []
    seen = set()
    for item in attempts:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique[:8]


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


def ranked_youtube_entries(entries):
    candidates = [item for item in entries if isinstance(item, dict) and item.get("id")]
    return [
        item
        for _, item in sorted(
            enumerate(candidates),
            key=lambda pair: (-instrumental_score(pair[1]), pair[0]),
        )
    ]


def pick_youtube_entry(entries):
    ranked = ranked_youtube_entries(entries)
    return ranked[0] if ranked else None


def youtube_candidate(item):
    video_id = str(item.get("id") or "")
    return {
        "videoId": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "youtubeTitle": item.get("title") or "",
        "uploader": item.get("uploader") or item.get("channel") or "",
        "duration": item.get("duration"),
    }


def parse_ytdlp_search_output(stdout):
    text = str(stdout or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            entries = payload.get("entries")
            if isinstance(entries, list):
                return [item for item in entries if isinstance(item, dict)]
            if payload.get("id"):
                return [payload]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
    except json.JSONDecodeError:
        pass
    found = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("id"):
            found.append(item)
    return found


def search_youtube(title, artist):
    ytdlp = find_ytdlp()
    if not ytdlp:
        raise SongListError("找不到 yt-dlp。請先執行：pip install yt-dlp")
    query = build_search_query(title, artist)
    command = [
        ytdlp,
        f"ytsearch5:{query}",
        "--flat-playlist",
        "--skip-download",
        "--no-warnings",
        "--print",
        "%(.{id,title,channel,uploader,duration})j",
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
    ranked = ranked_youtube_entries(parse_ytdlp_search_output(completed.stdout))
    candidates = [youtube_candidate(item) for item in ranked if item.get("id")]
    if not candidates:
        raise SongListError("找不到這首歌的 YouTube 結果。")
    picked = candidates[0]
    return {
        "videoId": picked["videoId"],
        "url": picked["url"],
        "youtubeTitle": picked["youtubeTitle"],
        "uploader": picked["uploader"],
        "duration": picked["duration"],
        "candidates": candidates[:5],
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


def download_youtube_audio(raw_url, title, artist, browser="", use_cookies=False):
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
    if not use_cookies:
        browser = ""
    for cookie_browser, extractor in download_attempts(browser, use_cookies=use_cookies):
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


def elitesand_base_override():
    raw = os.environ.get("GO_TO_KTV_ELITESAND", "").strip().rstrip("/")
    return raw or ""


def elitesand_json(url, timeout=0.8, pin=""):
    headers = {"Accept": "application/json", "User-Agent": "go-to-ktv"}
    if pin:
        headers["X-Pin"] = str(pin).strip()
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return None
    if isinstance(payload, (dict, list)):
        return payload
    return None


def is_elitesand_health(payload):
    """Elitesand Pro /api/health 獨有：status、數字版本、timestamp、portFallbackFrom。"""
    if not isinstance(payload, dict):
        return False
    if payload.get("status") != "ok":
        return False
    if "portFallbackFrom" not in payload:
        return False
    if not isinstance(payload.get("timestamp"), (int, float)):
        return False
    version = str(payload.get("version") or "").strip()
    if version.lower() == "mock" or not ELITESAND_VERSION_RE.match(version):
        return False
    return True


def is_elitesand_obs_launcher(payload):
    if not isinstance(payload, dict):
        return False
    blob = json.dumps(payload.get("files") or {}, ensure_ascii=False)
    return "Elitesand-Pro" in blob or "elitesand-pro" in blob.lower()


def probe_elitesand(base):
    health = elitesand_json(f"{base}/api/health")
    if not is_elitesand_health(health):
        return None
    if not is_elitesand_obs_launcher(elitesand_json(f"{base}/api/obs-launcher")):
        return None
    try:
        probed_port = int(urllib.parse.urlparse(base).port or "0")
    except (TypeError, ValueError):
        probed_port = 0
    reported = health.get("port")
    try:
        reported_port = int(reported) if reported is not None else probed_port
    except (TypeError, ValueError):
        reported_port = probed_port
    return {
        "ok": True,
        "base": base,
        "port": reported_port,
        "version": str(health.get("version") or ""),
        "portMatch": reported_port == probed_port,
    }


def find_elitesand():
    override = elitesand_base_override()
    bases = [override] if override else [f"http://127.0.0.1:{port}" for port in ELITESAND_PORTS]
    hits = []
    for base in bases:
        found = probe_elitesand(base)
        if found:
            hits.append(found)
    if not hits:
        return None
    hits.sort(key=lambda item: (bool(item.get("portMatch")), int(item.get("port") or 0)), reverse=True)
    return hits[0]


def is_stub_elitesand_track(track):
    filename = str((track or {}).get("filename") or "").strip().lower()
    title = str((track or {}).get("title") or "").strip().lower()
    return filename == "mock.mp3" or title == "mock track"


_elitesand_sio = None
_elitesand_sio_base = ""
_elitesand_sio_lock = threading.Lock()


def elitesand_socket_disconnect():
    global _elitesand_sio, _elitesand_sio_base
    client = _elitesand_sio
    _elitesand_sio = None
    _elitesand_sio_base = ""
    if client is None:
        return
    try:
        client.disconnect()
    except Exception:
        pass


def elitesand_controller_socket(found, pin=""):
    """以本機 controller 連 Elitesand 的 socket.io，才能改目前播放清單。"""
    global _elitesand_sio, _elitesand_sio_base
    try:
        import socketio
    except ImportError as error:
        raise SongListError("缺少 python-socketio。請再雙擊一次「開始」讓它自動安裝套件。") from error
    base = found["base"]
    pin = str(pin or "").strip()
    with _elitesand_sio_lock:
        if _elitesand_sio is not None and _elitesand_sio_base == base and getattr(_elitesand_sio, "connected", False):
            return _elitesand_sio
        elitesand_socket_disconnect()
        client = socketio.Client(reconnection=False, logger=False, engineio_logger=False)
        auth = {"clientType": "controller"}
        if pin:
            auth["pin"] = pin
        try:
            client.connect(
                base,
                auth=auth,
                transports=["websocket", "polling"],
                wait_timeout=8,
                socketio_path="socket.io",
            )
        except Exception as error:
            raise SongListError("連不上 Elitesand 播放清單通道。請確認 Elitesand 視窗還開著。") from error
        _elitesand_sio = client
        _elitesand_sio_base = base
        return client


def track_for_playlist(raw, video_id, watch_url, title="", artist=""):
    track = dict(raw) if isinstance(raw, dict) else {}
    if not track.get("id"):
        track["id"] = video_id
    if not track.get("url"):
        track["url"] = watch_url
    if not track.get("source"):
        track["source"] = "youtube"
    preferred_title = str(title or "").strip()
    preferred_artist = str(artist or "").strip()
    if preferred_title:
        track["title"] = preferred_title
    if preferred_artist:
        track["artist"] = preferred_artist
        track["artistConfidence"] = 1
        track["needsArtistConfirmation"] = False
    return track


def elitesand_attach_to_playlist(found, track, pin=""):
    """媒體庫下載後，把這首掛上目前播放清單（取代同 id 的音檔遺失列）。"""
    if not isinstance(track, dict) or not track.get("id"):
        raise SongListError("Elitesand 回傳的歌曲不完整，無法加入播放清單。")
    client = elitesand_controller_socket(found, pin)
    try:
        client.emit("playlist:remove", track.get("id"))
        result = client.call("playlist:add", [track], timeout=12)
    except Exception as error:
        elitesand_socket_disconnect()
        raise SongListError(f"音檔已進媒體庫，但沒掛上播放清單：{error}") from error
    if isinstance(result, dict) and result.get("ok") is False:
        raise SongListError(str(result.get("error") or "無法加入 Elitesand 播放清單。"))
    return True


def elitesand_import_youtube(raw_url, pin="", title="", artist=""):
    found = find_elitesand()
    if not found:
        raise SongListError("找不到 Elitesand Pro。請先打開它；本工具會認它的健康檢查與 /api/obs-launcher。若 3000 被佔，它會在 3001–3010。")
    _video_id, watch_url = parse_watch_url(raw_url)
    body = json.dumps({"url": watch_url, "isBatch": True}).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "go-to-ktv",
    }
    pin = str(pin or "").strip()
    if pin:
        headers["X-Pin"] = pin
    request = urllib.request.Request(
        f"{found['base']}/api/youtube",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=ELITESAND_TIMEOUT_SEC) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"error": raw[:200] or f"Elitesand 回傳 {error.code}"}
        status = error.code
    except urllib.error.URLError as error:
        raise SongListError("連不上 Elitesand，請確認程式還開著。") from error
    except TimeoutError as error:
        raise SongListError("Elitesand 下載逾時，請稍後再試。") from error
    if not isinstance(payload, dict):
        raise SongListError("Elitesand 回傳無法讀取。")
    if status == 401 or payload.get("code") == "PIN_REQUIRED":
        raise SongListError("Elitesand 需要 PIN。請在欄位填入 PIN 後再送。")
    skipped = False
    track = {}
    if payload.get("code") == "DUPLICATE_SONG":
        skipped = True
        track = payload.get("existing") or {}
    elif status >= 400 or not payload.get("success"):
        raise SongListError(str(payload.get("error") or "Elitesand 下載失敗。")[:240])
    else:
        track = payload.get("track") or {}
        if is_stub_elitesand_track(track):
            raise SongListError("連到的不是 Elitesand Pro（假服務／測試回應）。請關掉佔用 3000 的舊程式，只留 Elitesand 視窗再開一次。")
    track = track_for_playlist(track, _video_id, watch_url, title, artist)
    elitesand_attach_to_playlist(found, track, pin)
    return {
        "skipped": skipped,
        "playlistOk": True,
        "title": track.get("title") or "",
        "filename": track.get("filename") or "",
        "id": track.get("id") or "",
        "elitesand": found["base"],
        "version": found.get("version") or "",
    }


def normalize_song_key(title, artist=""):
    title_text = re.sub(r"\s+", " ", str(title or "")).strip().lower()
    artist_text = re.sub(r"\s+", " ", str(artist or "")).strip().lower()
    return f"{title_text}|{artist_text}"


def extract_track_list(payload):
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("songs", "tracks", "items", "library", "media", "data", "results"):
        value = payload.get(key)
        found = extract_track_list(value)
        if found:
            return found
    if payload.get("title") or payload.get("filename") or payload.get("id") or payload.get("url"):
        return [payload]
    return []


def track_video_id(track):
    if not isinstance(track, dict):
        return ""
    raw_id = str(track.get("id") or track.get("videoId") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{6,18}", raw_id):
        return raw_id
    for raw in (track.get("url"), track.get("youtubeUrl"), track.get("sourceUrl")):
        try:
            video_id, _watch = parse_watch_url(raw)
            return video_id
        except SongListError:
            continue
    return ""


def summarize_elitesand_track(track):
    video_id = track_video_id(track)
    title = str(track.get("title") or track.get("name") or "").strip()
    artist = str(track.get("artist") or track.get("uploader") or "").strip()
    return {
        "id": str(track.get("id") or video_id or ""),
        "videoId": video_id,
        "url": str(track.get("url") or ""),
        "title": title,
        "artist": artist,
        "filename": str(track.get("filename") or ""),
        "key": normalize_song_key(title, artist),
    }


def elitesand_library_tracks(found, pin=""):
    if not found:
        return []
    pin = str(pin or "").strip()
    seen = []
    used = set()
    for path in (
        "/api/library",
        "/api/songs",
        "/api/tracks",
        "/api/media",
        "/api/library/songs",
        "/api/media/songs",
    ):
        payload = elitesand_json(f"{found['base']}{path}", timeout=1.5, pin=pin)
        for track in extract_track_list(payload):
            item = summarize_elitesand_track(track)
            marker = item["videoId"] or item["key"] or item["filename"]
            if not marker or marker in used:
                continue
            used.add(marker)
            seen.append(item)
        if seen:
            return seen
    try:
        client = elitesand_controller_socket(found, pin)
        for event in ("library:list", "library:get", "songs:list"):
            try:
                payload = client.call(event, timeout=4)
            except Exception:
                continue
            for track in extract_track_list(payload):
                item = summarize_elitesand_track(track)
                marker = item["videoId"] or item["key"] or item["filename"]
                if not marker or marker in used:
                    continue
                used.add(marker)
                seen.append(item)
            if seen:
                return seen
    except SongListError:
        return seen
    return seen


def fetch_elitesand_library(pin=""):
    found = find_elitesand()
    if not found:
        return {"ok": False, "tracks": []}
    tracks = elitesand_library_tracks(found, pin)
    return {
        "ok": True,
        "base": found["base"],
        "count": len(tracks),
        "tracks": tracks,
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
        if path == "/api/elitesand-status":
            found = find_elitesand()
            self.respond_json(200, found or {"ok": False})
            return
        self.send_error(404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/songs":
            try:
                incoming = read_json_body(self, 4000, "請貼上歌單網址。")
                result = import_playlist(incoming.get("url"))
            except SongListError as error:
                self.respond_json(400, {"error": str(error)})
                return
            print(f"{result.get('sourceKind')}: {result.get('displayName')}: {len(result['songs'])} songs", flush=True)
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
                    bool(incoming.get("useCookies")),
                )
            except SongListError as error:
                self.respond_json(400, {"error": str(error)})
                return
            skipped = " skip" if result.get("skipped") else ""
            print(f"dl{skipped}: {result['videoId']} -> {result['filename']}", flush=True)
            self.respond_json(200, result)
            return
        if path == "/api/elitesand-library":
            pin = ""
            length = int(self.headers.get("Content-Length") or "0")
            if length > 0:
                try:
                    incoming = read_json_body(self, 4000, "請提供 JSON。")
                    pin = incoming.get("pin") or ""
                except SongListError:
                    pin = ""
            self.respond_json(200, fetch_elitesand_library(pin))
            return
        if path == "/api/elitesand-import":
            try:
                incoming = read_json_body(self, 12000, "請提供 YouTube 網址。")
                result = elitesand_import_youtube(
                    incoming.get("url"),
                    incoming.get("pin"),
                    incoming.get("title"),
                    incoming.get("artist"),
                )
            except SongListError as error:
                self.respond_json(400, {"error": str(error)})
                return
            skipped = " skip" if result.get("skipped") else ""
            print(f"es{skipped}: {result.get('title') or ''} -> {result.get('filename')}", flush=True)
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
        if path == "/api/shutdown":
            length = int(self.headers.get("Content-Length") or "0")
            if length > 0:
                self.rfile.read(min(length, 8000))
            self.respond_json(
                200,
                {"ok": True, "released": f"http://127.0.0.1:{_bound_port}"},
            )
            schedule_shutdown()
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
        f"http://127.0.0.1:{port} 還被上一份「歌單轉入」佔著（PID {names}）。\n\n"
        "用完應按網頁上的「結束程式」，或關掉那個黑色視窗，這個位置才會讓出來。\n\n"
        "現在要結束舊的、讓這一份接手嗎？（下次請先結束，就不必再頂）"
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


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def schedule_shutdown():
    def _stop():
        time.sleep(0.2)
        stop_http()

    threading.Thread(target=_stop, daemon=True).start()


def stop_http():
    global _released
    httpd = _httpd
    if httpd is None or _released:
        return
    _released = True
    print(f"已結束，http://127.0.0.1:{_bound_port} 已讓出。", flush=True)
    try:
        httpd.shutdown()
    except Exception:
        pass
    try:
        httpd.server_close()
    except OSError:
        pass


def bind_server(host, start_port, tries=20):
    occupants = pids_listening(start_port)
    if occupants:
        if ask_close_old(occupants, start_port):
            stop_pids(occupants)
            time.sleep(0.8)
        else:
            print("已略過結束舊程式，改試其他埠。下次請先結束上一份，讓 8765 空出來。", flush=True)
    last_error = None
    for port in range(start_port, start_port + tries):
        try:
            server = AppServer((host, port), Handler)
            if port != start_port:
                print(f"注意：{start_port} 仍被占用，已改用 {port}。", flush=True)
            return server, port
        except OSError as error:
            last_error = error
            print(f"埠 {port} 無法使用，改試 {port + 1}…", flush=True)
    raise OSError(f"找不到可用埠（從 {start_port} 試了 {tries} 個）。最後錯誤：{last_error}") from last_error


def windows_app_browsers():
    paths = [
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
    ]
    found = []
    for path in paths:
        if path and os.path.isfile(path) and path not in found:
            found.append(path)
    for name in ("chrome.exe", "msedge.exe"):
        which = shutil.which(name)
        if which and which not in found:
            found.append(which)
    return found


def mac_app_browsers():
    names = ("Google Chrome", "Microsoft Edge", "Chromium")
    found = []
    roots = (Path("/Applications"), Path.home() / "Applications")
    for name in names:
        if any((root / f"{name}.app").is_dir() for root in roots):
            found.append(name)
    return found


def open_closeable_window(url):
    """用 Chrome／Edge 的 --app 視窗打開，結束時才關得掉這個頁。"""
    try:
        if sys.platform.startswith("win"):
            for exe in windows_app_browsers():
                subprocess.Popen(
                    [exe, f"--app={url}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
        elif sys.platform == "darwin":
            for name in mac_app_browsers():
                subprocess.Popen(
                    ["open", "-na", name, "--args", f"--app={url}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
        else:
            for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
                exe = shutil.which(name)
                if not exe:
                    continue
                subprocess.Popen(
                    [exe, f"--app={url}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
    except OSError:
        return False
    return False


def open_browser(port):
    url = f"http://127.0.0.1:{port}"
    try:
        if open_closeable_window(url):
            return
        webbrowser.open(url)
    except Exception as error:
        print(f"無法自動打開瀏覽器：{error}", flush=True)
        print(f"請手動打開 {url}", flush=True)


def main():
    global _httpd, _bound_port
    ytdlp = find_ytdlp()
    if ytdlp:
        print(f"yt-dlp: {ytdlp}", flush=True)
    else:
        print("提醒：尚未找到 yt-dlp，YouTube 搜尋會失敗。啟動器會試著自動安裝。", flush=True)
    server, port = bind_server(HOST, PORT)
    _httpd = server
    _bound_port = port
    print(f"歌單轉入 v{APP_VERSION}", flush=True)
    print(f"監聽 {HOST}:{port}", flush=True)
    print(f"請打開 http://127.0.0.1:{port}", flush=True)
    print("用完請按網頁「結束程式」，或關掉這個視窗，8765 才會讓出來。只關瀏覽器分頁是不夠的。", flush=True)
    if HOST in {"0.0.0.0", "::"}:
        for ip in local_ips():
            if ip != "127.0.0.1":
                print(f"遠端／區網可試 http://{ip}:{port}", flush=True)
    if os.environ.get("GO_TO_KTV_NO_BROWSER", "").strip() not in {"1", "true", "yes"}:
        threading.Timer(0.6, lambda: open_browser(port)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_http()


if __name__ == "__main__":
    main()
