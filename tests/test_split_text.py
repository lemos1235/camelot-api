from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from camelot_api import config, service
from camelot_api.models import ExtractRequest


class SplitTextConfigTests(unittest.TestCase):
    def tearDown(self) -> None:
        config.reset_config()

    def _cfg(self, env: dict | None = None, toml: dict | None = None):
        config.reset_config()
        with patch.dict(os.environ, env or {}, clear=True), patch.object(
            config, "_load_toml", return_value=toml or {}
        ):
            return config.get_config()

    def test_default_is_false(self) -> None:
        self.assertFalse(self._cfg().default_split_text)

    def test_env_override(self) -> None:
        cfg = self._cfg(env={"CAMELOT_SPLIT_TEXT": "true"})
        self.assertTrue(cfg.default_split_text)

    def test_toml_override(self) -> None:
        cfg = self._cfg(toml={"split_text": True})
        self.assertTrue(cfg.default_split_text)


class SplitTextServiceTests(unittest.TestCase):
    def tearDown(self) -> None:
        config.reset_config()

    def _with_config(self, default_split_text: bool):
        cfg = SimpleNamespace(default_split_text=default_split_text, default_engine="combined")
        return patch.object(service, "get_config", return_value=cfg)

    def test_uses_config_default_when_unspecified(self) -> None:
        with self._with_config(True):
            req = ExtractRequest(file_id="abc", flavor="lattice")
            kwargs = service._build_camelot_kwargs(req)
        self.assertTrue(kwargs["split_text"])

    def test_request_false_overrides_config_true(self) -> None:
        with self._with_config(True):
            req = ExtractRequest(file_id="abc", flavor="lattice", split_text=False)
            kwargs = service._build_camelot_kwargs(req)
        self.assertFalse(kwargs["split_text"])

    def test_request_true_overrides_config_false(self) -> None:
        with self._with_config(False):
            req = ExtractRequest(file_id="abc", flavor="lattice", split_text=True)
            kwargs = service._build_camelot_kwargs(req)
        self.assertTrue(kwargs["split_text"])

    def test_cache_key_uses_effective_split_text(self) -> None:
        with self._with_config(True):
            unresolved = ExtractRequest(file_id="abc", flavor="lattice")
            explicit = ExtractRequest(file_id="abc", flavor="lattice", split_text=True)
            opposite = ExtractRequest(file_id="abc", flavor="lattice", split_text=False)
            self.assertEqual(
                service._make_cache_key("abc", unresolved),
                service._make_cache_key("abc", explicit),
            )
            self.assertNotEqual(
                service._make_cache_key("abc", unresolved),
                service._make_cache_key("abc", opposite),
            )


if __name__ == "__main__":
    unittest.main()
