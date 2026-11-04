"""Typed exceptions mapped to a consistent API error envelope."""


class TwinError(Exception):
    code = "TWIN_ERROR"
    http_status = 500


class InputValidationError(TwinError):
    code = "INPUT_VALIDATION"
    http_status = 422


class SolverError(TwinError):
    code = "SOLVER_FAILURE"
    http_status = 500


class BalanceError(TwinError):
    """Raised when conservation audits fail; results are rejected, never normalised."""
    code = "BALANCE_REJECTED"
    http_status = 500


class SafetyGateError(TwinError):
    code = "SAFETY_GATE"
    http_status = 409


class AuthError(TwinError):
    code = "AUTH"
    http_status = 401


class PermissionDenied(TwinError):
    code = "FORBIDDEN"
    http_status = 403


class NotFound(TwinError):
    code = "NOT_FOUND"
    http_status = 404
