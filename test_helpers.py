#!/usr/bin/env python3
"""本機小測試：檔名、YouTube 網址解析、下載 API 拒絕無效網址。"""

import json
import tempfile
import unittest
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
        message = server.friendly_download_error(text, True)
        self.assertIn("關掉 Chrome", message)
        self.assertNotIn("cookies-from-browser", message)

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
                )
            self.assertFalse(result["skipped"])
            self.assertTrue(str(result["cookieBrowser"]).startswith("chrome"))
            self.assertTrue(any("--cookies-from-browser" in call for call in calls))
            self.assertTrue(any("web,mweb" in " ".join(call) or "--cookies-from-browser" in call for call in calls))


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
        self.assertEqual(server.APP_VERSION, "0.5.2")


if __name__ == "__main__":
    unittest.main()
