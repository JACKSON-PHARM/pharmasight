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
# OSCU retail sale (full Joi contract); preferred over legacy sendSalesTransaction for taxTyCd validation.
SAVE_TRNS_SALES_OSDC_PATH = "/saveTrnsSalesOsdc"
# Gava / kra_certify: primes OSCU sales context before ``saveTrnsSalesOsdc`` (soft-fail if unavailable).
SELECT_INVOICE_TYPE_PATH = "/selectInvoiceType"
SAVE_ITEM_PATH = "/saveItem"
SELECT_ITEM_CLASS_LIST_PATH = "/selectItemClsList"
SELECT_ITEM_LIST_PATH = "/selectItemList"
INSERT_STOCK_IO_PATH = "/insertStockIO"
# Root ``sarTyCd`` on ``insertStockIO`` (stock I/O document type). Distinct from per-line ``ioTyCd``.
# Labels align with gavaetims portal comment (``gavaetims.py`` composition prelude): 01 Import, 02 Purchase,
# 04 Stock movement, 06 Adjustment. Avoid ``11`` unless KRA spec explicitly requires it (direction pitfalls).
INSERT_STOCK_IO_SAR_TY_IMPORT = "01"
INSERT_STOCK_IO_SAR_TY_PURCHASE = "02"
INSERT_STOCK_IO_SAR_TY_STOCK_MOVEMENT = "04"
INSERT_STOCK_IO_SAR_TY_ADJUSTMENT = "06"
SAVE_STOCK_MASTER_PATH = "/saveStockMaster"
SELECT_STOCK_MASTER_PATH = "/selectStockMaster"
SELECT_STOCK_MOVE_LIST_PATH = "/selectStockMoveList"

# Customs / imported items (KRA portal “Basic Data Management” — TIS receives customs declarations).
# Used by certification scripts (`gavaetims.py`, `kra_min.py`); production app services do not yet
# orchestrate this lifecycle before stock adjustment for import-sourced SKU lines.
SELECT_IMPORT_ITEM_LIST_PATH = "/selectImportItemList"
IMPORTED_ITEM_INFO_PATH = "/importedItemInfo"
IMPORTED_ITEM_CONVERTED_INFO_PATH = "/importedItemConvertedInfo"
UPDATE_IMPORT_ITEM_PATH = "/updateImportItem"

# Back-compat name used by older docs / forks (legacy endpoint).
SEND_SALES_TRNS_PATH = SEND_SALES_TRANSACTION_PATH
OAUTH_TOKEN_PATH = OAUTH_TOKEN_PATH_LEGACY
