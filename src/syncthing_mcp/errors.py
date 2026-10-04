"""Public failures never contain upstream bodies, URLs or credentials."""

from typing import Any


class PublicError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        outcome: str = "not_attempted",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.outcome = outcome

    def payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "outcome": self.outcome,
        }
