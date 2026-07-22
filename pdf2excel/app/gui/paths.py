"""Output-location safety helpers.

Confidential financial output must not be dropped into a cloud-synced
folder (OneDrive, Google Drive, Dropbox, iCloud) without the user
knowing — that would copy the data off the machine, defeating the
offline guarantee. This detects such folders so the UI can warn.
"""

from __future__ import annotations

import os

# Case-insensitive path fragments that indicate a sync root.
_SYNC_MARKERS = (
    "onedrive", "google drive", "googledrive", "dropbox",
    "icloud", "icloud drive", "box sync", "pcloud", "mega",
)


def sync_service_for(path: str) -> str | None:
    """Return a human-readable sync-service name if ``path`` is inside a
    known cloud-sync folder, else None."""
    norm = os.path.normpath(os.path.abspath(path)).replace("\\", "/").lower()
    parts = norm.split("/")
    for part in parts:
        for marker in _SYNC_MARKERS:
            if marker in part:
                # Normalize to a friendly label.
                if "onedrive" in part:
                    return "OneDrive"
                if "google" in part:
                    return "Google Drive"
                if "dropbox" in part:
                    return "Dropbox"
                if "icloud" in part:
                    return "iCloud"
                return part
    # Windows also flags OneDrive via an environment variable.
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if onedrive:
        od = os.path.normpath(onedrive).replace("\\", "/").lower()
        if norm.startswith(od):
            return "OneDrive"
    return None
