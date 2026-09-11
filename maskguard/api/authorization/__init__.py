"""Phase 10.3: Enterprise Authorization (RBAC).

Answers "what may this authenticated caller do?" — never "what must
MaskGuard do with sensitive data?" (that remains RiskEngine/PolicyEngine/
RedactionEngine/VerificationEngine, untouched by this module — see
docs/enterprise-architecture.md §2). Isolated from MaskGuard Core exactly
like `maskguard/api/auth/` (Phase 10.2): nothing here is imported by, or
imports, `maskguard/detection|risk|policy|redaction|verification|ocr`.
"""
