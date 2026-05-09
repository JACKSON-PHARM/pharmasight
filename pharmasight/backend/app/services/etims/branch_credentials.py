"""Read branch-level eTIMS secrets (OAuth + CMC) with app-level env fallback."""
from __future__ import annotations

import logging
from typing import Tuple

from app.config import settings
from app.models.company import BranchEtimsCredentials
from app.services.etims.credential_crypto import decrypt_secret

logger = logging.getLogger(__name__)


def effective_etims_environment(creds: BranchEtimsCredentials) -> str:
    """
    KRA sandbox vs production for API base and OAuth token routing.

    If ETIMS_ENVIRONMENT is set to sandbox|production (e.g. on Render for go-live),
    it overrides the branch row so one deployment tracks one KRA app registration.
    """
    g = (getattr(settings, "ETIMS_ENVIRONMENT", None) or "").strip().lower()
    if g in ("sandbox", "production"):
        return g
    e = (creds.environment or "sandbox").strip().lower()
    return e if e in ("sandbox", "production") else "sandbox"


def get_oauth_username_password(creds: BranchEtimsCredentials) -> Tuple[str, str]:
    """
    OAuth client id (username) and secret (password) for HTTP Basic token requests.

    Precedence (pairs only — never mix branch username with env secret):
    1. Branch kra_oauth_username + kra_oauth_password (optional per-branch override)
    2. Branch consumer_key + consumer_secret_encrypted (KRA developer portal app; secret decrypted at use-time)
    3. ETIMS_APP_CONSUMER_KEY + ETIMS_APP_CONSUMER_SECRET (deployment-wide fallback)
    4. ETIMS_OAUTH_USERNAME + ETIMS_OAUTH_PASSWORD (legacy env names)

    Values are never logged or returned to API clients.
    """
    bu = (creds.kra_oauth_username or "").strip()
    bp = decrypt_secret(getattr(creds, "kra_oauth_password", None)).strip()
    if bu and bp:
        logger.debug("eTIMS OAuth credential source: branch_etims_credentials (kra_oauth_username/password)")
        return bu, bp

    if bu or bp:
        logger.warning(
            "eTIMS OAuth: branch has only one of kra_oauth_username/kra_oauth_password; "
            "ignoring incomplete pair. Use consumer_key/consumer_secret on the branch or ETIMS_APP_CONSUMER_*."
        )

    ck = (getattr(creds, "consumer_key", None) or "").strip()
    cs = decrypt_secret(getattr(creds, "consumer_secret_encrypted", None)).strip()
    if ck and cs:
        logger.debug("eTIMS OAuth credential source: branch_etims_credentials (consumer_key/consumer_secret)")
        return ck, cs

    if ck or cs:
        logger.warning(
            "eTIMS OAuth: branch has only one of consumer_key/consumer_secret_encrypted; "
            "ignoring incomplete pair."
        )

    ku = (settings.ETIMS_APP_CONSUMER_KEY or "").strip()
    kp = (settings.ETIMS_APP_CONSUMER_SECRET or "").strip()
    if ku and kp:
        logger.debug("eTIMS OAuth credential source: ETIMS_APP_CONSUMER_KEY/ETIMS_APP_CONSUMER_SECRET (env)")
        return ku, kp

    if ku or kp:
        logger.warning(
            "eTIMS OAuth: ETIMS_APP_CONSUMER_KEY or ETIMS_APP_CONSUMER_SECRET is set but not both. "
            "Set both environment variables (local .env or Render secrets)."
        )

    lu = (settings.ETIMS_OAUTH_USERNAME or "").strip()
    lp = (settings.ETIMS_OAUTH_PASSWORD or "").strip()
    if lu and lp:
        logger.debug("eTIMS OAuth credential source: ETIMS_OAUTH_USERNAME/ETIMS_OAUTH_PASSWORD (legacy env)")
        return lu, lp

    if lu or lp:
        logger.warning(
            "eTIMS OAuth: ETIMS_OAUTH_USERNAME or ETIMS_OAUTH_PASSWORD is set but not both; ignoring incomplete pair."
        )

    logger.warning(
        "eTIMS OAuth: no client id/secret configured. "
        "Set ETIMS_APP_CONSUMER_KEY and ETIMS_APP_CONSUMER_SECRET (KRA developer portal Consumer Key/Secret), "
        "or set both branch OAuth fields, or legacy ETIMS_OAUTH_USERNAME and ETIMS_OAUTH_PASSWORD."
    )
    return "", ""


def get_cmc_key_plain(creds: BranchEtimsCredentials) -> str:
    return decrypt_secret(getattr(creds, "cmc_key_encrypted", None)).strip()
