from __future__ import annotations

import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import UploadFile

from camelot_api import service
from camelot_api.models import ExtractRequest, ExtractResponse


class FileDeduplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = SimpleNamespace(
            upload_dir=self.temp_dir.name,
            upload_max_size_mb=10,
            upload_ttl_hours=1,
            cache_max_entries=10,
        )
        self.config_patch = patch.object(service, "get_config", return_value=self.config)
        self.config_patch.start()
        service._registry = {}
        service._md5_index = {}
        service._registry_loaded = True
        service._cache = {}
        service._cache_order = []

    def tearDown(self) -> None:
        self.config_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def _upload(content: bytes = b"%PDF-1.4\ncontent") -> UploadFile:
        return UploadFile(filename="sample.pdf", file=io.BytesIO(content))

    def test_expired_md5_entry_is_replaced_on_upload(self) -> None:
        first = service.save_upload(self._upload())
        service._registry[first.file_id]["created_at"] = (
            datetime.now(tz=timezone.utc) - timedelta(hours=2)
        ).isoformat()
        service._save_registry()
        service._registry = {}
        service._md5_index = {}
        service._load_registry()

        second = service.save_upload(self._upload())

        self.assertFalse(second.cached)
        self.assertNotEqual(first.file_id, second.file_id)
        self.assertNotIn(first.file_id, service._registry)
        self.assertEqual(
            service.resolve_file(second.file_id),
            Path(service._registry[second.file_id]["path"]),
        )

    def test_missing_md5_file_is_replaced_on_upload(self) -> None:
        first = service.save_upload(self._upload())
        Path(service._registry[first.file_id]["path"]).unlink()

        second = service.save_upload(self._upload())

        self.assertFalse(second.cached)
        self.assertNotEqual(first.file_id, second.file_id)
        self.assertTrue(service.resolve_file(second.file_id).exists())

    def test_expired_file_does_not_return_cached_extract_result(self) -> None:
        uploaded = service.save_upload(self._upload())
        request = ExtractRequest(file_id=uploaded.file_id)
        cache_key = service._make_cache_key(uploaded.file_id, request)
        service._cache_set(cache_key, ExtractResponse(success=True))
        service._registry[uploaded.file_id]["created_at"] = (
            datetime.now(tz=timezone.utc) - timedelta(hours=2)
        ).isoformat()

        result = service.extract_tables(request)

        self.assertFalse(result.success)
        self.assertNotIn(cache_key, service._cache)
        self.assertNotIn(uploaded.file_id, service._registry)

    def test_cleanup_uses_shared_expiration_and_discard_logic(self) -> None:
        uploaded = service.save_upload(self._upload())
        request = ExtractRequest(file_id=uploaded.file_id)
        cache_key = service._make_cache_key(uploaded.file_id, request)
        service._cache_set(cache_key, ExtractResponse(success=True))
        service._registry[uploaded.file_id]["created_at"] = (
            datetime.now(tz=timezone.utc) - timedelta(hours=2)
        ).isoformat()

        removed = service.cleanup_expired_files()

        self.assertEqual(removed, 1)
        self.assertNotIn(uploaded.file_id, service._registry)
        self.assertNotIn(uploaded.md5, service._md5_index)
        self.assertNotIn(cache_key, service._cache)

    def test_file_url_validates_file_before_returning_cached_result(self) -> None:
        uploaded = service.save_upload(self._upload())
        request = ExtractRequest(file_url="https://example.com/sample.pdf")
        cache_key = service._make_cache_key(uploaded.file_id, request)
        service._cache_set(cache_key, ExtractResponse(success=True))
        path = Path(service._registry[uploaded.file_id]["path"])
        path.unlink()

        with patch.object(
            service,
            "_download_from_url",
            return_value=(uploaded.file_id, path),
        ):
            result = service.extract_tables(request)

        self.assertFalse(result.success)
        self.assertNotIn(cache_key, service._cache)


if __name__ == "__main__":
    unittest.main()
