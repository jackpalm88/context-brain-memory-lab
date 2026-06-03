from enum import Enum


class FailureCode(str, Enum):
    NOT_CONFIGURED           = "not_configured"
    MISSING_API_KEY          = "missing_api_key"
    PROVIDER_IMPORT_MISSING  = "provider_import_missing"
    PROVIDER_HTTP_ERROR      = "provider_http_error"
    RATE_LIMITED             = "rate_limited"
    TIMEOUT                  = "timeout"
    INVALID_JSON             = "invalid_json"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    CIRCUIT_OPEN             = "circuit_open"
    DIMENSION_MISMATCH       = "dimension_mismatch"
    PARTIAL_BATCH_FAILURE    = "partial_batch_failure"
    UNKNOWN_ERROR            = "unknown_error"
