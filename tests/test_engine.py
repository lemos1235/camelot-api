from __future__ import annotations

import argparse
import os
import unittest
from unittest.mock import MagicMock, patch

from camelot_api import config, service
from camelot_api.models import ExtractRequest
from tools.detect import build_kwargs as detect_build_kwargs


class EngineConfigTests(unittest.TestCase):
    def tearDown(self) -> None:
        config.reset_config()

    def test_default_engine_is_combined(self) -> None:
        config.reset_config()
        with patch.dict(os.environ, {}, clear=True), patch.object(config, "_load_toml", return_value={}):
            cfg = config.get_config()
            self.assertEqual(cfg.default_engine, "combined")

    def test_env_camelot_default_engine(self) -> None:
        config.reset_config()
        with patch.dict(os.environ, {"CAMELOT_DEFAULT_ENGINE": "vector"}, clear=True), patch.object(
            config, "_load_toml", return_value={}
        ):
            cfg = config.get_config()
            self.assertEqual(cfg.default_engine, "vector")

    def test_env_camelot_engine_fallback(self) -> None:
        config.reset_config()
        with patch.dict(os.environ, {"CAMELOT_ENGINE": "raster"}, clear=True), patch.object(
            config, "_load_toml", return_value={}
        ):
            cfg = config.get_config()
            self.assertEqual(cfg.default_engine, "raster")

    def test_toml_default_engine(self) -> None:
        config.reset_config()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            config, "_load_toml", return_value={"default_engine": "vector"}
        ):
            cfg = config.get_config()
            self.assertEqual(cfg.default_engine, "vector")

    def test_toml_engine_fallback(self) -> None:
        config.reset_config()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            config, "_load_toml", return_value={"engine": "raster"}
        ):
            cfg = config.get_config()
            self.assertEqual(cfg.default_engine, "raster")


class EngineServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        config.reset_config()

    def tearDown(self) -> None:
        config.reset_config()

    def test_lattice_uses_default_engine_when_unspecified(self) -> None:
        req = ExtractRequest(file_id="abc", flavor="lattice")
        kwargs = service._build_camelot_kwargs(req)
        self.assertEqual(kwargs.get("engine"), "combined")

    def test_lattice_uses_explicit_engine(self) -> None:
        req = ExtractRequest(file_id="abc", flavor="lattice", engine="vector")
        kwargs = service._build_camelot_kwargs(req)
        self.assertEqual(kwargs.get("engine"), "vector")

    def test_hybrid_uses_engine(self) -> None:
        req = ExtractRequest(file_id="abc", flavor="hybrid", engine="raster")
        kwargs = service._build_camelot_kwargs(req)
        self.assertEqual(kwargs.get("engine"), "raster")

    def test_stream_and_network_do_not_include_engine(self) -> None:
        for fl in ("stream", "network", "ml"):
            req = ExtractRequest(file_id="abc", flavor=fl, engine="vector")
            kwargs = service._build_camelot_kwargs(req)
            self.assertNotIn("engine", kwargs)

    def test_cache_key_equivalence_and_differentiation(self) -> None:
        # 未指定 engine 与显式指定默认 engine ("combined") 生成相同 key
        req_default = ExtractRequest(file_id="abc", flavor="lattice")
        req_explicit_combined = ExtractRequest(file_id="abc", flavor="lattice", engine="combined")
        key1 = service._make_cache_key("abc", req_default)
        key2 = service._make_cache_key("abc", req_explicit_combined)
        self.assertEqual(key1, key2)

        # 不同 engine 生成不同 key
        req_vector = ExtractRequest(file_id="abc", flavor="lattice", engine="vector")
        key3 = service._make_cache_key("abc", req_vector)
        self.assertNotEqual(key1, key3)

    @patch("camelot.read_pdf")
    def test_fallback_to_stream_strips_engine(self, mock_read_pdf: MagicMock) -> None:
        empty_tables = MagicMock()
        empty_tables.n = 0

        stream_tables = MagicMock()
        stream_tables.n = 1
        stream_tables.__iter__.return_value = []

        mock_read_pdf.side_effect = [empty_tables, stream_tables]

        req = ExtractRequest(file_id="abc", flavor="lattice", engine="vector")
        service._do_extract("dummy.pdf", req)

        self.assertEqual(mock_read_pdf.call_count, 2)
        # 第一次调用 lattice，包含 engine='vector'
        first_call_kwargs = mock_read_pdf.call_args_list[0].kwargs
        self.assertEqual(first_call_kwargs.get("engine"), "vector")
        # 第二次回退 stream 调用，不包含 engine
        second_call_kwargs = mock_read_pdf.call_args_list[1].kwargs
        self.assertNotIn("engine", second_call_kwargs)


class DetectCliEngineTests(unittest.TestCase):
    def test_detect_build_kwargs_lattice_engine(self) -> None:
        args = argparse.Namespace(
            flavor="lattice",
            pages="1",
            split_text=False,
            flag_size=False,
            strip_text=None,
            process_background=False,
            line_scale=15,
            engine="vector",
            line_tol=None,
            joint_tol=None,
            threshold_blocksize=None,
            threshold_constant=None,
            iterations=None,
            resolution=None,
            copy_text=None,
            shift_text=None,
        )
        kwargs = detect_build_kwargs(args)
        self.assertEqual(kwargs.get("engine"), "vector")

    def test_detect_build_kwargs_stream_ignores_engine(self) -> None:
        args = argparse.Namespace(
            flavor="stream",
            pages="1",
            split_text=False,
            flag_size=False,
            strip_text=None,
            process_background=False,
            engine="vector",
            edge_tol=None,
            row_tol=None,
            column_tol=None,
            copy_text=None,
            shift_text=None,
        )
        kwargs = detect_build_kwargs(args)
        self.assertNotIn("engine", kwargs)


if __name__ == "__main__":
    unittest.main()
