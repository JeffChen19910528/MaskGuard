"""Phase 10.3 §11/§13/§51/§52/§79: identity -> role assignment.

Role BUNDLES (`permissions.py`) are code. WHO holds which role is
deployment-specific, security-sensitive, server-side-only configuration —
never client-submittable (§13/§14), never keyed by email (§47/§83:
`issuer + subject` is the stable identity, matching
`AuthenticatedIdentity.identity_key`, Phase 10.2).

§12: this file does NOT read OIDC group/claim data — Phase 10.2 doesn't
define a provider-specific group claim, and inventing one here would
couple this module to a specific IdP's claim shape (explicitly
prohibited, §12). The mapping below is a placeholder server-side table a
future phase can extend to ALSO consult validated group claims (still
never trusting them until Phase 10.2's own signature/issuer/audience
validation has already run) without changing `permissions_for_roles()`,
`require_permission()`, or any route.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import yaml

from .permissions import KNOWN_ROLES


class AuthorizationConfigError(RuntimeError):
    """§51/§79: malformed role-mapping configuration is ALWAYS a hard
    startup failure — never a silent fallback to "everyone is
    Administrator," "everyone is Operator," or "authorization disabled."
    This applies regardless of MASKGUARD_ENV — unlike some Phase
    9/10.2 checks that only fail closed in production, a malformed
    security-sensitive mapping file is never acceptable to run with,
    development included."""


@dataclass(frozen=True)
class RoleMapping:
    #: `"issuer|subject"` (matches `AuthenticatedIdentity.identity_key`) -> roles.
    assignments: dict[str, frozenset[str]]

    def roles_for(self, identity_key: str) -> frozenset[str]:
        # §49: an identity with no explicit entry gets NO roles — default
        # deny, not an implicit fallback role.
        return self.assignments.get(identity_key, frozenset())


_EMPTY_MAPPING = RoleMapping(assignments={})


def _load_yaml_mapping(path: str) -> RoleMapping:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except OSError as exc:
        raise AuthorizationConfigError(f"AUTHZ_ROLE_MAPPING_FILE={path!r} could not be read: {exc}") from exc
    except yaml.YAMLError as exc:
        raise AuthorizationConfigError(f"AUTHZ_ROLE_MAPPING_FILE={path!r} is not valid YAML: {exc}") from exc

    if raw is None:
        return _EMPTY_MAPPING
    if not isinstance(raw, dict) or "mappings" not in raw or not isinstance(raw["mappings"], list):
        raise AuthorizationConfigError(
            f"AUTHZ_ROLE_MAPPING_FILE={path!r} must be a mapping with a top-level 'mappings' list."
        )

    assignments: dict[str, frozenset[str]] = {}
    seen_keys: set[str] = set()
    for i, entry in enumerate(raw["mappings"]):
        if not isinstance(entry, dict):
            raise AuthorizationConfigError(f"mappings[{i}] must be a mapping (issuer/subject/roles).")
        issuer = entry.get("issuer")
        subject = entry.get("subject")
        roles = entry.get("roles")
        if not issuer or not isinstance(issuer, str):
            raise AuthorizationConfigError(f"mappings[{i}].issuer must be a non-empty string.")
        if not subject or not isinstance(subject, str):
            raise AuthorizationConfigError(f"mappings[{i}].subject must be a non-empty string.")
        if not isinstance(roles, list) or not roles:
            raise AuthorizationConfigError(f"mappings[{i}].roles must be a non-empty list.")

        unknown = [r for r in roles if r not in KNOWN_ROLES]
        if unknown:
            # §51: "unknown permissions should be rejected" — applied
            # identically to unknown ROLE names, the equivalent malformed-
            # configuration case at this layer.
            raise AuthorizationConfigError(
                f"mappings[{i}] references unknown role(s) {unknown} — known roles: {sorted(KNOWN_ROLES)}."
            )

        key = f"{issuer}|{subject}"
        if key in seen_keys:
            # §51: "duplicate roles should be rejected" — interpreted at
            # the mapping-entry level: two separate entries for the same
            # identity is an ambiguous, likely-erroneous configuration
            # (which one wins?) rather than silently merging or picking
            # the last one.
            raise AuthorizationConfigError(f"duplicate role-mapping entry for identity {key!r}.")
        seen_keys.add(key)
        assignments[key] = frozenset(roles)

    return RoleMapping(assignments=assignments)


@lru_cache
def get_role_mapping() -> RoleMapping:
    """§11: static server-side configuration (Option A) — the file path is
    itself trusted server configuration (`AUTHZ_ROLE_MAPPING_FILE`), never
    derived from a request. §49: no configured file at all means an EMPTY
    mapping (every authenticated identity has zero roles, zero
    permissions) — default deny, not "nobody is authorized so skip
    authorization," which would be fail-OPEN."""
    path = os.environ.get("AUTHZ_ROLE_MAPPING_FILE")
    if not path:
        return _EMPTY_MAPPING
    return _load_yaml_mapping(path)
