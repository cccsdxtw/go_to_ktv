#!/usr/bin/env python3
"""本機小測試：檔名、YouTube 網址解析、下載 API 拒絕無效網址。"""

import io
import json
import os
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

import server


class FilenameTests(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(server.sanitize_for_filename('A/B:C*'), "A B C")

    def test_build_track_filename(self):
        self.assertEqual(
            server.build_track_filename("DAOKO", "打上花火", ".mp3"),
            "DAOKO - 打上花火.mp3",
        )
        self.assertEqual(server.build_track_filename("", "  ", "mp3"), "未知歌曲.mp3")


class YoutubeUrlTests(unittest.TestCase):
    def test_watch(self):
        video_id, url = server.parse_watch_url("https://www.youtube.com/watch?v=lOL3CEton6E")
        self.assertEqual(video_id, "lOL3CEton6E")
        self.assertEqual(url, "https://www.youtube.com/watch?v=lOL3CEton6E")

    def test_short(self):
        video_id, url = server.parse_watch_url("https://youtu.be/lOL3CEton6E")
        self.assertEqual(video_id, "lOL3CEton6E")
        self.assertIn("watch?v=lOL3CEton6E", url)

    def test_reject_other_host(self):
        with self.assertRaises(server.SongListError):
            server.parse_watch_url("https://streamersonglist.com/t/x/songs")


class UniquePathTests(unittest.TestCase):
    def test_unique(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            first = folder / "song.mp3"
            first.write_text("a", encoding="utf-8")
            second = server.unique_path(folder, "song.mp3")
            self.assertEqual(second.name, "song (2).mp3")


class DownloadSkipTests(unittest.TestCase):
    def test_existing_marker(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            audio = folder / "歌手 - 歌名.mp3"
            audio.write_bytes(b"x" * 2000)
            (folder / ".abc123.done").write_text("歌手 - 歌名.mp3", encoding="utf-8")
            with mock.patch.object(server, "AUDIO_DIR", folder):
                found = server.existing_download("abc123")
            self.assertEqual(found, audio)


class YtdlpAuthTests(unittest.TestCase):
    def setUp(self):
        server.reset_ytdlp_auth()

    def test_bot_message(self):
        text = "ERROR: [youtube] xx: Sign in to confirm you’re not a bot. Use --cookies-from-browser"
        self.assertTrue(server.is_bot_block(text))
        anonymous = server.friendly_download_error(text, False)
        self.assertIn("不是用你的帳號", anonymous)
        with_cookies = server.friendly_download_error(text, True)
        self.assertIn("專用帳號", with_cookies)
        self.assertNotIn("cookies-from-browser", with_cookies)

    def test_cookie_specs_include_profile(self):
        specs = server.cookie_specs("chrome")
        self.assertTrue(any(item.startswith("chrome") for item in specs))
        self.assertIn("chrome:Default", specs)

    def test_normalize_browser(self):
        self.assertEqual(server.normalize_browser("Chrome"), "chrome")
        self.assertEqual(server.normalize_browser("msedge"), "edge")
        self.assertEqual(server.normalize_browser("chrome:Default"), "chrome:Default")
        self.assertEqual(server.normalize_browser("hack;rm"), "")

    def test_retries_with_chrome_cookies(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(list(command))
                if "--cookies-from-browser" not in command:
                    return mock.Mock(
                        returncode=1,
                        stdout="",
                        stderr="ERROR: Sign in to confirm you're not a bot. Use --cookies-from-browser",
                    )
                video_id = None
                for part in command:
                    if str(part).endswith(".%(ext)s"):
                        video_id = Path(part).name.split(".", 1)[0]
                (folder / f"{video_id}.mp3").write_bytes(b"audio" * 500)
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(server, "AUDIO_DIR", folder), \
                 mock.patch.object(server, "find_ytdlp", return_value="/usr/bin/yt-dlp"), \
                 mock.patch.object(server, "find_ffmpeg", return_value="/usr/bin/ffmpeg"), \
                 mock.patch.object(server.subprocess, "run", side_effect=fake_run):
                result = server.download_youtube_audio(
                    "https://youtu.be/lOL3CEton6E",
                    "打上花火",
                    "DAOKO",
                    "chrome",
                    True,
                )
            self.assertFalse(result["skipped"])
            self.assertTrue(str(result["cookieBrowser"]).startswith("chrome"))
            self.assertTrue(any("--cookies-from-browser" in call for call in calls))
            self.assertTrue(any("--cookies-from-browser" in call for call in calls))

    def test_impersonate_without_account(self):
        with mock.patch.object(server, "curl_cffi_available", return_value=True):
            self.assertEqual(server.impersonate_client(None), "chrome")
            self.assertIsNone(server.impersonate_client("chrome"))

    def test_anonymous_never_reads_cookies(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(list(command))
                return mock.Mock(
                    returncode=1,
                    stdout="",
                    stderr="ERROR: Sign in to confirm you're not a bot.",
                )

            with mock.patch.object(server, "AUDIO_DIR", folder), \
                 mock.patch.object(server, "find_ytdlp", return_value="/usr/bin/yt-dlp"), \
                 mock.patch.object(server, "find_ffmpeg", return_value="/usr/bin/ffmpeg"), \
                 mock.patch.object(server.subprocess, "run", side_effect=fake_run):
                with self.assertRaises(server.SongListError) as ctx:
                    server.download_youtube_audio(
                        "https://youtu.be/lOL3CEton6E",
                        "打上花火",
                        "DAOKO",
                        "chrome",
                        False,
                    )
            self.assertTrue(calls)
            self.assertTrue(all("--cookies-from-browser" not in call for call in calls))
            self.assertIn("不是用你的帳號", str(ctx.exception))


class DownloadPipelineTests(unittest.TestCase):
    def setUp(self):
        server.reset_ytdlp_auth()

    def test_download_renames_and_skips(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)

            def fake_run(command, **_kwargs):
                video_id = None
                for part in command:
                    if str(part).endswith(".%(ext)s"):
                        video_id = Path(part).name.split(".", 1)[0]
                produced = folder / f"{video_id}.mp3"
                produced.write_bytes(b"audio" * 500)
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(server, "AUDIO_DIR", folder), \
                 mock.patch.object(server, "find_ytdlp", return_value="/usr/bin/yt-dlp"), \
                 mock.patch.object(server, "find_ffmpeg", return_value="/usr/bin/ffmpeg"), \
                 mock.patch.object(server.subprocess, "run", side_effect=fake_run):
                first = server.download_youtube_audio(
                    "https://youtu.be/lOL3CEton6E",
                    "打上花火",
                    "DAOKO",
                )
                second = server.download_youtube_audio(
                    "https://youtu.be/lOL3CEton6E",
                    "打上花火",
                    "DAOKO",
                )
            self.assertEqual(first["filename"], "DAOKO - 打上花火.mp3")
            self.assertFalse(first["skipped"])
            self.assertTrue(second["skipped"])
            self.assertTrue((folder / first["filename"]).is_file())


class HealthPayloadTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(server.APP_VERSION, "0.6.3")


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code, payload):
        super().__init__(
            "http://127.0.0.1:3000/api/youtube",
            code,
            "err",
            hdrs=Message(),
            fp=io.BytesIO(json.dumps(payload).encode("utf-8")),
        )


def elitesand_health(port, version="0.9.9.5"):
    return {
        "status": "ok",
        "version": version,
        "timestamp": 1710000000000,
        "port": port,
        "portFallbackFrom": 3000 if port != 3000 else None,
    }


def elitesand_obs(port):
    return {
        "dir": "C:/Elitesand Pro/data/obs-sources",
        "port": port,
        "files": {
            "lyrics": f"C:/Elitesand-Pro-Lyrics.html",
            "setlist": f"C:/Elitesand-Pro-Setlist.html",
        },
    }


class ElitesandProxyTests(unittest.TestCase):
    def test_find_scans_ports(self):
        calls = []

        def fake_urlopen(request, timeout=0):
            calls.append(request.full_url)
            if request.full_url.endswith(":3001/api/health"):
                return FakeResponse(elitesand_health(3001))
            if request.full_url.endswith(":3001/api/obs-launcher"):
                return FakeResponse(elitesand_obs(3001))
            raise urllib.error.URLError("offline")

        with mock.patch.dict(os.environ, {"GO_TO_KTV_ELITESAND": ""}, clear=False), mock.patch.object(
            server.urllib.request, "urlopen", side_effect=fake_urlopen
        ):
            found = server.find_elitesand()
        self.assertTrue(found["ok"])
        self.assertEqual(found["base"], "http://127.0.0.1:3001")
        self.assertEqual(found["version"], "0.9.9.5")
        self.assertTrue(any(":3000/api/health" in url for url in calls))

    def test_find_override(self):
        def fake_urlopen(request, timeout=0):
            if request.full_url == "http://127.0.0.1:3999/api/health":
                return FakeResponse(elitesand_health(3999))
            if request.full_url == "http://127.0.0.1:3999/api/obs-launcher":
                return FakeResponse(elitesand_obs(3999))
            raise urllib.error.URLError("offline")

        with mock.patch.dict(os.environ, {"GO_TO_KTV_ELITESAND": "http://127.0.0.1:3999"}, clear=False), mock.patch.object(
            server.urllib.request, "urlopen", side_effect=fake_urlopen
        ):
            found = server.find_elitesand()
        self.assertEqual(found["base"], "http://127.0.0.1:3999")

    def test_import_missing_app(self):
        with mock.patch.object(server, "find_elitesand", return_value=None):
            with self.assertRaises(server.SongListError) as ctx:
                server.elitesand_import_youtube("https://youtu.be/lOL3CEton6E")
        self.assertIn("找不到", str(ctx.exception))

    def test_import_posts_batch_and_pin(self):
        captured = {}

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["pin"] = request.headers.get("X-pin") or request.headers.get("X-Pin")
            return FakeResponse(
                {
                    "success": True,
                    "track": {"id": "abc", "title": "打上花火", "filename": "song.mp3"},
                }
            )

        with mock.patch.object(
            server, "find_elitesand", return_value={"ok": True, "base": "http://127.0.0.1:3000"}
        ), mock.patch.object(server, "elitesand_attach_to_playlist", return_value=True) as attach, mock.patch.object(
            server.urllib.request, "urlopen", side_effect=fake_urlopen
        ):
            result = server.elitesand_import_youtube("https://youtu.be/lOL3CEton6E", "1234")
        self.assertFalse(result["skipped"])
        self.assertTrue(result["playlistOk"])
        self.assertEqual(result["filename"], "song.mp3")
        attach.assert_called_once()
        sent_track = attach.call_args.args[1]
        self.assertEqual(sent_track["id"], "abc")
        self.assertEqual(sent_track["filename"], "song.mp3")
        self.assertEqual(captured["url"], "http://127.0.0.1:3000/api/youtube")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["body"]["url"], "https://www.youtube.com/watch?v=lOL3CEton6E")
        self.assertTrue(captured["body"]["isBatch"])
        self.assertEqual(captured["pin"], "1234")

    def test_import_duplicate(self):
        def fake_urlopen(request, timeout=0):
            raise FakeHTTPError(409, {"code": "DUPLICATE_SONG", "existing": {"title": "已有", "filename": "old.mp3"}})

        with mock.patch.object(
            server, "find_elitesand", return_value={"ok": True, "base": "http://127.0.0.1:3000"}
        ), mock.patch.object(server, "elitesand_attach_to_playlist", return_value=True) as attach, mock.patch.object(
            server.urllib.request, "urlopen", side_effect=fake_urlopen
        ):
            result = server.elitesand_import_youtube("https://youtu.be/lOL3CEton6E")
        self.assertTrue(result["skipped"])
        self.assertTrue(result["playlistOk"])
        self.assertEqual(result["filename"], "old.mp3")
        attach.assert_called_once()

    def test_import_pin_required(self):
        def fake_urlopen(request, timeout=0):
            raise FakeHTTPError(401, {"code": "PIN_REQUIRED", "error": "PIN required"})

        with mock.patch.object(
            server, "find_elitesand", return_value={"ok": True, "base": "http://127.0.0.1:3000"}
        ), mock.patch.object(server.urllib.request, "urlopen", side_effect=fake_urlopen):
            with self.assertRaises(server.SongListError) as ctx:
                server.elitesand_import_youtube("https://youtu.be/lOL3CEton6E")
        self.assertIn("PIN", str(ctx.exception))

    def test_skip_mock_and_our_health(self):
        def fake_urlopen(request, timeout=0):
            if request.full_url.endswith(":3000/api/health"):
                return FakeResponse({"status": "ok", "version": "mock", "port": 3000, "timestamp": 1})
            if request.full_url.endswith(":3001/api/health"):
                return FakeResponse({"ok": True, "ytdlp": True, "version": "0.6.2", "audioDir": "/tmp"})
            if request.full_url.endswith(":3002/api/health"):
                return FakeResponse(elitesand_health(3002, "0.9.9.5"))
            if request.full_url.endswith(":3002/api/obs-launcher"):
                return FakeResponse(elitesand_obs(3002))
            raise urllib.error.URLError("offline")

        with mock.patch.dict(os.environ, {"GO_TO_KTV_ELITESAND": ""}, clear=False), mock.patch.object(
            server.urllib.request, "urlopen", side_effect=fake_urlopen
        ):
            found = server.find_elitesand()
        self.assertEqual(found["base"], "http://127.0.0.1:3002")
        self.assertEqual(found["version"], "0.9.9.5")

    def test_rejects_health_without_elitesand_fields(self):
        def fake_urlopen(request, timeout=0):
            if "/api/health" in request.full_url:
                return FakeResponse({"status": "ok", "version": "1.2.3", "timestamp": 1, "port": 3000})
            raise urllib.error.URLError("offline")

        with mock.patch.dict(os.environ, {"GO_TO_KTV_ELITESAND": ""}, clear=False), mock.patch.object(
            server.urllib.request, "urlopen", side_effect=fake_urlopen
        ):
            self.assertIsNone(server.find_elitesand())

    def test_import_rejects_stub_track(self):
        def fake_urlopen(request, timeout=0):
            return FakeResponse({"success": True, "track": {"title": "mock track", "filename": "mock.mp3"}})

        with mock.patch.object(
            server, "find_elitesand", return_value={"ok": True, "base": "http://127.0.0.1:3000"}
        ), mock.patch.object(server, "elitesand_attach_to_playlist") as attach, mock.patch.object(
            server.urllib.request, "urlopen", side_effect=fake_urlopen
        ):
            with self.assertRaises(server.SongListError) as ctx:
                server.elitesand_import_youtube("https://youtu.be/lOL3CEton6E")
        self.assertIn("不是 Elitesand", str(ctx.exception))
        attach.assert_not_called()


class PlaylistAttachTests(unittest.TestCase):
    def test_track_for_playlist_fills_id(self):
        track = server.track_for_playlist({"title": "雨愛", "filename": "a.mp3"}, "abc12345678", "https://www.youtube.com/watch?v=abc12345678")
        self.assertEqual(track["id"], "abc12345678")
        self.assertEqual(track["source"], "youtube")

    def test_attach_removes_then_adds(self):
        calls = []

        class FakeSio:
            connected = True

            def emit(self, event, data=None):
                calls.append(("emit", event, data))

            def call(self, event, data=None, timeout=0):
                calls.append(("call", event, data))
                return {"ok": True, "added": 1}

        found = {"ok": True, "base": "http://127.0.0.1:3000"}
        track = {"id": "abc", "title": "雨愛", "filename": "a.mp3"}
        with mock.patch.object(server, "elitesand_controller_socket", return_value=FakeSio()):
            self.assertTrue(server.elitesand_attach_to_playlist(found, track, "1234"))
        self.assertEqual(calls[0], ("emit", "playlist:remove", "abc"))
        self.assertEqual(calls[1][0], "call")
        self.assertEqual(calls[1][1], "playlist:add")
        self.assertEqual(calls[1][2][0]["filename"], "a.mp3")


if __name__ == "__main__":
    unittest.main()
