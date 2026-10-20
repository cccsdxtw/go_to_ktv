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


class YoutubeSearchPickTests(unittest.TestCase):
    def test_instrumental_ranks_first(self):
        picked = server.pick_youtube_entry(
            [
                {"id": "aaa", "title": "打上花火"},
                {"id": "bbb", "title": "打上花火 伴奏"},
                {"id": "ccc", "title": "打上花火 cover"},
            ]
        )
        self.assertEqual(picked["id"], "bbb")

    def test_search_keeps_five_candidates(self):
        payload = {
            "entries": [
                {"id": "aaa111", "title": "打上花火"},
                {"id": "bbb222", "title": "打上花火 伴奏"},
                {"id": "ccc333", "title": "打上花火 karaoke"},
                {"id": "ddd444", "title": "打上花火 cover"},
                {"id": "eee555", "title": "打上花火 live"},
            ]
        }
        fake = mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")
        with mock.patch.object(server, "find_ytdlp", return_value="/usr/bin/yt-dlp"), mock.patch.object(
            server.subprocess, "run", return_value=fake
        ):
            result = server.search_youtube("打上花火", "DAOKO")
        self.assertEqual(len(result["candidates"]), 5)
        self.assertEqual(result["videoId"], "bbb222")
        self.assertEqual(result["candidates"][0]["videoId"], "bbb222")
        self.assertTrue(result["candidates"][0]["url"].endswith("bbb222"))
        self.assertEqual(result["query"], "打上花火 DAOKO 伴奏")

    def test_parse_print_lines(self):
        stdout = "\n".join(
            [
                json.dumps({"id": "aaa", "title": "原唱"}),
                json.dumps({"id": "bbb", "title": "伴奏"}),
            ]
        )
        found = server.parse_ytdlp_search_output(stdout)
        self.assertEqual([item["id"] for item in found], ["aaa", "bbb"])


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
        self.assertEqual(server.APP_VERSION, "1.0.9")


class ActionGroupLayoutTests(unittest.TestCase):
    def test_four_labeled_rows(self):
        html = Path("index.html").read_text(encoding="utf-8")
        labels = ["下載區", "YT區", "程式區", "其他"]
        for label in labels:
            self.assertIn(f'<span class="row-label">{label}</span>', html)
        self.assertLess(html.index("下載區"), html.index("YT區"))
        self.assertLess(html.index("YT區"), html.index("程式區"))
        self.assertLess(html.index("程式區"), html.index(">其他<"))
        self.assertIn('id="copy"', html)
        self.assertIn('id="download"', html)
        self.assertIn('id="copy-youtube"', html)
        self.assertIn('id="youtube-search"', html)
        self.assertIn("去聽", html)
        self.assertIn("yt-pick", html)
        self.assertIn("yt-choice", html)
        self.assertIn("另外", html)
        self.assertIn("is-collapsed", html)
        self.assertIn("applyYoutubeCandidate", html)
        self.assertNotIn('id="youtube-stop"', html)
        self.assertNotIn('id="elitesand-stop"', html)
        self.assertNotIn('id="audio-stop"', html)
        self.assertIn('id="send-elitesand"', html)
        self.assertIn('id="one-click-serial"', html)
        self.assertIn('id="one-click-parallel"', html)
        self.assertIn('id="one-click-fetch-serial"', html)
        self.assertIn('id="one-click-fetch-parallel"', html)
        self.assertIn('id="one-click-sheet-serial"', html)
        self.assertIn('id="one-click-sheet-parallel"', html)
        self.assertIn("一鍵開始(順序)", html)
        self.assertIn("一鍵開始(並行)", html)
        self.assertIn('id="send-concurrency"', html)
        self.assertIn('<option value="1" selected>1</option>', html)
        self.assertIn("同時下載預設 1，每次打開都是 1", html)
        self.assertIn("Elitesand 沒保證能同時收多首", html)
        self.assertIn('sendConcurrencySelect.value = "1"', html)
        self.assertNotIn("go_to_ktv_send_conc", html)
        self.assertIn('id="check-elitesand"', html)
        self.assertIn('id="pipeline-stop"', html)
        self.assertIn("一鍵開始", html)
        self.assertIn('id="elitesand-pin"', html)
        self.assertNotIn("暫停搜尋", html)
        self.assertNotIn("暫停送出", html)
        self.assertNotIn("暫停另存", html)
        self.assertLess(html.index(">其他<"), html.index('id="copy-youtube"'))
        self.assertLess(html.index('id="youtube-search"'), html.index('id="copy-youtube"'))
        self.assertNotIn("hidden>暫停", html)
        self.assertNotIn('hidden>停止', html)


class OneClickPipelineTests(unittest.TestCase):
    def test_elitesand_before_youtube_then_send(self):
        html = Path("index.html").read_text(encoding="utf-8")
        fn = html.split("async function runOneClickPipeline", 1)[1].split("oneClickSerialButton.addEventListener", 1)[0]
        self.assertLess(fn.index("markExistingElitesandSongs(true)"), fn.index("overlapSearchAndSend"))
        self.assertIn("runSerialSearchThenSend", fn)
        self.assertIn('mode === "parallel"', fn)
        self.assertIn("pipelineWasStopped()", fn)
        self.assertIn("waitIfPaused", fn)
        serial = html.split("async function runSerialSearchThenSend", 1)[1].split("async function finishOneClickResult", 1)[0]
        self.assertLess(serial.index("searchYoutubeTargets"), serial.index("sendElitesandTargets"))
        overlap = html.split("function createOverlapEngine()", 1)[1].split("async function overlapSearchAndSend", 1)[0]
        self.assertIn("enqueueSend", overlap)
        self.assertIn("searchOneYoutube", overlap)
        self.assertIn("sendOneElitesand", overlap)
        self.assertIn("finishCrawl", overlap)
        self.assertIn("createSendPool", overlap)
        self.assertIn("/api/songs-stream", html)
        self.assertIn("async function runOneClickFromUrl", html)
        from_url = html.split("async function runOneClickFromUrl", 1)[1].split("async function startOneClickFromUrl", 1)[0]
        self.assertLess(from_url.index("loadElitesandLibraryIndex(true)"), from_url.index("loadPlaylistFromUrl"))
        self.assertLess(from_url.index("loadPlaylistFromUrl"), from_url.index("streamPlaylistFromUrl"))
        self.assertLess(from_url.index("streamPlaylistFromUrl"), from_url.index("engine.addSongs"))
        self.assertIn("runSerialSearchThenSend", from_url)
        pool = html.split("function createSendPool()", 1)[1].split("function createOverlapEngine()", 1)[0]
        self.assertIn("sendConcurrency()", pool)
        send = html.split("async function sendElitesandTargets", 1)[1].split("sendElitesandButton.addEventListener", 1)[0]
        self.assertIn("createSendPool()", send)

    def test_stop_clears_and_aborts(self):
        html = Path("index.html").read_text(encoding="utf-8")
        self.assertIn("function clearStopFlags()", html)
        self.assertIn("function requestPause()", html)
        self.assertIn("function requestResume()", html)
        self.assertIn("function waitIfPaused()", html)
        self.assertNotIn("function confirmLeavePaused(", html)
        self.assertNotIn("unlockPausedActionButtons", html)
        self.assertNotIn("allowWorkOrLeavePause", html)
        self.assertIn('pipelinePaused ? "繼續" : "暫停"', html)
        pause = html.split("function requestPause()", 1)[1].split("function requestResume()", 1)[0]
        self.assertNotIn("pipelineAbort.abort()", pause)
        self.assertNotIn("unlockPausedActionButtons", pause)
        self.assertIn("youtubeSearchButton.disabled = busy", html)
        self.assertIn("pipelineAbort.abort()", html.split("function requestStop", 1)[1].split("copyYoutubeButton", 1)[0])
        search = html.split("async function searchYoutubeTargets", 1)[1].split("youtubeSearchButton.addEventListener", 1)[0]
        send = html.split("async function sendElitesandTargets", 1)[1].split("sendElitesandButton.addEventListener", 1)[0]
        self.assertIn("await waitIfPaused()", search)
        self.assertIn("await waitIfPaused()", send)
        self.assertIn("if (!fromPipeline) clearStopFlags()", search)
        self.assertIn("if (!fromPipeline) clearStopFlags()", send)
        self.assertIn('id="pipeline-stop"', html)
        self.assertIn("暫停", html)
        self.assertIn("繼續", html)


class PlaylistStreamTests(unittest.TestCase):
    def test_ssl_emits_first_page_before_second_fetch(self):
        pages = [
            {
                "./routes/streamer/_streamer": {
                    "streamer": {"platforms": {"twitch": {"displayName": "Ada"}}}
                },
                "./routes/streamer/songs": {
                    "songs": [{"id": 1, "title": "A", "artist": "X"}],
                    "token": "next",
                    "total": 2,
                },
            },
            {
                "./routes/streamer/_streamer": {},
                "./routes/streamer/songs": {
                    "songs": [{"id": 2, "title": "B", "artist": "Y"}],
                    "token": "",
                    "total": 2,
                },
            },
        ]
        calls = []

        def fake_payload(url):
            calls.append(url)
            return pages[len(calls) - 1]

        with mock.patch.object(server, "fetch_payload", side_effect=fake_payload):
            events = list(server.iter_streamersonglist("ada"))
        self.assertEqual(events[0]["type"], "meta")
        self.assertEqual(events[1]["type"], "songs")
        self.assertEqual(events[1]["songs"][0]["title"], "A")
        self.assertEqual(events[2]["type"], "songs")
        self.assertEqual(events[2]["songs"][0]["title"], "B")
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(len(calls), 2)
        assembled = server.playlist_from_events(events)
        self.assertEqual(len(assembled["songs"]), 2)
        self.assertEqual(assembled["displayName"], "Ada")

    def test_stream_route_exists(self):
        text = Path("server.py").read_text(encoding="utf-8")
        self.assertIn('path == "/api/songs-stream"', text)
        self.assertIn("def iter_import_playlist", text)


class StickyFlowChartTests(unittest.TestCase):
    def test_sticky_steps_and_status(self):
        html = Path("index.html").read_text(encoding="utf-8")
        self.assertIn('class="stick-top"', html)
        self.assertIn('id="flow-chart"', html)
        self.assertLess(html.index("截取歌曲"), html.index("確定Elitesand歌單"))
        self.assertLess(html.index("確定Elitesand歌單"), html.index("YT搜尋"))
        self.assertLess(html.index("YT搜尋"), html.index("匯入Elitesand下載"))
        self.assertLess(html.index("匯入Elitesand下載"), html.index("flow-name\">完成"))
        status_at = html.index('id="status"')
        chart_at = html.index('id="flow-chart"')
        self.assertLess(chart_at, html.index('id="send-concurrency"'))
        self.assertLess(html.index('id="send-concurrency"'), html.index('id="pipeline-stop"'))
        self.assertLess(chart_at, html.index('id="pipeline-stop"'))
        self.assertLess(html.index('id="pipeline-stop"'), status_at)
        busy = html.split("function setPipelineBusy", 1)[1].split("function oneClickSummary", 1)[0]
        self.assertNotIn("sendConcurrencySelect.disabled", busy)
        self.assertLess(chart_at, status_at)
        self.assertLess(status_at, html.index('id="result"'))
        self.assertIn("function setFlowStages(", html)
        self.assertIn("function setFlowStage(", html)
        self.assertIn("function setFlowHint(", html)
        self.assertIn('data-flow-hint="check"', html)
        self.assertIn("尚未對", html)
        self.assertIn("正在對 Elitesand", html)
        self.assertIn('id="check-elitesand"', html)
        self.assertIn('class="source-card zone-fetch"', html)
        self.assertIn("zone-yt", html)
        self.assertIn("zone-import", html)
        self.assertIn("zone-check", html)


class ElitesandDialogTests(unittest.TestCase):
    def test_prompt_copy(self):
        html = Path("index.html").read_text(encoding="utf-8")
        self.assertIn("請開啟Elitesand", html)
        self.assertIn("已下載完成", html)
        self.assertIn("關閉程式", html)
        self.assertIn('id="app-dialog"', html)
        self.assertIn("window.close()", html)
        self.assertIn("function closeThisTab()", html)
        close_fn = html.split("function closeThisTab()", 1)[1].split("async function closeThisApp()", 1)[0]
        self.assertLess(close_fn.index("已結束"), close_fn.index("window.close()"))
        self.assertIn("這個分頁即將關閉", close_fn)


class CloseableWindowTests(unittest.TestCase):
    def test_windows_uses_app_flag(self):
        calls = []

        def fake_popen(args, **_kwargs):
            calls.append(args)
            return mock.Mock()

        with mock.patch.object(server.sys, "platform", "win32"), mock.patch.object(
            server, "windows_app_browsers", return_value=["C:\\chrome.exe"]
        ), mock.patch.object(server.subprocess, "Popen", side_effect=fake_popen):
            self.assertTrue(server.open_closeable_window("http://127.0.0.1:8765"))
        self.assertEqual(calls, [["C:\\chrome.exe", "--app=http://127.0.0.1:8765"]])

    def test_falls_back_when_no_app_browser(self):
        with mock.patch.object(server.sys, "platform", "win32"), mock.patch.object(
            server, "windows_app_browsers", return_value=[]
        ):
            self.assertFalse(server.open_closeable_window("http://127.0.0.1:8765"))


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
            result = server.elitesand_import_youtube(
                "https://youtu.be/lOL3CEton6E", "1234", "Lydia", "F.I.R"
            )
        self.assertFalse(result["skipped"])
        self.assertTrue(result["playlistOk"])
        self.assertEqual(result["filename"], "song.mp3")
        self.assertEqual(result["title"], "Lydia")
        attach.assert_called_once()
        sent_track = attach.call_args.args[1]
        self.assertEqual(sent_track["id"], "abc")
        self.assertEqual(sent_track["filename"], "song.mp3")
        self.assertEqual(sent_track["title"], "Lydia")
        self.assertEqual(sent_track["artist"], "F.I.R")
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

    def test_library_index_from_api(self):
        def fake_json(url, timeout=0, pin=""):
            if str(url).endswith("/api/library"):
                return {
                    "tracks": [
                        {
                            "title": "打上花火",
                            "artist": "DAOKO",
                            "url": "https://youtu.be/lOL3CEton6E",
                        }
                    ]
                }
            return None

        with mock.patch.object(
            server, "find_elitesand", return_value={"ok": True, "base": "http://127.0.0.1:3000"}
        ), mock.patch.object(server, "elitesand_json", side_effect=fake_json):
            result = server.fetch_elitesand_library("1234")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["tracks"][0]["videoId"], "lOL3CEton6E")
        self.assertEqual(result["tracks"][0]["key"], "打上花火|daoko")

    def test_song_key_and_extract(self):
        self.assertEqual(server.normalize_song_key(" 打上花火 ", " DAOKO "), "打上花火|daoko")
        tracks = server.extract_track_list({"songs": [{"title": "雨愛", "artist": "楊丞琳", "id": "abc12345678"}]})
        item = server.summarize_elitesand_track(tracks[0])
        self.assertEqual(item["videoId"], "abc12345678")

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
        self.assertEqual(track["title"], "雨愛")

    def test_track_for_playlist_keeps_original_names(self):
        track = server.track_for_playlist(
            {"title": "LydiaFIR飞儿乐团(高清)", "artist": "Someone", "filename": "a.mp3"},
            "abc12345678",
            "https://www.youtube.com/watch?v=abc12345678",
            "Lydia",
            "F.I.R",
        )
        self.assertEqual(track["title"], "Lydia")
        self.assertEqual(track["artist"], "F.I.R")
        self.assertEqual(track["filename"], "a.mp3")
        self.assertEqual(track["artistConfidence"], 1)
        self.assertFalse(track["needsArtistConfirmation"])

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


class PlaylistImportTests(unittest.TestCase):
    def test_detect_ssl(self):
        found = server.detect_playlist("https://streamersonglist.com/t/demo/songs")
        self.assertEqual(found["kind"], "streamersonglist")
        self.assertEqual(found["username"], "demo")

    def test_detect_youtube_playlist(self):
        found = server.detect_playlist("https://www.youtube.com/playlist?list=PLabcdefghijk")
        self.assertEqual(found["kind"], "youtube")
        self.assertEqual(found["listId"], "PLabcdefghijk")

    def test_detect_youtube_watch_with_list(self):
        found = server.detect_playlist("https://www.youtube.com/watch?v=lOL3CEton6E&list=PLabc")
        self.assertEqual(found["listId"], "PLabc")

    def test_detect_youtube_video(self):
        found = server.detect_playlist("https://youtu.be/lOL3CEton6E")
        self.assertEqual(found["videoId"], "lOL3CEton6E")

    def test_detect_youtube_mix_uses_video(self):
        found = server.detect_playlist("https://www.youtube.com/watch?v=lOL3CEton6E&list=RDlOL3CEton6E")
        self.assertEqual(found["videoId"], "lOL3CEton6E")
        self.assertNotIn("listId", found)

    def test_detect_kkbox_playlist(self):
        found = server.detect_playlist("https://www.kkbox.com/tw/tc/playlist/4nUZM-TY2aVxZ2xaA-")
        self.assertEqual(found["kind"], "kkbox")
        self.assertEqual(found["itemType"], "playlist")
        self.assertEqual(found["itemId"], "4nUZM-TY2aVxZ2xaA-")

    def test_detect_unknown(self):
        with self.assertRaises(server.SongListError) as ctx:
            server.detect_playlist("https://example.com/x")
        self.assertIn("StreamerSonglist", str(ctx.exception))

    def test_split_title_artist(self):
        title, artist = server.split_title_artist("F.I.R - Lydia")
        self.assertEqual(title, "Lydia")
        self.assertEqual(artist, "F.I.R")

    def test_youtube_payload_prefills_url(self):
        result = server.songs_from_youtube_payload(
            {
                "title": "My list",
                "id": "PLabc",
                "entries": [{"id": "lOL3CEton6E", "title": "F.I.R - Lydia", "uploader": "x"}],
            },
            "https://www.youtube.com/playlist?list=PLabc",
        )
        self.assertEqual(result["sourceKind"], "youtube")
        song = result["songs"][0]
        self.assertEqual(song["youtubeUrl"], "https://www.youtube.com/watch?v=lOL3CEton6E")
        self.assertEqual(song["title"], "Lydia")
        self.assertEqual(song["artist"], "F.I.R")

    def test_kkbox_widget_tracks(self):
        display, songs = server.kkbox_tracks_from_widget(
            {
                "playlist_title": "測試",
                "songlist": [{"song_crypt_id": "a", "song_name": "這個世界", "artist_name": "蔡藍欽"}],
            }
        )
        self.assertEqual(display, "測試")
        self.assertEqual(songs[0]["title"], "這個世界")
        self.assertEqual(songs[0]["artist"], "蔡藍欽")

    def test_kkbox_widget_fetch(self):
        html_doc = (
            '<div data-state="{&quot;feed&quot;:{&quot;data&quot;:{&quot;playlist_title&quot;:&quot;測試&quot;,'
            '&quot;songlist&quot;:[{&quot;song_crypt_id&quot;:&quot;a&quot;,&quot;song_name&quot;:&quot;雨愛&quot;,'
            '&quot;artist_name&quot;:&quot;楊丞琳&quot;}]}}}"></div>'
        )
        with mock.patch.object(server, "http_get_text", return_value=("https://widget.kkbox.com/v1/", html_doc)):
            result = server.fetch_kkbox_playlist("https://www.kkbox.com/tw/tc/playlist/abc123")
        self.assertEqual(result["sourceKind"], "kkbox")
        self.assertEqual(result["songs"][0]["title"], "雨愛")
        self.assertEqual(result["songs"][0]["artist"], "楊丞琳")

    def test_detect_spotify_playlist(self):
        found = server.detect_playlist("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc")
        self.assertEqual(found["kind"], "spotify")
        self.assertEqual(found["itemType"], "playlist")
        self.assertEqual(found["itemId"], "37i9dQZF1DXcBWIGoYBM5M")

    def test_detect_spotify_uri(self):
        found = server.detect_playlist("spotify:album:4aawyAB9vmqN3uQ7FjRGTy")
        self.assertEqual(found["kind"], "spotify")
        self.assertEqual(found["itemType"], "album")

    def test_spotify_entity_tracks(self):
        result = server.songs_from_spotify_entity(
            {
                "title": "Today’s Top Hits",
                "trackList": [
                    {
                        "uri": "spotify:track:3XmwAZpIMNpTJy8faw3ajD",
                        "title": "expectations",
                        "subtitle": "Olivia Rodrigo,\xa0Chappell Roan",
                    }
                ],
            },
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "37i9dQZF1DXcBWIGoYBM5M",
        )
        self.assertEqual(result["sourceKind"], "spotify")
        self.assertEqual(result["songs"][0]["title"], "expectations")
        self.assertEqual(result["songs"][0]["artist"], "Olivia Rodrigo, Chappell Roan")

    def test_spotify_embed_fetch(self):
        payload = {
            "props": {
                "pageProps": {
                    "state": {
                        "data": {
                            "entity": {
                                "title": "測試",
                                "trackList": [{"uri": "spotify:track:aaaaaaaaaaaaaaaaaaaaaa", "title": "雨愛", "subtitle": "楊丞琳"}],
                            }
                        }
                    }
                }
            }
        }
        html_doc = f'<script id="__NEXT_DATA__">{json.dumps(payload, ensure_ascii=False)}</script>'
        with mock.patch.object(server, "http_get_text", return_value=("https://open.spotify.com/embed/playlist/x", html_doc)):
            result = server.fetch_spotify_playlist("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
        self.assertEqual(result["songs"][0]["title"], "雨愛")
        self.assertEqual(result["songs"][0]["artist"], "楊丞琳")


class ShutdownTests(unittest.TestCase):
    def test_stop_http_closes_socket(self):
        class Dummy:
            def __init__(self):
                self.calls = []

            def shutdown(self):
                self.calls.append("shutdown")

            def server_close(self):
                self.calls.append("close")

        dummy = Dummy()
        server._httpd = dummy
        server._bound_port = 8765
        server._released = False
        server.stop_http()
        self.assertEqual(dummy.calls, ["shutdown", "close"])
        self.assertTrue(server._released)
        server.stop_http()
        self.assertEqual(dummy.calls, ["shutdown", "close"])
        server._httpd = None
        server._released = False


if __name__ == "__main__":
    unittest.main()
