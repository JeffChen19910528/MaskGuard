"""Phase 10.4: Enterprise Audit & Security Event Architecture.

Answers WHO/WHAT/WHEN/RESULT for security-relevant operations — never a
copy of request/response bodies, images, OCR text, or tokens (§5/§79/§80).
Isolated from MaskGuard Core exactly like `maskguard/api/auth/` and
`maskguard/api/authorization/`: nothing here is imported by, or imports,
`maskguard/detection|risk|policy|redaction|verification|ocr`.

Audit is OBSERVABILITY, not a security decision path (§2/§76/§77):
- it consumes Phase 10.2's authenticated identity and Phase 10.3's
  authorization decision, never re-implementing either;
- a failure to WRITE an audit record never blocks, weakens, or alters
  any authentication/authorization/PolicyEngine/redaction/verification
  outcome (see `service.py`'s `emit()` — always best-effort, always
  fail-safe, documented in detail there).
"""
