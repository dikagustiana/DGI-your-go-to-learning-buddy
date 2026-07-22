"""RapidOCR bundled-model manifest verification (fail-closed, offline).

The app promises to never download a model. To keep that promise
honest, the default engine verifies at startup that the bundled ONNX
models are exactly the ones it was built against — by NAME and SHA-256,
not merely "there are three .onnx files". A missing, truncated, or
swapped model produces a clear local error; it must never fall through
to any network fetch.

Regenerate the manifest after a deliberate model upgrade:

    python -m app.pipeline.engines.rapidocr_models --write
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass

_MANIFEST_PATH = pathlib.Path(__file__).with_name("rapidocr_models.json")


@dataclass
class ModelCheck:
    ok: bool
    detail: str


def load_manifest() -> dict:
    with open(_MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def _package_dir() -> pathlib.Path:
    import rapidocr_onnxruntime
    return pathlib.Path(rapidocr_onnxruntime.__file__).parent


def _sha256(path: pathlib.Path, limit: int | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_models(deep: bool = True) -> ModelCheck:
    """Check the bundled models against the manifest.

    ``deep=False`` checks presence + size only (fast, for the frequent
    GUI availability probe); ``deep=True`` also verifies SHA-256.
    """
    try:
        manifest = load_manifest()
        pkg = _package_dir()
    except Exception as exc:
        return ModelCheck(False, f"tidak bisa membaca manifest model: {exc}")

    for rel, meta in manifest.get("models", {}).items():
        path = pkg / rel
        if not path.exists():
            return ModelCheck(
                False, f"berkas model hilang: {rel}. Instalasi rusak — "
                "pasang ulang aplikasi (jangan sambungkan ke internet).")
        size = path.stat().st_size
        if size != meta["size"]:
            return ModelCheck(
                False, f"ukuran model {rel} tidak sesuai "
                f"({size} != {meta['size']}). Berkas rusak.")
        if deep and _sha256(path) != meta["sha256"]:
            return ModelCheck(
                False, f"sidik jari (SHA-256) model {rel} tidak cocok — "
                "berkas berbeda dari yang seharusnya. Pasang ulang aplikasi.")
    return ModelCheck(True, "ok")


def model_hashes() -> dict[str, str]:
    """name -> sha256 from the manifest (recorded in the session)."""
    return {k: v["sha256"] for k, v in load_manifest().get("models", {}).items()}


def _write_manifest() -> None:  # pragma: no cover - maintenance tool
    import rapidocr_onnxruntime
    pkg = _package_dir()
    models = {}
    for p in sorted(pkg.glob("**/*.onnx")):
        models[p.relative_to(pkg).as_posix()] = {
            "sha256": _sha256(p), "size": p.stat().st_size}
    doc = load_manifest()
    doc["models"] = models
    doc["rapidocr_onnxruntime_version"] = getattr(
        rapidocr_onnxruntime, "__version__", "unknown")
    with open(_MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    print(f"wrote {_MANIFEST_PATH} with {len(models)} models")


if __name__ == "__main__":  # pragma: no cover
    import sys
    if "--write" in sys.argv:
        _write_manifest()
    else:
        print(verify_models(deep=True))
