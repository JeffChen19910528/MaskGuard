# MaskGuard

Image sensitive-data detection and redaction pipeline. Detects personal data,
financial data, credentials, and business-confidential text in images via
local OCR + rule-based/local-AI classification, then masks/blurs/pixelates it
in place. See `Skill.md` for the full specification this implements.

## Setup

```bash
python -m pip install -e .
```

OCR requires the **Tesseract binary** to be installed and on `PATH` (this is
separate from — and in addition to — the `pytesseract` Python package, which
is just a thin subprocess wrapper around it).

### Windows

```powershell
winget install --id UB-Mannheim.TesseractOCR -e
```

Installs to `C:\Program Files\Tesseract-OCR` and (after a new shell/session)
puts `tesseract.exe` on `PATH`. **Known gotcha, confirmed on this project:**
the winget/UB-Mannheim package's bundled `tessdata` only ships `eng` (+`osd`)
— `chi_tra` (Traditional Chinese) is **not** included and must be added
manually:

```powershell
# Download the language pack Tesseract's own project publishes:
Invoke-WebRequest -Uri "https://github.com/tesseract-ocr/tessdata/raw/main/chi_tra.traineddata" -OutFile "$env:LOCALAPPDATA\tessdata\chi_tra.traineddata"
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata" "$env:LOCALAPPDATA\tessdata\"
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\osd.traineddata" "$env:LOCALAPPDATA\tessdata\"
# Point Tesseract at a language-data directory you can write to without admin rights:
$env:TESSDATA_PREFIX = "$env:LOCALAPPDATA\tessdata"
```

(Writing directly into `C:\Program Files\Tesseract-OCR\tessdata\` requires an
elevated/admin shell — the `TESSDATA_PREFIX` env var pointing at a
user-writable copy avoids that.) Verify with `tesseract --list-langs` — it
should print `chi_tra`, `eng`, `osd`.

If `tesseract` isn't on `PATH` at all, either open a new terminal (winget
updates the registry `PATH`, not your current shell) or pass the binary path
explicitly: `LocalOcrEngine(tesseract_cmd=r"C:\Program Files\Tesseract-OCR\tesseract.exe")`.

### Linux (Debian/Ubuntu)

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-tra tesseract-ocr-eng
```

Other distros: `dnf install tesseract tesseract-langpack-chi_tra` (Fedora) or
build from https://github.com/tesseract-ocr/tesseract. Verify with
`tesseract --list-langs`.

### macOS

```bash
brew install tesseract tesseract-lang   # tesseract-lang bundles all language packs, incl. chi_tra
```

Verify with `tesseract --list-langs`.

### Verifying the environment yourself

```bash
python tests/e2e/_environment.py
```

Prints Python version, whether `pytesseract` imports, the resolved
`tesseract` binary path, `tesseract --version` output, and which of
`eng`/`chi_tra` are actually available — this is the same check the E2E test
suite (`pytest -m e2e`) runs before every test, via the `ocr_env` fixture in
`tests/e2e/conftest.py`. If the environment isn't ready, E2E tests report
**SKIPPED** (never a false PASS) with the specific missing piece named.

## Usage

```bash
imgmask input.png --output ./output
imgmask input.png --output ./output --mode strict --verify
imgmask ./input_folder --output ./output --recursive
```

Output layout (Skill.md §24):

```
output/
├── processed/<name>_masked.png
├── report/<name>_masked.json      # processing_report.json — no raw sensitive text
└── audit.log                      # append-only, type/confidence/region only
```

`--mode strict` enables Skill.md §40 Strict Mode: local-only OCR/AI, no cloud
upload, verification required, and a failed verification blocks output
entirely (no image is written).

## Tests

```bash
python -m pytest              # unit tests only — no Tesseract required
python -m pytest -m e2e       # real-OCR end-to-end tests — requires Tesseract (see above)
```

Unit tests exercise detection/risk/policy/redaction logic directly against
synthetic OCR tokens and a fake OCR engine, so they never touch the Tesseract
binary. `-m e2e` selects the separate real-OCR suite under `tests/e2e/`,
which drives the full `Image -> Preprocess -> Real OCR -> Detection -> Risk
-> Policy -> Redaction -> Verification -> Output` pipeline against generated
test images. Plain `pytest` (no `-m`) excludes `e2e` automatically via
`pyproject.toml`'s `addopts`, so CI/local unit runs stay fast and don't need
Tesseract installed.

E2E tests never silently pass without a real OCR environment: if Tesseract
or the `chi_tra` language data is missing, every E2E test **SKIPS** (not
passes) with a message naming exactly what's missing.

### Generating E2E test fixtures

```bash
python scripts/generate_test_images.py
```

Regenerates `tests/fixtures/*.png` + `manifest.json`. All fixture text is
synthetic (fabricated formats, plus the standard Luhn-valid *test* credit
card number `4111 1111 1111 1111` that every payment processor's own docs
use) and every image carries a visible "TEST DATA (SYNTHETIC)" banner. Rerun
this if you change the fixture content in `scripts/generate_test_images.py`.
