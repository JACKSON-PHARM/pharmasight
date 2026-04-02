"""
Item master synchronization with eTIMS (e.g. saveItem).

Responsibilities (when implemented):
- Map PharmaSight Item rows (+ units) to KRA item payload (itemClsCd, pkgUnitCd, qtyUnitCd, taxTyCd).
- Upsert remote item identity and store KRA item keys back on Item (after schema migration).
- Queue retries; never block synchronous sales invoice creation.
"""


def placeholder() -> None:
    raise NotImplementedError("eTIMS items sync not wired yet")
