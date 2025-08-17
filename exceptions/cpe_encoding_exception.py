# cpe_parser/exceptions/cpe_encoding_exception.py
from typing import Optional

class CpeEncodingException(Exception):
    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.cause = cause