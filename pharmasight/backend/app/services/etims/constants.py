"""KRA eTIMS OSCU URL paths.

Sandbox: Postman collection *eTIMS-OSCU-Integrator-Automated-Testing-SBX* uses
``https://sbx.kra.go.ke/etims-oscu/api/v1`` for OSCU calls and
``https://sbx.kra.go.ke/v1/token/generate`` for OAuth (see ``ETIMS_SANDBOX_OAUTH_BASE``).

Production hosts may still use legacy ``/oauth2/v1/generate`` on the same base as OSCU;
``get_access_token(..., environment=...)`` picks the token path accordingly.
"""

# OAuth: Apigee sandbox token vs typical legacy gateway path
OAUTH_TOKEN_PATH_APIGEE = "/v1/token/generate"
OAUTH_TOKEN_PATH_LEGACY = "/oauth2/v1/generate"

# OSCU endpoints relative to ETIMS_*_API_BASE (sandbox default ends with /etims-oscu/api/v1)
SELECT_INIT_OSDC_PATH = "/initialize"
SEND_SALES_TRANSACTION_PATH = "/sendSalesTransaction"

# Back-compat name used by older docs / forks
SEND_SALES_TRNS_PATH = SEND_SALES_TRANSACTION_PATH
OAUTH_TOKEN_PATH = OAUTH_TOKEN_PATH_LEGACY
