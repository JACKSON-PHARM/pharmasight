"""
eTIMS authentication and session lifecycle.

Responsibilities (when implemented):
- Obtain and refresh OAuth/session tokens per KRA sandbox/production rules.
- Store short-lived credentials outside request path (DB-encrypted or secrets manager).
- Associate credentials with company + branch context (bhfId / device), never mixing tenants.
"""


def placeholder() -> None:
    """Reserved for token acquisition; implement with official auth endpoints."""
    raise NotImplementedError("eTIMS auth not wired yet")
