"""Phase 10.2: Enterprise Authentication Foundation (OIDC Relying Party).

Establishes WHO the caller is. Deliberately does NOT establish WHAT the
caller may do — that is Phase 10.3 (authorization/RBAC), not implemented
here (see docs/enterprise-authorization-architecture.md).

This package is isolated from MaskGuard Core: nothing under
`maskguard/detection/`, `risk/`, `policy/`, `redaction/`, `verification/`,
or `ocr/` imports from here, and nothing here imports from those either.
Authentication is an API/application-boundary concern only (ADR-001/002,
docs/enterprise-architecture.md §2).
"""
