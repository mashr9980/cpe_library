# cpe_parser/values/status.py
import enum

class Status(enum.Enum):
    VALID = ("valid", True, "The CPE value is valid")
    UNQUOTED_QUESTION_MARK = ("unquoted_question_mark", False, "CPE Strings may not contain unquoted question marks except at the beginning or end of the string")
    UNQUOTED_ASTERISK = ("unquoted_asterisk", False, "CPE strings may only contain unquoted asterisk at the beginning or end of the string")
    ASTERISK_SEQUENCE = ("asterisk_sequence", False, "CPE strings may not contain multiple asterisk characters in sequence")
    NON_PRINTABLE = ("non_printable", False, "CPE strings may only contain printable characters in the UTF-8 character set between x00 and x7F")
    WHITESPACE = ("whitespace", False, "CPE strings may not contain whitespace; consider using an underscore instead")
    SINGLE_QUOTED_HYPHEN = ("single_quoted_hyphen", False, "CPE components cannot be a single quoted hyphen")
    EMPTY = ("empty", False, "CPE components may not be empty or null")
    TOO_MANY_ELEMENTS = ("too_many_elements", False, "The CPE value has too many components")
    TOO_FEW_ELEMENTS = ("too_few_elements", False, "The CPE value has too few components")
    INVALID_PART = ("invalid_part", False, "The CPE value has an invalid part defined")
    INVALID = ("invalid", False, "The CPE value is invalid")
    
    def __init__(self, name: str, valid: bool, message: str):
        self.status_name = name
        self.valid = valid
        self.message = message
    
    def is_valid(self) -> bool:
        return self.valid
    
    def get_message(self) -> str:
        return self.message