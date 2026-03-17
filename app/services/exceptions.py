from typing import Any

class LLMServiceError(Exception):
    """Exception raised for errors in LLM API communication."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

class IntentParseException(Exception):
    """Exception raised when intent parsing validation or decoding fails."""
    def __init__(self, detail: Any):
        super().__init__(str(detail))
        self.detail = detail
