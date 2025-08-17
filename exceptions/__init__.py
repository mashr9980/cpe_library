# cpe_parser/exceptions/__init__.py
from .cpe_validation_exception import CpeValidationException
from .cpe_encoding_exception import CpeEncodingException

__all__ = ['CpeParsingException', 'CpeValidationException', 'CpeEncodingException']

# cpe_parser/exceptions/cpe_parsing_exception.py
from typing import Optional

class CpeParsingException(Exception):
    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.cause = cause