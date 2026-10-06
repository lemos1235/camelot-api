from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from camelot.backends import image_conversion

from camelot_api import service
from camelot_api.models import ExtractRequest
from camelot_api.pdfium_backend import ManagedPdfiumBackend


class EmptyTables(list):
    n = 0


class ExtractionConcurrencyTests(unittest.TestCase):
    def test_camelot_calls_are_serialized_across_requests(self) -> None:
        active = 0
        max_active = 0
        counter_lock = threading.Lock()
        start = threading.Barrier(4)
        original_backend = image_conversion.BACKENDS["pdfium"]
        flavors = ("lattice", "hybrid", "network", "auto")

        def read_pdf(*args, **kwargs):
            nonlocal active, max_active
            self.assertIs(image_conversion.BACKENDS["pdfium"], ManagedPdfiumBackend)
            with counter_lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.03)
                return EmptyTables()
            finally:
                with counter_lock:
                    active -= 1

        def extract(index):
            start.wait(timeout=5)
            return service._do_extract(
                f"sample-{index}.pdf", ExtractRequest(file_id=str(index), flavor=flavors[index])
            )

        with (
            patch.object(service, "get_config", return_value=SimpleNamespace(fallback_to_stream=True)),
            patch.object(service.camelot, "read_pdf", side_effect=read_pdf) as reader,
            patch.object(service, "_build_response", return_value=None),
            ThreadPoolExecutor(max_workers=4) as pool,
        ):
            list(pool.map(extract, range(4)))

        # Both the initial lattice call and the stream fallback must be protected.
        self.assertEqual(reader.call_count, 5)
        self.assertEqual(max_active, 1)
        self.assertIs(image_conversion.BACKENDS["pdfium"], original_backend)

    def test_read_failure_does_not_block_the_next_request(self) -> None:
        request = ExtractRequest(file_id="sample")
        original_backend = image_conversion.BACKENDS["pdfium"]
        with (
            patch.object(service, "get_config", return_value=SimpleNamespace(fallback_to_stream=False)),
            patch.object(service.camelot, "read_pdf", side_effect=[RuntimeError("render failed"), EmptyTables()]),
        ):
            with self.assertRaisesRegex(RuntimeError, "render failed"):
                service._do_extract("sample.pdf", request)
            self.assertIs(image_conversion.BACKENDS["pdfium"], original_backend)
            # Run on another thread so a leaked lock cannot pass via reentrancy.
            result = []
            finished = threading.Event()

            def extract():
                try:
                    result.append(service._do_extract("sample.pdf", request))
                finally:
                    finished.set()

            # A regression must not leave a non-daemon thread hanging the test runner.
            worker = threading.Thread(target=extract, daemon=True)
            worker.start()
            self.assertTrue(finished.wait(timeout=5), "extraction lock was not released")
            worker.join(timeout=1)

        self.assertTrue(result[0].success)
        self.assertIs(image_conversion.BACKENDS["pdfium"], original_backend)


if __name__ == "__main__":
    unittest.main()
