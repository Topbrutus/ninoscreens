import os
import unittest
import urllib.parse
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock, patch

import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from app.web_profile import SecurityInterceptor, SecurityPolicy, build_shared_profile


def _ci_requires_webengine_failure() -> bool:
    return os.environ.get("CI", "").lower() == "true" or (
        os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    )


def _handle_webengine_unavailable(test_case, message: str) -> None:
    if _ci_requires_webengine_failure():
        test_case.fail(message)
        return
    test_case.skipTest(message)


class _SkipFailProbe:
    def __init__(self) -> None:
        self.skipped_message: str | None = None
        self.failed_message: str | None = None

    def skipTest(self, message: str) -> None:
        self.skipped_message = message

    def fail(self, message: str) -> None:
        self.failed_message = message


class TestSecurityPolicy(unittest.TestCase):
    def setUp(self):
        self.assets_root = Path(__file__).resolve().parents[1] / "app" / "assets"
        self.policy = SecurityPolicy([self.assets_root])

    def test_https_to_file_blocked(self):
        self.assertTrue(self.policy.should_block("file:///C:/secret.txt", "https://example.com"))

    def test_http_to_file_blocked(self):
        self.assertTrue(self.policy.should_block("file:///C:/secret.txt", "http://example.com"))

    def test_ws_to_file_blocked(self):
        self.assertTrue(self.policy.should_block("file:///C:/secret.txt", "ws://example.com"))

    def test_wss_to_file_blocked(self):
        self.assertTrue(self.policy.should_block("file:///C:/secret.txt", "wss://example.com"))

    def test_https_to_https_allowed(self):
        self.assertFalse(self.policy.should_block("https://api.github.com", "https://example.com"))

    def test_https_to_data_allowed(self):
        self.assertFalse(self.policy.should_block("data:text/html,Hello", "https://example.com"))

    def test_empty_origin_to_arbitrary_file_blocked(self):
        self.assertTrue(self.policy.should_block("file:///C:/secret.txt", ""))

    def test_unknown_origin_to_arbitrary_file_blocked(self):
        self.assertTrue(self.policy.should_block("file:///C:/secret.txt", "unknown-scheme://foo"))

    def test_local_origin_to_file_outside_whitelist_blocked(self):
        self.assertTrue(self.policy.should_block("file:///C:/secret.txt", "file:///C:/other.txt"))

    def test_internal_resource_allowed(self):
        terminal_html = self.assets_root / "terminal" / "terminal.html"
        url = "file:///" + urllib.parse.quote(str(terminal_html).replace('\\', '/'))
        self.assertFalse(self.policy.should_block(url, ""))
        self.assertFalse(self.policy.should_block(url, url))

    def test_path_traversal_blocked(self):
        # file:///D:/tools/ninoscreens/app/assets/../config.py
        escaped_path = self.assets_root / ".." / "config.py"
        url = "file:///" + urllib.parse.quote(str(escaped_path).replace('\\', '/'))
        self.assertTrue(self.policy.should_block(url, ""))

    def test_encoded_traversal_blocked(self):
        # file:///D:/tools/ninoscreens/app/assets/%2e%2e/config.py
        escaped_path = str(self.assets_root).replace('\\', '/') + "/%2e%2e/config.py"
        url = "file:///" + escaped_path
        self.assertTrue(self.policy.should_block(url, ""))

    def test_windows_case_variance(self):
        terminal_html = self.assets_root / "terminal" / "terminal.html"
        # Uppercase the drive letter and some folders
        url = "file:///" + urllib.parse.quote(str(terminal_html).upper().replace('\\', '/'))
        self.assertFalse(self.policy.should_block(url, ""))

    def test_windows_alt_separators(self):
        terminal_html = self.assets_root / "terminal" / "terminal.html"
        url = "file:///" + urllib.parse.quote(str(terminal_html).replace('/', '\\'))
        self.assertFalse(self.policy.should_block(url, ""))

    def test_malformed_url(self):
        # A malformed URL that might throw an exception in parsing
        self.assertTrue(self.policy.should_block("file:///C:/[invalid_url_chars]", ""))

    def test_no_sensitive_data_in_logs(self):
        from app.web_profile import SecurityInterceptor
        
        interceptor = SecurityInterceptor(self.policy)
        info = MagicMock()
        info.requestUrl().toString.return_value = "file:///C:/Users/casho/secret.txt"
        info.firstPartyUrl().toString.return_value = "https://evil.com/query?token=123"
        info.requestUrl().scheme.return_value = "file"
        info.firstPartyUrl().scheme.return_value = "https"
        
        with self.assertLogs("app.web_profile", level="WARNING") as cm:
            interceptor.interceptRequest(info)
            
        info.block.assert_called_once_with(True)
        # Check logs don't contain the paths
        for record in cm.output:
            self.assertNotIn("casho", record)
            self.assertNotIn("secret", record)
            self.assertNotIn("evil.com", record)
            self.assertNotIn("token=123", record)


class TestWebProfileConfiguration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication([])

    def setUp(self):
        import app.web_profile
        # Reset the global interceptor for clean tests
        app.web_profile._SHARED_INTERCEPTOR = None
        self.profile = build_shared_profile(None)

    def test_security_attributes_set(self):
        settings = self.profile.settings()
        if hasattr(QWebEngineSettings.WebAttribute, 'WebSecurityEnabled'):
            self.assertTrue(settings.testAttribute(QWebEngineSettings.WebAttribute.WebSecurityEnabled))
        if hasattr(QWebEngineSettings.WebAttribute, 'LocalContentCanAccessFileUrls'):
            self.assertFalse(settings.testAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls))
        if hasattr(QWebEngineSettings.WebAttribute, 'LocalContentCanAccessRemoteUrls'):
            self.assertFalse(settings.testAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls))

    def test_attribute_absent_no_crash(self):
        import app.web_profile
        app.web_profile._SHARED_INTERCEPTOR = None
        # Mock hasattr to always return False for WebAttribute
        original_hasattr = hasattr
        def mock_hasattr(obj, attr):
            if obj is QWebEngineSettings.WebAttribute:
                return False
            return original_hasattr(obj, attr)
            
        with patch('builtins.hasattr', side_effect=mock_hasattr):
            profile = build_shared_profile(None)
            self.assertIsNotNone(profile)

    def test_single_interceptor_repeated_calls(self):
        import app.web_profile
        p1 = build_shared_profile(None)
        p2 = build_shared_profile(None)
        self.assertIsNotNone(app.web_profile._SHARED_INTERCEPTOR)
        self.assertIs(p1._nino_security_interceptor, p2._nino_security_interceptor)
        self.assertIs(app.web_profile._SHARED_INTERCEPTOR, p1._nino_security_interceptor)

    def test_unrelated_settings_preserved(self):
        settings = self.profile.settings()
        # From the original code
        self.assertFalse(settings.testAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard))
        self.assertTrue(settings.testAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled))


class WebProfileSecurityTests(unittest.TestCase):
    """Integration test using a controlled local HTTP server on 127.0.0.1.

    Verifies that:
    - An HTTP resource served locally is accessible.
    - A file:// request attempted from an HTTP origin is blocked by the
      SecurityInterceptor before any content is read.
    No external network is used. No real secrets are accessed.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _process_deferred_deletes(self, rounds=8):
        for _ in range(rounds):
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()

    def _assert_deleted(self, obj, name):
        self._process_deferred_deletes()
        self.assertFalse(shiboken6.isValid(obj), f"{name} must be destroyed before profile release")

    def _run_with_timeout(self, page, url, timeout_ms=6000):
        """Load *url* into *page* and pump the event loop until loadFinished or timeout."""
        result = {}
        loop = QEventLoop()

        def on_load(ok):
            result["ok"] = ok
            loop.quit()

        page.loadFinished.connect(on_load)
        page.setUrl(url)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()
        page.loadFinished.disconnect(on_load)
        return result.get("ok")

    def test_qtwebengine_local_http_integration(self):
        import http.server
        import socket
        import tempfile
        import threading
        import urllib.request

        # Verify QWebEngineView can initialise in this environment.
        probe = None
        try:
            probe = QWebEngineView()
            loop = QEventLoop()
            loaded = {}

            def _probe_done(ok):
                loaded["ok"] = ok
                loop.quit()

            probe.loadFinished.connect(_probe_done)
            probe.setUrl(QUrl("about:blank"))
            QTimer.singleShot(5000, loop.quit)
            loop.exec()
            probe.loadFinished.disconnect(_probe_done)
            if not loaded.get("ok"):
                _handle_webengine_unavailable(
                    self,
                    "QWebEngineView could not load about:blank in this environment "
                    "(likely missing GPU / display driver). Class: loadFinished=False.",
                )
        except Exception as exc:
            _handle_webengine_unavailable(
                self,
                f"QWebEngineView initialisation failed: {type(exc).__name__}. "
                "Cannot run HTTP integration test.",
            )
        finally:
            if probe is not None:
                probe.stop()
                probe.close()
                probe.deleteLater()
                self._process_deferred_deletes()

        class _QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a dummy sensitive file – never a real file, never /etc/passwd
            sentinel_path = os.path.join(tmp_dir, "ninoscreens-security-test.txt")
            with open(sentinel_path, "w") as fh:
                fh.write("SHOULD_NOT_BE_ACCESSIBLE")

            # Create an HTML page served over HTTP that tries to fetch the file URL
            sentinel_url = "file:///" + sentinel_path.replace("\\", "/")
            html_content = f"""<!DOCTYPE html>
<html><head><title>loading</title></head>
<body><script>
(async () => {{
  try {{
    const resp = await fetch({repr(sentinel_url)});
    const txt = await resp.text();
    document.title = 'GOT:' + txt;
  }} catch (e) {{
    document.title = 'BLOCKED:' + e.constructor.name;
  }}
}})();
</script></body></html>"""
            page_html_path = os.path.join(tmp_dir, "page.html")
            with open(page_html_path, "w", encoding="utf-8") as fh:
                fh.write(html_content)

            # Start HTTP server bound to loopback only
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            httpd = http.server.HTTPServer(
                ("127.0.0.1", port),
                lambda *a, **kw: _QuietHandler(*a, directory=tmp_dir, **kw),
            )
            server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            server_thread.start()

            profile = None
            page = None
            view = None
            try:
                # Verify the HTTP server itself is reachable (pure Python, no Qt)
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/page.html", timeout=5) as r:
                    self.assertEqual(r.status, 200, "HTTP server must serve the test page")
                    r.read()

                # The integration test owns its profile to keep teardown deterministic.
                profile = QWebEngineProfile("ninoscreens-web-profile-test", self.app)
                profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
                profile.setPersistentCookiesPolicy(
                    QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
                )
                interceptor = SecurityInterceptor(SecurityPolicy([Path(tmp_dir)]), profile)
                profile.setUrlRequestInterceptor(interceptor)
                profile._nino_security_interceptor = interceptor

                view = QWebEngineView()

                secured_page = QWebEnginePage(profile, view)
                view.setPage(secured_page)
                page = secured_page

                # Load the HTTP page and wait
                http_url = QUrl(f"http://127.0.0.1:{port}/page.html")
                loaded_ok = self._run_with_timeout(page, http_url, timeout_ms=6000)
                self.assertTrue(loaded_ok, "HTTP page must load through QtWebEngine")

                # Now read the page title via JS
                title_result = {}
                title_loop = QEventLoop()

                def _on_title(t):
                    title_result["t"] = t
                    title_loop.quit()

                page.runJavaScript("document.title", _on_title)
                QTimer.singleShot(3000, title_loop.quit)
                title_loop.exec()

                title = title_result.get("t", "")
                # The fetch attempt should have been blocked; accept BLOCKED or loading
                # (some engines silently fail without updating title)
                self.assertNotIn(
                    "GOT:SHOULD_NOT_BE_ACCESSIBLE",
                    title,
                    "file:// content must NOT be accessible from an HTTP origin",
                )

            finally:
                if view is not None:
                    view.stop()
                if page is not None:
                    page.deleteLater()
                if view is not None:
                    view.close()
                    view.deleteLater()
                if page is not None:
                    self._assert_deleted(page, "QWebEnginePage")
                if view is not None:
                    self._assert_deleted(view, "QWebEngineView")
                if profile is not None:
                    profile.deleteLater()
                    self._process_deferred_deletes()

                page = None
                view = None
                profile = None

                import gc

                gc.collect()

                httpd.shutdown()
                httpd.server_close()
                server_thread.join(timeout=5)
                self.assertFalse(server_thread.is_alive(), "HTTP server thread must stop")


class WebEngineSkipPolicyTests(unittest.TestCase):
    def test_local_webengine_probe_failure_remains_skip_contract(self):
        probe = _SkipFailProbe()

        with patch.dict(os.environ, {"CI": "", "GITHUB_ACTIONS": ""}, clear=False):
            _handle_webengine_unavailable(probe, "local probe failure")

        self.assertEqual(probe.skipped_message, "local probe failure")
        self.assertIsNone(probe.failed_message)

    def test_ci_webengine_probe_failure_is_failure_not_skip(self):
        probe = _SkipFailProbe()

        with patch.dict(os.environ, {"CI": "true", "GITHUB_ACTIONS": ""}, clear=False):
            _handle_webengine_unavailable(probe, "ci probe failure")

        self.assertEqual(probe.failed_message, "ci probe failure")
        self.assertIsNone(probe.skipped_message)

if __name__ == '__main__':
    unittest.main()
