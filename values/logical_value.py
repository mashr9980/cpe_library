# cpe_parser/values/logical_value.py
import enum

class LogicalValue(enum.Enum):
    ANY = "*"
    NA = "-"
    
    def get_abbreviation(self) -> str:
        return self.value