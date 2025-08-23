from .cpe_validation_exception import CpeValidationException
from .cpe_encoding_exception import CpeEncodingException

class CpeParsingException(Exception):
    def __init__(self, message: str, cause=None):
        super().__init__(message)
        self.cause = cause

__all__ = ['CpeParsingException', 'CpeValidationException', 'CpeEncodingException']