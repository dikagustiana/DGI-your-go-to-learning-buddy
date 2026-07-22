"""Generate an SBOM + checksums for a release (stdlib only).

Produces, next to a built installer:
  * sbom.json      — CycloneDX-style component list from the installed
                     Python distributions plus the pinned OCR models.
  * SHA256SUMS.txt — SHA-256 of the installer (+ SBOM) for verification.

No third-party SBOM tool is required (keeps the build lean and offline).

Usage:  python installer/gen_sbom.py <installer.exe> [outdir]
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from importlib import metadata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import __version__  # noqa: E402


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _components() -> list[dict]:
    comps = []
    for dist in sorted(metadata.distributions(),
                       key=lambda d: (d.metadata["Name"] or "").lower()):
        name = dist.metadata["Name"]
        if not name:
            continue
        comps.append({
            "type": "library",
            "name": name,
            "version": dist.version,
            "licenses": [dist.metadata.get("License") or "UNKNOWN"],
        })
    # The pinned OCR models are supply-chain components too.
    try:
        from app.pipeline.engines.rapidocr_models import model_hashes
        for rel, sha in model_hashes().items():
            comps.append({"type": "data", "name": rel,
                          "version": sha[:12], "hashes": {"SHA-256": sha}})
    except Exception:
        pass
    return comps


def main(installer: str, outdir: str | None = None) -> None:
    outdir = outdir or os.path.dirname(os.path.abspath(installer))
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {"component": {"type": "application",
                                   "name": "PDF ke Excel",
                                   "version": __version__}},
        "components": _components(),
    }
    sbom_path = os.path.join(outdir, "sbom.json")
    with open(sbom_path, "w", encoding="utf-8") as f:
        json.dump(sbom, f, indent=2)

    sums_path = os.path.join(outdir, "SHA256SUMS.txt")
    with open(sums_path, "w", encoding="utf-8") as f:
        for target in (installer, sbom_path):
            if os.path.exists(target):
                f.write(f"{_sha256(target)}  {os.path.basename(target)}\n")

    print(f"wrote {sbom_path} ({len(sbom['components'])} components)")
    print(f"wrote {sums_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: gen_sbom.py <installer.exe> [outdir]", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
