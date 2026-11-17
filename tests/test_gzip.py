"""gzip for the browsers that accept it (web.py)."""

import gzip
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from colcon_dashboard import web
from colcon_dashboard.web import Handler, accepts_gzip
import tests.helpers  # noqa: F401  (it points CONFIG at a test path)

# the deb build exports a dead http_proxy, and urllib sends loopback
# requests through it too (see tests/test_api.py)
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Headers(unittest.TestCase):
    def test_accept_encoding(self):
        for header in ("gzip", "gzip, deflate, br, zstd", "deflate, GZIP;q=0.5", "*"):
            self.assertTrue(accepts_gzip(header), header)
        for header in (None, "", "identity", "br", "gzip;q=0", "gzip; q=0.0", "gzip;q=x"):
            self.assertFalse(accepts_gzip(header), header)

    def test_a_published_body_is_compressed_once(self):
        body = "x" * 5000
        with mock.patch.object(web.gzip, "compress", wraps=gzip.compress) as packer:
            first = web._gzipped(body, body.encode(), shared=True)
            again = web._gzipped(body, body.encode(), shared=True)
        self.assertIs(first, again)
        self.assertEqual(packer.call_count, 1)
        self.assertEqual(gzip.decompress(first), body.encode())


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ThreadingHTTPServer.daemon_threads = True
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, encoding=None):
        headers = {"Accept-Encoding": encoding} if encoding else {}
        req = urllib.request.Request(self.base + path, headers=headers)
        with OPENER.open(req, timeout=5) as r:
            return r.headers.get("Content-Encoding"), r.read()

    def test_gzip_when_the_browser_asks(self):
        _, plain = self.get("/style.css")
        enc, packed = self.get("/style.css", "gzip, deflate")
        self.assertEqual(enc, "gzip")
        self.assertEqual(gzip.decompress(packed), plain)
        self.assertLess(len(packed), len(plain))
        # no gzip without the header, and none for a PNG or a short answer
        self.assertIsNone(self.get("/style.css")[0])
        self.assertIsNone(self.get("/icon-192.png", "gzip")[0])
        self.assertIsNone(self.get("/api/ping", "gzip")[0])

if __name__ == "__main__":
    unittest.main()
