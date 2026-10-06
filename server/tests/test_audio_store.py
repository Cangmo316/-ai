"""音频下发通道测试：暂存、签名、过期、越权。

**重点守住"带不了请求头的播放器也能安全取音频"**：
端侧用 `innerAudioContext.src` / `<audio>` 拉音频，两者都带不了 `Authorization`，
所以鉴权只能靠 URL 签名。这条链一旦写松（比如忘了校验过期），
就是"任何人拿到 URL 就能反复取老人语音"——属于隐私红线，必须有断言守着。

跑法：`cd server; .\\.venv\\Scripts\\python.exe -m unittest tests.test_audio_store -v`
"""

from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.voice import audio_store  # noqa: E402


class StoreTest(unittest.TestCase):
    def test_存取(self):
        store = audio_store.AudioStore()
        audio_id = store.put(b"fake-mp3-bytes")
        self.assertTrue(audio_id)
        self.assertEqual(store.get(audio_id), b"fake-mp3-bytes")

    def test_id_是随机且不含业务标识(self):
        store = audio_store.AudioStore()
        first = store.put(b"a")
        second = store.put(b"b")
        self.assertNotEqual(first, second)
        self.assertEqual(len(first), 32)          # 16 字节 hex
        for char in first:
            self.assertIn(char, "0123456789abcdef")

    def test_过期后取不到(self):
        store = audio_store.AudioStore(ttl_s=1)
        audio_id = store.put(b"x", ttl_s=1)
        self.assertIsNotNone(store.get(audio_id))
        # 直接把过期时间拨到过去（不真等 1 秒，测试要快）
        expire_at, data = store._items[audio_id]
        store._items[audio_id] = (time.time() - 1, data)
        self.assertIsNone(store.get(audio_id))

    def test_空数据不产生_id(self):
        store = audio_store.AudioStore()
        self.assertEqual(store.put(b""), "")

    def test_超上限丢最旧的(self):
        store = audio_store.AudioStore(max_bytes=10)
        old = store.put(b"1" * 8)
        new = store.put(b"2" * 8)
        self.assertIsNone(store.get(old), "超上限应丢弃最旧的")
        self.assertIsNotNone(store.get(new))


class SignTest(unittest.TestCase):
    def setUp(self):
        os.environ["BILIN_AUDIO_SECRET"] = "test-secret"

    def tearDown(self):
        os.environ.pop("BILIN_AUDIO_SECRET", None)

    def test_正常签名可验(self):
        expire = int(time.time()) + 60
        signature = audio_store.sign("abc123", expire)
        ok, reason = audio_store.verify("abc123", expire, signature)
        self.assertTrue(ok, reason)

    def test_签名不匹配(self):
        expire = int(time.time()) + 60
        ok, _ = audio_store.verify("abc123", expire, "deadbeef" * 4)
        self.assertFalse(ok)

    def test_换_id_签名失效(self):
        expire = int(time.time()) + 60
        signature = audio_store.sign("abc123", expire)
        ok, _ = audio_store.verify("other-id", expire, signature)
        self.assertFalse(ok)

    def test_过期失效(self):
        expire = int(time.time()) - 1
        signature = audio_store.sign("abc123", expire)
        ok, reason = audio_store.verify("abc123", expire, signature)
        self.assertFalse(ok)
        self.assertIn("过期", reason)

    def test_缺签名失效(self):
        ok, _ = audio_store.verify("abc123", int(time.time()) + 60, "")
        self.assertFalse(ok)

    def test_坏过期时间不抛错(self):
        ok, _ = audio_store.verify("abc123", "not-a-number", "sig")
        self.assertFalse(ok)

    def test_密钥从_API_TOKENS_派生_而不是直接用(self):
        # 派生值不该等于原始 token（泄露签名的危害面要小于泄露 token）
        os.environ.pop("BILIN_AUDIO_SECRET", None)
        os.environ["API_TOKENS"] = "super-secret-token"
        try:
            key = audio_store._signing_key(None)
            self.assertNotEqual(key.decode("utf-8", "ignore"), "super-secret-token")
        finally:
            os.environ.pop("API_TOKENS", None)


class EndpointTest(unittest.TestCase):
    """端到端：真的起一个 app，走 HTTP 取音频。"""

    def setUp(self):
        os.environ["BILIN_AUDIO_SECRET"] = "test-secret"
        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self):
        os.environ.pop("BILIN_AUDIO_SECRET", None)

    def _put(self, data=b"ID3-fake-mp3"):
        audio_id = audio_store.get_store().put(data)
        return audio_id, audio_store.build_audio_url(audio_id)

    def test_用签名_url_能取到音频(self):
        data = b"ID3-fake-mp3-payload"
        _audio_id, url = self._put(data)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, data)
        self.assertIn("audio/mpeg", response.headers.get("content-type", ""))

    def test_没有签名取不到(self):
        audio_id = audio_store.get_store().put(b"x")
        response = self.client.get("/v1/audio/%s" % audio_id)
        self.assertEqual(response.status_code, 403)

    def test_签名错误取不到(self):
        audio_id = audio_store.get_store().put(b"x")
        expire = int(time.time()) + 60
        response = self.client.get("/v1/audio/%s?expires=%d&sig=wrong" % (audio_id, expire))
        self.assertEqual(response.status_code, 403)

    def test_过期签名取不到(self):
        audio_id = audio_store.get_store().put(b"x")
        expire = int(time.time()) - 5
        signature = audio_store.sign(audio_id, expire)
        response = self.client.get("/v1/audio/%s?expires=%d&sig=%s" % (audio_id, expire, signature))
        self.assertEqual(response.status_code, 403)

    def test_签名对但音频不存在是_404(self):
        expire = int(time.time()) + 60
        signature = audio_store.sign("missing-id", expire)
        response = self.client.get("/v1/audio/missing-id?expires=%d&sig=%s" % (expire, signature))
        self.assertEqual(response.status_code, 404)

    def test_音频端点不需要_Authorization_头(self):
        # 这条正是本通道存在的理由：播放器加不了头，所以必须能无头访问（靠签名自证）
        _audio_id, url = self._put(b"payload")
        response = self.client.get(url)          # 注意：没带任何 header
        self.assertEqual(response.status_code, 200)

    def test_错误响应不区分原因(self):
        # 403 与 404 的文案要一致，避免通过差异探测音频 id 是否存在
        first = self.client.get("/v1/audio/whatever?expires=1&sig=x").json()
        second = self.client.get("/v1/audio/%s" % ("a" * 32)).json()
        self.assertEqual(first.get("message"), second.get("message"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
