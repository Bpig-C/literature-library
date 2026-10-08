"""Machine-readable error categories for the research workflow (contract v5).

Every operational failure maps to exactly one contract error category so
external agents can react programmatically instead of parsing prose.
"""
from __future__ import annotations

from .research_schema import CONTRACT


ERROR_CATEGORIES = tuple(CONTRACT["error_categories"])


class ResearchOperationError(Exception):
    """An operational failure with a contract error category."""

    def __init__(self, category: str, message: str, *, retryable: bool = False):
        if category not in ERROR_CATEGORIES:
            raise ValueError(f"unknown error category: {category}")
        super().__init__(message)
        self.category = category
        self.message = message
        self.retryable = bool(retryable) or category == "retryable_failure"

    def to_dict(self) -> dict:
        return {"error": self.category, "message": self.message, "retryable": self.retryable}


def invalid_payload(message: str) -> ResearchOperationError:
    return ResearchOperationError("invalid_payload", message)


def incompatible_definition(message: str) -> ResearchOperationError:
    return ResearchOperationError("incompatible_definition", message)


def identity_conflict(message: str) -> ResearchOperationError:
    return ResearchOperationError("identity_conflict", message)


def revision_conflict(message: str) -> ResearchOperationError:
    return ResearchOperationError("revision_conflict", message)


def lease_conflict(message: str) -> ResearchOperationError:
    return ResearchOperationError("lease_conflict", message)


def dependency_unavailable(message: str) -> ResearchOperationError:
    return ResearchOperationError("dependency_unavailable", message)


def read_only_error(message: str) -> ResearchOperationError:
    return ResearchOperationError("read_only", message)


def not_found_error(message: str) -> ResearchOperationError:
    return ResearchOperationError("not_found", message)


def retryable_failure(message: str) -> ResearchOperationError:
    return ResearchOperationError("retryable_failure", message, retryable=True)


def classify_exception(exc: Exception) -> ResearchOperationError:
    """Translate legacy exception types into contract error categories."""
    if isinstance(exc, ResearchOperationError):
        return exc
    from .research_service import ResearchConflictError
    text = str(exc)
    lowered = text.lower()
    if isinstance(exc, KeyError):
        return not_found_error(text)
    if isinstance(exc, PermissionError):
        return read_only_error(text)
    if isinstance(exc, FileNotFoundError):
        return dependency_unavailable(text)
    if isinstance(exc, ResearchConflictError):
        if "lease" in lowered or "fencing" in lowered:
            return lease_conflict(text)
        if "revision" in lowered or "draft" in lowered:
            return revision_conflict(text)
        return identity_conflict(text)
    if isinstance(exc, ValueError):
        if "supersedes" in lowered or "head" in lowered or "revision" in lowered:
            return revision_conflict(text)
        if ("lease" in lowered or "fencing" in lowered or "worker_owner" in lowered
                or "worker mutation" in lowered):
            return lease_conflict(text)
        if ("definition" in lowered or "ontology_keys" in lowered
                or "not defined by" in lowered or "payload must" in lowered
                or "requires author definitions" in lowered):
            return incompatible_definition(text)
        if "already binds" in lowered or "citation key already" in lowered \
                or "already exists" in lowered or "ambiguous" in lowered:
            return identity_conflict(text)
        if "schema is not initialized" in lowered:
            return dependency_unavailable(text)
        return invalid_payload(text)
    return invalid_payload(text)
