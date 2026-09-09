# Phase 6 Baseline (reconstructed — raw file lost)

**Incident:** the original `ocr_benchmark_20260909.json`/`.csv` (Phase 6, pre-hardening)
was accidentally overwritten during the Phase 6.1 hardened run. `write_report()`
stamped filenames by UTC date only; the hardened run executed at local
2026-09-10 ~02:xx was still 2026-09-09 in UTC, producing the identical
filename as the real baseline and silently overwriting it. `benchmarks/`
was untracked in git at the time, so there was no commit to recover from.

**Fix applied:** `write_report()` now stamps with full `HHMMSS` resolution
and refuses (`FileExistsError`) to overwrite an existing result file — see
`tests/ocr_benchmark/test_report_output.py`.

**What follows is NOT raw per-row data** — only the aggregate summary
numbers, reconstructed from the Phase 6 final report text (recorded in the
conversation transcript, not re-derived or guessed):

| Metric | Phase 6 Baseline |
|---|---|
| Dataset | 51 images, 52 ground-truth sensitive values |
| OCR | Tesseract 5.4.0.20240606, chi_tra/eng/osd |
| Mean Sensitive Detection Recall | 0.702 |
| Total False Negatives | 14 |
| Verification False PASS | 5 |
| Mean Bounding Box IoU | 0.868 |
| Mean CER | 0.438 |
| Mean processing time | 0.895 sec/image |
| Known confirmed FN causes | Address_clean (punctuation), rotated condition (~7 types), Passport/BankAccount under low_res/blurred/rotated/font_large |

See `benchmarks/results/ocr_benchmark_20260910_hardened.{json,csv}` for the
Phase 6.1 (post-fix) run's full per-row data, and the Phase 6.1 Final Report
for the complete before/after comparison.
