# THREAT_MODEL.md — "PDF ke Excel"

Scope: a desktop app that converts **confidential** scanned financial
PDFs to Excel, fully on-device. This document states plainly what data
is stored, where, what leaves the machine (nothing, by design), and the
limits of that protection. It is written so a security reviewer can
check the claims against the code.

## 1. Assets

* The source PDF (confidential financial scans).
* Extracted data: OCR text, corrected values, document-type labels.
* The Excel output workbook (visible values + full Audit sheet).

## 2. What is stored, and where

| Data | Location | Format | Notes |
|------|----------|--------|-------|
| Working session | `<pdf>.p2x` next to the source PDF | SQLite (WAL) | Plaintext. Holds all extracted + corrected values and the audit trail. |
| WAL / SHM sidecars | `<pdf>.p2x-wal`, `<pdf>.p2x-shm` | SQLite | Checkpointed + truncated on clean close; removed by "Hapus data kerja". |
| Output workbook | Documents (or a user-chosen folder) | .xlsx | Visible values + `Audit` + `Masalah` + `Ringkasan` sheets. |
| RapidOCR models | inside the app install | .onnx | Read-only; SHA-256-verified (see §5). |

The session file is deliberately **plaintext SQLite**. `secure_delete`
is ON (deleted rows are zeroed, not left in free pages) and the WAL is
checkpointed+truncated on close, so no extracted data lingers in the
sidecars after a clean exit.

## 3. Network behaviour

**No component makes an outbound network call on the document path.**
There is no cloud OCR, no telemetry, no analytics, no update check that
sees documents, no crash reporter.

* Default engine (RapidOCR): models are bundled and SHA-256-verified;
  the code fails closed (local error) rather than downloading if a model
  is missing/altered — so a network fetch is never even attempted.
* Optional engine (PaddleOCR PP-StructureV3): NOT in the shipped
  installer. If a technician installs it, the engine refuses to run
  unless its model pack is already cached locally
  (`~/.paddlex/official_models`), and sets `DISABLE_MODEL_SOURCE_CHECK`
  — it will not auto-download at runtime.

The CI "clean-machine" job runs the installed app with **outbound
network blocked** to prove the document path needs no network (Fase 6).

## 4. What we do NOT protect against (out of scope / OS responsibility)

These are real exposures the app cannot fully control. They are listed
so nobody assumes a guarantee that isn't there:

* **Windows pagefile / hibernation**: decrypted data in RAM may be
  written to `pagefile.sys` / `hiberfil.sys` by the OS. Mitigation is an
  OS/BitLocker concern, not something this app can guarantee.
* **Crash dumps**: a Windows Error Reporting dump of this process could
  contain in-memory document data. Disabling/handling WER is an OS
  policy decision.
* **Antivirus / EDR**: security software may read and upload the PDF or
  the output for scanning. This is outside app control.
* **Backups / file history / VSS**: OS or third-party backup may copy
  the session file and output.
* **Cloud-sync folders** (OneDrive, Google Drive, Dropbox, iCloud): the
  app *detects* when output would land in a synced folder and warns the
  user, and lets them pick a different folder — but if they proceed, the
  sync client copies the data off-device. Detection is best-effort
  (name/env-var based).
* **SSD/flash deletion is not forensically guaranteed**: wear-levelling
  means "Hapus data kerja" cannot promise the bytes are unrecoverable.
  The UI says this explicitly.
* **Cold-boot / physical access / privileged malware**: not in scope.

## 5. Integrity of the OCR models (supply chain)

The bundled RapidOCR models are pinned by SHA-256 in
`app/pipeline/engines/rapidocr_models.json`. On first use the engine
verifies each model file by name, size, and hash. A tampered or swapped
model produces a local error and the app will not run OCR — it will not
silently produce wrong numbers, and it will not reach the network to
"repair" itself.

## 6. Encryption of the session file (decision pending)

The session file is currently unencrypted. If encryption is required by
policy, the intended approach is the OS-provided mechanism (Windows
DPAPI, per-user) rather than any home-grown crypto — with the documented
trade-off that a DPAPI-encrypted file is bound to the Windows user
profile and is not portable to another machine/user. This is flagged
for the product owner (see `SECURITY_DECISIONS` in the final report); it
is not implemented yet.

## 7. Auditability (why plaintext is a feature here)

The `Audit` worksheet and the `.p2x` session preserve the **immutable
original OCR text** alongside every human correction, with editor
identity and timestamp. This is a deliberate finance-tie-out
requirement: the trail must be inspectable. Encrypting the workbook
would work against the reviewer's job; protection of the *output* is
left to filesystem/folder controls.
