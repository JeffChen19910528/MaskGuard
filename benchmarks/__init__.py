"""Standalone OCR-engine benchmark framework for MaskGuard.

Everything under `benchmarks/` is measurement tooling — it imports and runs
the real, unmodified `maskguard` package (Detection/Risk/Policy/Redaction/
Verification) to compare OCR engines objectively. It is not part of the
production pipeline and production code never imports from here.
"""
