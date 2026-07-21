# BUILD.md — Cara membangun installer "PDF ke Excel"

Dokumen ini untuk maintainer. Panduan pengguna akhir ada di
`CARA-PAKAI.md`.

Hasil akhirnya: **satu file `PDF-ke-Excel-Setup.exe`** yang bisa
diberikan ke pengguna — mereka tinggal double-click, Next → Next →
Selesai. Tidak perlu Python, internet, atau hak admin di komputer
pengguna.

---

## Cara A — Build otomatis lewat GitHub Actions (disarankan)

Workflow `.github/workflows/build-windows-installer.yml` berjalan
otomatis setiap ada push ke branch `claude/pdf-to-excel-ocr-app-8079cd`
yang menyentuh folder `pdf2excel/`. Workflow ini:

1. mem-freeze aplikasi dengan PyInstaller di runner Windows asli;
2. menguji exe hasil freeze dengan OCR sungguhan (gagal keras bila model
   RapidOCR tidak ikut ter-bundle, atau bila PaddleOCR bocor ke bundle);
3. meng-compile installer dengan Inno Setup;
4. **uji "mesin bersih"**: silent-install `Setup.exe`, lalu menjalankan
   aplikasi yang ter-install untuk mengonversi sample PDF;
5. meng-upload `Setup.exe` sebagai artifact.

Mengambil hasilnya: buka tab **Actions** di GitHub → pilih run "Build
Windows installer" yang hijau → bagian **Artifacts** → unduh
`PDF-ke-Excel-Setup`.

> ⚠ Actions hanya berjalan bila akun GitHub tidak terkunci masalah
> billing. Kalau run gagal dalam hitungan detik dengan pesan *"account
> is locked due to a billing issue"*, selesaikan dulu di
> https://github.com/settings/billing lalu jalankan ulang run-nya
> (tombol **Re-run all jobs**).

---

## Cara B — Build lokal di PC Windows (tanpa GitHub Actions, gratis)

Prasyarat (sekali saja):

* Windows 10/11 64-bit
* Python 3.11+ — https://www.python.org/downloads/ (centang **Add
  Python to PATH**)
* Inno Setup 6.5+ — https://jrsoftware.org/isdl.php
* Kode sumbernya — clone dengan Git, **atau tanpa Git sama sekali**:
  buka halaman repo di GitHub → pilih branch
  `claude/pdf-to-excel-ocr-app-8079cd` → **Code → Download ZIP** →
  ekstrak.

### Cara paling mudah: dobel-klik `build-installer.bat`

Di dalam folder `pdf2excel` ada **`build-installer.bat`**. Dobel-klik
file itu — script akan memeriksa Python & Inno Setup, menyiapkan
lingkungan, mem-freeze aplikasi, **menguji hasilnya dengan OCR
sungguhan**, lalu membungkus installer. Kalau semua beres, di akhir
tertulis lokasi `installer\Output\PDF-ke-Excel-Setup.exe`. Build
pertama ±10–20 menit (unduh dependensi); build berikutnya jauh lebih
cepat.

### Atau manual, langkah demi langkah:

```bat
git clone https://github.com/dikagustiana/DGI-your-go-to-learning-buddy.git
cd DGI-your-go-to-learning-buddy
git checkout claude/pdf-to-excel-ocr-app-8079cd
cd pdf2excel

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pyinstaller

pyinstaller pdf2excel.spec --noconfirm

"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\setup.iss
```

Hasil: `installer\Output\PDF-ke-Excel-Setup.exe`.

Smoke test sebelum dibagikan (wajib):

```bat
python samples\make_sample.py sample.pdf
dist\pdf2excel\pdf2excel-cli.exe inspect sample.pdf
:: harus menampilkan:  engines: {'rapidocr': True, 'paddle-ppstructure': False}
dist\pdf2excel\pdf2excel-cli.exe convert sample.pdf -o sample.xlsx --no-session
:: harus menghasilkan sample.xlsx tanpa error dan TANPA download apa pun
```

Catatan penting:

* **Jangan build di mesin yang ter-install PaddleOCR** tanpa memeriksa
  hasilnya — spec sudah meng-exclude paddle, dan smoke test di atas
  memverifikasinya (`'paddle-ppstructure': False`).
* PyInstaller **tidak bisa cross-compile**: installer Windows harus
  di-build di Windows.
* Bundle memakai mode one-folder (bukan one-file) dengan sengaja:
  one-file membuat startup lambat dan sering dicurigai antivirus.

---

## Checklist uji "mesin bersih" (manual)

Lakukan sekali per rilis, di PC Windows yang **tidak punya Python**
(atau akun/user Windows baru):

1. Matikan Wi-Fi / cabut kabel LAN (uji offline).
2. Salin `PDF-ke-Excel-Setup.exe` lewat flashdisk, lalu double-click.
3. SmartScreen mungkin muncul ("Windows protected your PC") →
   **More info → Run anyway** (lihat bagian SmartScreen di bawah).
4. Wizard harus tampil dalam bahasa Indonesia; klik Lanjut → Pasang →
   Selesai. **Tidak boleh muncul prompt admin (UAC)**.
5. Pastikan ada ikon **PDF ke Excel** di Desktop dan di Start Menu.
6. Buka aplikasinya, pilih sebuah PDF hasil scan, jalankan konversi
   sampai selesai, buka file Excel hasilnya. Masih dalam keadaan
   offline — tidak boleh ada error jaringan/download.
7. Buka **Settings → Apps → Installed apps**: "PDF ke Excel" harus
   terdaftar; klik **Uninstall** dan pastikan bersih.

---

## Menghilangkan peringatan SmartScreen ("unknown publisher")

`Setup.exe` yang tidak ditandatangani akan memunculkan peringatan biru
SmartScreen di komputer pengguna — membingungkan untuk pengguna lansia.
Dua jalan resmi menghilangkannya (tidak menghalangi rilis pertama;
pengguna tetap bisa klik "More info → Run anyway"):

**(a) Sertifikat code-signing.**
Beli sertifikat *OV* atau *EV code signing* dari CA (Sectigo, DigiCert,
SSL.com; kisaran $100–400/tahun, perlu verifikasi identitas
perusahaan), lalu tandatangani exe dan installer saat build:

```bat
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
  /f sertifikat.pfx /p KATASANDI installer\Output\PDF-ke-Excel-Setup.exe
```

Dengan sertifikat OV, reputasi SmartScreen tetap perlu terbangun dari
jumlah unduhan; dengan EV, peringatan biasanya hilang seketika.

**(b) Microsoft Store.**
Kemas aplikasi sebagai MSIX dan terbitkan lewat Partner Center
(pendaftaran developer perorangan ±$19 sekali bayar). Aplikasi dari
Store tidak kena SmartScreen sama sekali, update otomatis, dan
pengalaman installnya paling sederhana untuk pengguna awam. Jalur ini
lebih panjang (sertifikasi Store, kebijakan konten) — scaffolding MSIX
dan checklist submission dibuat terpisah bila diperlukan.
