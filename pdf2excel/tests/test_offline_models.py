"""Regression tests for fail-closed model verification and sync detection
(Fase 4)."""

import os

import pytest

from app.gui.paths import sync_service_for
from app.pipeline.engines.rapidocr_models import (load_manifest, model_hashes,
                                                  verify_models)


def test_manifest_has_three_models():
    models = load_manifest()["models"]
    assert len(models) >= 3
    assert all("sha256" in m and "size" in m for m in models.values())


def test_verify_models_passes_on_real_install():
    # The installed models must match the committed manifest exactly.
    assert verify_models(deep=True).ok


def test_verify_models_fails_on_tampered_manifest(monkeypatch):
    import app.pipeline.engines.rapidocr_models as mod
    good = load_manifest()
    bad = {**good, "models": {
        k: {**v, "sha256": "0" * 64} for k, v in good["models"].items()}}
    monkeypatch.setattr(mod, "load_manifest", lambda: bad)
    check = verify_models(deep=True)
    assert not check.ok
    assert "sidik jari" in check.detail.lower() or "sha" in check.detail.lower()


def test_verify_models_fails_when_file_missing(monkeypatch):
    import app.pipeline.engines.rapidocr_models as mod
    good = load_manifest()
    bad = {**good, "models": {
        **good["models"],
        "models/does_not_exist.onnx": {"sha256": "0" * 64, "size": 1}}}
    monkeypatch.setattr(mod, "load_manifest", lambda: bad)
    check = verify_models(deep=False)
    assert not check.ok
    assert "hilang" in check.detail


def test_engine_unavailable_when_models_bad(monkeypatch):
    from app.pipeline.engines.rapidocr_engine import RapidOCREngine
    monkeypatch.setattr(RapidOCREngine, "models_present",
                        classmethod(lambda cls, deep=False: False))
    assert RapidOCREngine.is_available() is False


def test_model_hashes_exposed():
    hashes = model_hashes()
    assert hashes and all(len(h) == 64 for h in hashes.values())


@pytest.mark.parametrize("path, expected", [
    ("/home/u/OneDrive/Documents/x.xlsx", "OneDrive"),
    ("C:/Users/u/OneDrive - Corp/rk.xlsx", "OneDrive"),
    ("/Users/u/Google Drive/a.xlsx", "Google Drive"),
    ("/home/u/Dropbox/a.xlsx", "Dropbox"),
    ("/Users/u/Library/Mobile Documents/iCloud~x/a.xlsx", "iCloud"),
])
def test_sync_folder_detected(path, expected):
    assert sync_service_for(path) == expected


def test_plain_folder_not_flagged():
    assert sync_service_for("/home/u/Documents/x.xlsx") is None
    assert sync_service_for("C:/Users/u/Documents/rk.xlsx") is None
