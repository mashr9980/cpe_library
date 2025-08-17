# cpe_parser/internal/util/cpe23_part_iterator.py

from exceptions import CpeParsingException


class Cpe23PartIterator:
    def __init__(self, cpe: str):
        if cpe is None or not cpe.startswith("cpe:2.3:"):
            raise CpeParsingException(f"Invalid 2.3 CPE value: {cpe}")
        self.cpe = cpe
        self.pos = 8
    
    def has_next(self) -> bool:
        return self.pos < len(self.cpe)
    
    def __next__(self) -> str:
        if self.pos >= len(self.cpe):
            raise StopIteration("No remaining parts")
        
        end = self.pos
        while end < len(self.cpe):
            if self.cpe[end] == ':':
                break
            if self.cpe[end] == '\\' and (end + 1) < len(self.cpe):
                end += 1
            end += 1
        
        part = self.cpe[self.pos:end]
        self.pos = end + 1
        return part
    
    def __iter__(self):
        return self