# cpe_parser/values/part.py
import enum

from exceptions import CpeParsingException

class Part(enum.Enum):
    APPLICATION = "a"
    OPERATING_SYSTEM = "o"
    HARDWARE_DEVICE = "h"
    ANY = "*"
    NA = "-"
    
    def get_abbreviation(self) -> str:
        return self.value
    
    @classmethod
    def get_enum(cls, part: str) -> 'Part':
        for p in cls:
            if p.get_abbreviation() == part:
                return p
        raise CpeParsingException(f"Invalid Part Type: {part}")