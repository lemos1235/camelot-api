from __future__ import annotations

import gc
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image
from camelot.backends import ImageConversionBackend, image_conversion
from camelot.parsers import Hybrid, Lattice

from camelot_api import pdfium_backend, service
from camelot_api.models import ExtractRequest
from camelot_api.pdfium_backend import ManagedPdfiumBackend, managed_pdfium_backend


class PdfiumResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.closed = []
        self.doc = MagicMock()
        self.page = self.doc.__getitem__.return_value
        self.bitmap = self.page.render.return_value
        self.image = self.bitmap.to_pil.return_value
        for name, resource in (
            ("document", self.doc), ("page", self.page),
            ("bitmap", self.bitmap), ("image", self.image),
        ):
            resource.close.side_effect = lambda name=name: self.closed.append(name)
        self.factory_patch = patch.object(
            pdfium_backend.pdfium_backend.pdfium, "PdfDocument", return_value=self.doc
        )
        self.factory = self.factory_patch.start()
        self.addCleanup(self.factory_patch.stop)
        self.backend = ManagedPdfiumBackend()

    def test_convert_closes_every_resource_in_reverse_order(self) -> None:
        self.backend.convert("sample.pdf", "sample.png", resolution=144, page=2)
        self.doc.init_forms.assert_called_once_with()
        self.doc.__getitem__.assert_called_once_with(1)
        self.page.render.assert_called_once_with(scale=2)
        self.image.save.assert_called_once_with("sample.png")
        self.assertEqual(self.closed, ["image", "bitmap", "page", "document"])

    def test_partial_failures_close_all_acquired_resources(self) -> None:
        stages = (
            (self.doc.init_forms, ["document"]),
            (self.doc.__getitem__, ["document"]),
            (self.page.render, ["page", "document"]),
            (self.bitmap.to_pil, ["bitmap", "page", "document"]),
            (self.image.save, ["image", "bitmap", "page", "document"]),
        )
        for method, expected in stages:
            with self.subTest(stage=expected):
                self.closed.clear()
                method.side_effect = RuntimeError("render failed")
                with self.assertRaisesRegex(RuntimeError, "render failed"):
                    self.backend.convert("sample.pdf", "sample.png")
                self.assertEqual(self.closed, expected)
                method.side_effect = None

    def test_cleanup_failure_does_not_skip_parent_cleanup(self) -> None:
        self.bitmap.close.side_effect = RuntimeError("close failed")
        with self.assertRaisesRegex(RuntimeError, "close failed"):
            self.backend.convert("sample.pdf", "sample.png")
        self.assertEqual(self.closed, ["image", "page", "document"])

    def test_to_array_returns_contiguous_independent_bgr_pixels(self) -> None:
        rgb_image = Image.new("RGB", (2, 2), (11, 22, 33))
        self.image.convert.return_value = rgb_image
        with patch.object(rgb_image, "close", wraps=rgb_image.close) as close_rgb:
            array = self.backend.to_array("sample.pdf")
            close_rgb.assert_called_once_with()
        np.testing.assert_array_equal(array, np.full((2, 2, 3), [33, 22, 11], dtype=np.uint8))
        self.assertTrue(array.flags.c_contiguous)
        self.assertTrue(array.flags.owndata)
        self.assertEqual(self.closed, ["image", "bitmap", "page", "document"])

    def test_rgb_conversion_failure_closes_render_resources(self) -> None:
        self.image.convert.side_effect = RuntimeError("RGB failed")
        with self.assertRaisesRegex(RuntimeError, "RGB failed"):
            self.backend.to_array("sample.pdf")
        self.assertEqual(self.closed, ["image", "bitmap", "page", "document"])

    def test_missing_pdfium_reports_error_before_opening_document(self) -> None:
        with patch.object(self.backend, "installed", return_value=False):
            with self.assertRaisesRegex(OSError, "pypdfium2 is not available"):
                self.backend.convert("sample.pdf", "sample.png")
        self.factory.assert_not_called()


class PdfiumRegistryTests(unittest.TestCase):
    def test_registry_is_restored_after_success_and_failure(self) -> None:
        original = image_conversion.BACKENDS["pdfium"]
        for fail in (False, True):
            with self.subTest(fail=fail):
                try:
                    with managed_pdfium_backend():
                        self.assertIs(image_conversion.BACKENDS["pdfium"], ManagedPdfiumBackend)
                        self.assertIsInstance(ImageConversionBackend().backend, ManagedPdfiumBackend)
                        if fail:
                            raise RuntimeError("parse failed")
                except RuntimeError:
                    if not fail:
                        raise
                self.assertIs(image_conversion.BACKENDS["pdfium"], original)

    def test_nested_context_restores_the_outer_backend(self) -> None:
        original = image_conversion.BACKENDS["pdfium"]
        with managed_pdfium_backend():
            with managed_pdfium_backend():
                self.assertIs(image_conversion.BACKENDS["pdfium"], ManagedPdfiumBackend)
            self.assertIs(image_conversion.BACKENDS["pdfium"], ManagedPdfiumBackend)
        self.assertIs(image_conversion.BACKENDS["pdfium"], original)


class PdfiumFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(managed_pdfium_backend())

    def test_convert_preserves_ghostscript_fallback(self) -> None:
        converter = ImageConversionBackend()
        fallback = MagicMock()
        with (
            patch.object(converter.backend, "convert", side_effect=RuntimeError("render failed")),
            patch.dict(image_conversion.BACKENDS, {"ghostscript": lambda: fallback}),
        ):
            converter.convert("sample.pdf", "sample.png", page=2)
        fallback.convert.assert_called_once_with("sample.pdf", "sample.png", page=2)

    def test_disabled_fallback_propagates_conversion_errors(self) -> None:
        converter = ImageConversionBackend(use_fallback=False)
        with patch.object(converter.backend, "convert", side_effect=RuntimeError("render failed")):
            with self.assertRaises(image_conversion.ImageConversionError):
                converter.convert("sample.pdf", "sample.png")

    def test_disabled_fallback_does_not_retry_array_rendering(self) -> None:
        kwargs = service._build_camelot_kwargs(
            ExtractRequest(file_id="sample", use_fallback=False)
        )
        kwargs.pop("flavor")
        converter = Lattice(**kwargs).icb
        with (
            patch.object(converter.backend, "to_array", side_effect=RuntimeError("render failed")),
            patch.object(converter.backend, "convert") as convert,
        ):
            with self.assertRaises(image_conversion.ImageConversionError):
                converter.to_array("sample.pdf")
        convert.assert_not_called()

    def test_to_array_preserves_fallback(self) -> None:
        converter = ImageConversionBackend()
        fallback = MagicMock()

        def save_fallback(pdf_path, png_path, page):
            with Image.new("RGB", (2, 2), (11, 22, 33)) as image:
                image.save(png_path)

        fallback.convert.side_effect = save_fallback
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(converter.backend, "to_array", side_effect=RuntimeError("render failed")),
            patch.object(converter.backend, "convert", side_effect=RuntimeError("render failed")),
            patch.dict(image_conversion.BACKENDS, {"ghostscript": lambda: fallback}),
            patch("camelot.utils.build_file_path_in_temp_dir", return_value=str(Path(directory) / "fallback.png")),
        ):
            array = converter.to_array("sample.pdf", page=2)
        np.testing.assert_array_equal(array, np.full((2, 2, 3), [33, 22, 11], dtype=np.uint8))
        fallback.convert.assert_called_once()


class PdfiumIntegrationTests(unittest.TestCase):
    def test_real_camelot_extracts_table_with_managed_backend(self) -> None:
        contents = b"\n".join([
            b"1 w 40 50 m 240 50 l S 40 100 m 240 100 l S 40 150 m 240 150 l S",
            b"40 50 m 40 150 l S 140 50 m 140 150 l S 240 50 m 240 150 l S",
            b"BT /F1 12 Tf 50 120 Td (Name) Tj ET",
            b"BT /F1 12 Tf 150 120 Td (Count) Tj ET",
            b"BT /F1 12 Tf 50 70 Td (Alice) Tj ET",
            b"BT /F1 12 Tf 150 70 Td (10) Tj ET",
        ])
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            f"<< /Length {len(contents)} >>\nstream\n".encode() + contents + b"\nendstream",
        ]
        document = bytearray(b"%PDF-1.4\n")
        offsets = []
        for number, obj in enumerate(objects, start=1):
            offsets.append(len(document))
            document.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
        xref_offset = len(document)
        document.extend(b"xref\n0 6\n0000000000 65535 f \n")
        for offset in offsets:
            document.extend(f"{offset:010d} 00000 n \n".encode())
        document.extend(
            f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
        )
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "table.pdf"
            pdf_path.write_bytes(document)
            with (
                patch.object(service, "get_config", return_value=SimpleNamespace(fallback_to_stream=False)),
                self.assertNoLogs("pypdfium2", level="WARNING"),
                patch("sys.unraisablehook") as finalizer_error,
                patch.object(
                    ManagedPdfiumBackend, "to_array", autospec=True,
                    side_effect=ManagedPdfiumBackend.to_array,
                ) as render_array,
                patch.object(
                    ManagedPdfiumBackend, "convert", autospec=True,
                    side_effect=ManagedPdfiumBackend.convert,
                ) as render_png,
                ThreadPoolExecutor(max_workers=4) as pool,
            ):
                futures = [
                    pool.submit(
                        service._do_extract, str(pdf_path),
                        ExtractRequest(file_id="table", flavor=flavor),
                    )
                    for flavor in ("lattice", "hybrid", "auto") * 4
                ]
                for future in futures:
                    result = future.result(timeout=15)
                    self.assertTrue(result.success)
                    self.assertEqual(result.total_tables, 1)
                    self.assertIn("Alice", [cell.text for cell in result.tables[0].cells])
                self.assertEqual(render_array.call_count, 8)
                self.assertEqual(render_png.call_count, 4)
                gc.collect()
                finalizer_error.assert_not_called()

    def test_real_pdf_array_matches_png_and_survives_cleanup(self) -> None:
        backend = ManagedPdfiumBackend()
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "sample.pdf"
            png_path = Path(directory) / "sample.png"
            with Image.new("RGB", (72, 36), "white") as source:
                source.save(pdf_path, "PDF", resolution=72)
            backend.convert(str(pdf_path), str(png_path), resolution=72)
            array = backend.to_array(str(pdf_path), resolution=72)
            self.assertEqual(array.shape, (36, 72, 3))
            with Image.open(png_path) as png:
                np.testing.assert_array_equal(array, np.asarray(png)[:, :, ::-1])
            # Invalid page loading must also release the document cleanly.
            with self.assertRaises(pdfium_backend.pdfium_backend.pdfium.PdfiumError):
                backend.to_array(str(pdf_path), resolution=72, page=2)

    def test_service_uses_managed_backend_in_actual_lattice_and_hybrid_parsers(self) -> None:
        original = image_conversion.BACKENDS["pdfium"]

        def read_pdf(file_path, pages, flavor, **kwargs):
            parser = {"lattice": Lattice, "hybrid": Hybrid}[flavor](**kwargs)
            lattice = parser.lattice_parser if flavor == "hybrid" else parser
            self.assertIsInstance(lattice.icb.backend, ManagedPdfiumBackend)
            self.assertEqual(lattice.icb.fallbacks, ["ghostscript", "poppler"])
            return SimpleNamespace(n=0)

        with (
            patch.object(service, "get_config", return_value=SimpleNamespace(fallback_to_stream=False)),
            patch.object(service.camelot, "read_pdf", side_effect=read_pdf),
            patch.object(service, "_build_response", return_value=None),
        ):
            for flavor in ("lattice", "hybrid"):
                with self.subTest(flavor=flavor):
                    service._do_extract("sample.pdf", ExtractRequest(file_id="sample", flavor=flavor))
                    self.assertIs(image_conversion.BACKENDS["pdfium"], original)


if __name__ == "__main__":
    unittest.main()
