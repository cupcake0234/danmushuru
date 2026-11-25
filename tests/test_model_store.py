"""Exercise download failure recovery and atomic installation with tiny models."""

from contextlib import ExitStack
import hashlib
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import model_store


class ModelStoreTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory())) / "model"
        self.payloads = {"model.int8.onnx": b"verified model weights", "tokens.txt": b"a 0\nb 1\n"}
        self.specs = tuple(model_store.ModelFile(name, len(data), hashlib.sha256(data).hexdigest())
                           for name, data in self.payloads.items())
        self.stack.enter_context(patch.object(model_store, "MODEL_FILES", self.specs))
        self.stack.enter_context(patch.object(model_store, "MODEL_SOURCES", (
            ("primary", "https://primary/"), ("backup", "https://backup/"))))
        self.requests = []

    def opener(self, request, **kwargs):
        self.requests.append(request.full_url)
        return io.BytesIO(self.payloads[request.full_url.rsplit("/", 1)[1]])

    def test_installs_verified_files_and_reports_complete_progress(self):
        progress = []
        result = model_store.install_model(self.folder, opener=self.opener,
                                           on_progress=lambda *value: progress.append(value))
        self.assertEqual(result, self.folder.resolve())
        for name, payload in self.payloads.items():
            self.assertEqual((result / name).read_bytes(), payload)
        size = sum(map(len, self.payloads.values()))
        self.assertEqual(progress[-1][:2], (size, size))
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(list(result.glob("*.partial")), [])

    def test_invalid_hash_uses_backup_source(self):
        def opener(request, **kwargs):
            if request.full_url == "https://primary/model.int8.onnx":
                self.requests.append(request.full_url)
                return io.BytesIO(b"x" * len(self.payloads["model.int8.onnx"]))
            return self.opener(request, **kwargs)
        model_store.install_model(self.folder, opener=opener)
        self.assertEqual(self.requests[:2], ["https://primary/model.int8.onnx",
                                            "https://backup/model.int8.onnx"])
        self.assertEqual((self.folder / "model.int8.onnx").read_bytes(),
                         self.payloads["model.int8.onnx"])

    def test_verified_existing_install_does_not_download(self):
        model_store.install_model(self.folder, opener=self.opener)
        self.requests.clear()
        model_store.install_model(self.folder, opener=self.opener)
        self.assertEqual(self.requests, [])

    def test_same_size_corrupt_install_is_repaired(self):
        model_store.install_model(self.folder, opener=self.opener)
        self.requests.clear()
        (self.folder / "tokens.txt").write_bytes(b"x" * len(self.payloads["tokens.txt"]))
        model_store.install_model(self.folder, opener=self.opener)
        self.assertEqual(self.requests, ["https://primary/tokens.txt"])
        self.assertEqual((self.folder / "tokens.txt").read_bytes(), self.payloads["tokens.txt"])

    def test_failed_download_never_replaces_existing_file(self):
        self.folder.mkdir()
        destination = self.folder / "model.int8.onnx"
        destination.write_bytes(b"previous model")
        with self.assertRaises(model_store.ModelInstallError):
            model_store.install_model(self.folder, opener=lambda *a, **k: io.BytesIO(b"wrong"))
        self.assertEqual(destination.read_bytes(), b"previous model")
        self.assertFalse((self.folder / "model.int8.onnx.partial").exists())

    def test_retry_keeps_already_verified_files(self):
        def failing(request, **kwargs):
            if request.full_url.endswith("tokens.txt"):
                raise OSError("network unavailable")
            return self.opener(request, **kwargs)
        with self.assertRaises(model_store.ModelInstallError):
            model_store.install_model(self.folder, opener=failing)
        self.requests.clear()
        model_store.install_model(self.folder, opener=self.opener)
        self.assertEqual(self.requests, ["https://primary/tokens.txt"])

    def test_cancel_removes_partial_and_never_publishes_model(self):
        cancel = threading.Event()

        class Response(io.BytesIO):
            def read(self, size=-1):
                cancel.set()
                return super().read(size)

        with self.assertRaises(model_store.ModelInstallCancelled):
            model_store.install_model(self.folder, cancel=cancel,
                                      opener=lambda *a, **k: Response(self.payloads["model.int8.onnx"]))
        self.assertFalse((self.folder / "model.int8.onnx").exists())
        self.assertEqual(list(self.folder.glob("*.partial")), [])

    def test_pre_cancelled_install_makes_no_network_request(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(model_store.ModelInstallCancelled):
            model_store.install_model(self.folder, cancel=cancel, opener=self.opener)
        self.assertFalse(self.folder.exists())
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
