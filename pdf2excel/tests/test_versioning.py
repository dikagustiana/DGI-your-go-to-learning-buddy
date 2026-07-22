"""Single-source versioning + SBOM generation (Fase 7)."""

import json
import subprocess
import sys
from pathlib import Path

import app

ROOT = Path(__file__).resolve().parent.parent


def test_version_is_single_sourced(tmp_path, monkeypatch):
    # gen_version.py must emit exactly app.__version__ into version.iss.
    monkeypatch.chdir(ROOT)
    subprocess.run([sys.executable, "installer/gen_version.py"], check=True)
    text = (ROOT / "installer" / "version.iss").read_text()
    assert f'#define MyAppVersion "{app.__version__}"' in text
    assert app.APP_MUTEX in text


def test_setup_iss_includes_generated_version():
    iss = (ROOT / "installer" / "setup.iss").read_text()
    assert '#include "version.iss"' in iss
    assert "AppMutex={#MyAppMutex}" in iss     # blocks install while running


def test_sbom_lists_components_and_checksums(tmp_path):
    fake = tmp_path / "PDF-ke-Excel-Setup.exe"
    fake.write_bytes(b"pretend installer")
    subprocess.run(
        [sys.executable, str(ROOT / "installer" / "gen_sbom.py"),
         str(fake), str(tmp_path)], check=True)

    sbom = json.loads((tmp_path / "sbom.json").read_text())
    assert sbom["metadata"]["component"]["version"] == app.__version__
    names = {c["name"] for c in sbom["components"]}
    # Core runtime deps must appear in the inventory.
    assert any("rapidocr" in n.lower() for n in names)
    assert any(n.lower() in ("pymupdf", "fitz") for n in names) or \
        any("mupdf" in n.lower() for n in names)

    sums = (tmp_path / "SHA256SUMS.txt").read_text()
    assert "PDF-ke-Excel-Setup.exe" in sums
    assert len(sums.split()[0]) == 64          # a real SHA-256 hex digest


def test_ocr_models_in_sbom(tmp_path):
    fake = tmp_path / "s.exe"
    fake.write_bytes(b"x")
    subprocess.run(
        [sys.executable, str(ROOT / "installer" / "gen_sbom.py"),
         str(fake), str(tmp_path)], check=True)
    sbom = json.loads((tmp_path / "sbom.json").read_text())
    data = [c for c in sbom["components"] if c.get("type") == "data"]
    assert any(".onnx" in c["name"] for c in data)   # models are tracked
