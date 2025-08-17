# cpe_parser/util/convert.py
import re
import logging
from typing import Optional
from values.logical_value import LogicalValue
from values.part import Part
from exceptions.cpe_encoding_exception import CpeEncodingException

class Convert:
    HEX_CHARS = "0123456789abcdef"
    
    @staticmethod
    def to_well_formed(value: Optional[str]) -> str:
        if value is None:
            return LogicalValue.ANY.get_abbreviation()
        if (LogicalValue.ANY.get_abbreviation() == value or 
            LogicalValue.NA.get_abbreviation() == value):
            return value
        
        buffer = list(value)
        x = 0
        while x < len(buffer):
            c = buffer[x]
            if not ((c >= 'a' and c <= 'z') or (c >= 'A' and c <= 'Z') or (c >= '0' and c <= '9')):
                buffer.insert(x, '\\')
                x += 1
            x += 1
        return ''.join(buffer)
    
    @staticmethod
    def from_well_formed(value: Optional[str]) -> str:
        if value is None:
            return LogicalValue.ANY.get_abbreviation()
        
        buffer = list(value)
        p = ' '
        x = 0
        while x < len(buffer) - 1:
            c = buffer[x]
            if c == '\\' and p != '\\':
                buffer.pop(x)
                x -= 1
            p = c
            x += 1
        return ''.join(buffer)
    
    @staticmethod
    def well_formed_to_cpe_uri_part(value: Optional[Part]) -> str:
        if value is None:
            return Part.ANY.get_abbreviation()
        return value.get_abbreviation()
    
    @staticmethod
    def well_formed_to_cpe_uri(well_formed: Optional[str]) -> str:
        if well_formed is None or well_formed == "" or LogicalValue.ANY.get_abbreviation() == well_formed:
            return ""
        if LogicalValue.NA.get_abbreviation() == well_formed:
            return well_formed
        
        bytes_data = well_formed.encode('utf-8')
        sb = []
        x = 0
        while x < len(bytes_data):
            c = bytes_data[x]
            if ((c >= ord('0') and c <= ord('9')) or 
                (c >= ord('a') and c <= ord('z')) or 
                (c >= ord('A') and c <= ord('Z'))):
                sb.append(chr(c))
            elif c == ord('\\'):
                x += 1
                if x >= len(bytes_data):
                    raise CpeEncodingException("Invalid Well Formed string - ends with an unquoted backslash")
                c = bytes_data[x]
                if c == ord('_') or c == ord('.') or c == ord('-'):
                    sb.append(chr(c))
                else:
                    sb.append('%')
                    sb.append(Convert.HEX_CHARS[(c & 0xF0) >> 4])
                    sb.append(Convert.HEX_CHARS[c & 0x0F])
            elif c == ord('*'):
                sb.append("%02")
            elif c == ord('?'):
                sb.append("%01")
            else:
                raise CpeEncodingException(f"Invalid Well Formed string - unexpected characters: {well_formed}")
            x += 1
        return ''.join(sb)
    
    @staticmethod
    def cpe_uri_to_well_formed(value: Optional[str], lenient: bool = False) -> str:
        if value is None or value == "" or LogicalValue.ANY.get_abbreviation() == value:
            return LogicalValue.ANY.get_abbreviation()
        elif LogicalValue.NA.get_abbreviation() == value:
            return LogicalValue.NA.get_abbreviation()
        
        bytes_data = value.lower().encode('utf-8')
        sb = []
        x = 0
        while x < len(bytes_data):
            c = chr(bytes_data[x])
            if ((c >= '0' and c <= '9') or (c >= 'a' and c <= 'z')):
                sb.append(c)
            elif c == '_' or c == '.' or c == '-':
                sb.append('\\')
                sb.append(c)
            elif c == '%':
                if (2 + x) >= len(bytes_data):
                    raise CpeEncodingException("Invalid CPE URI component - ends with a single percent")
                x += 1
                decoded = int(chr(bytes_data[x]) + chr(bytes_data[x + 1]), 16)
                x += 1
                if decoded == 1:
                    sb.append('?')
                elif decoded == 2:
                    sb.append('*')
                else:
                    sb.append('\\')
                    sb.append(chr(decoded))
            else:
                if lenient:
                    logging.debug(f"Invalid CPE URI part, '{value}'; escaping '{c}' as a well formatted string")
                    sb.append('\\')
                    sb.append(c)
                else:
                    raise CpeEncodingException("Invalid CPE URI component - unexpected characters")
            x += 1
        return ''.join(sb)
    
    @staticmethod
    def well_formed_to_fs_part(value: Optional[Part]) -> str:
        if value is None:
            return LogicalValue.ANY.get_abbreviation()
        return value.get_abbreviation()
    
    @staticmethod
    def well_formed_to_fs(value: Optional[str]) -> str:
        if value is None or value == "":
            return LogicalValue.ANY.get_abbreviation()
        if (LogicalValue.ANY.get_abbreviation() == value or 
            LogicalValue.NA.get_abbreviation() == value):
            return value
        
        buffer = list(value)
        p = ' '
        x = 0
        while x < len(buffer) - 1:
            c = buffer[x]
            if (c == '.' or c == '_' or c == '-') and p == '\\':
                buffer.pop(x - 1)
                x -= 1
            p = c
            x += 1
        return ''.join(buffer)
    
    @staticmethod
    def fs_to_well_formed(value: Optional[str], lenient: bool = False) -> str:
        if value is None or value == "":
            return LogicalValue.ANY.get_abbreviation()
        if (LogicalValue.ANY.get_abbreviation() == value or 
            LogicalValue.NA.get_abbreviation() == value):
            return value
        
        start_lenient = -1
        end_lenient = len(value) - 1
        if lenient:
            prev = ' '
            for x in range(len(value)):
                c = value[x]
                if start_lenient < 0 and c != '?' and c != '*':
                    start_lenient = x
                if c == '*' or c == '?':
                    if prev != '*' and prev != '?':
                        end_lenient = x - 1
                elif c == '\\':
                    x += 1
                    end_lenient = len(value) - 1
                else:
                    end_lenient = len(value) - 1
                prev = c
        
        quoted = False
        buffer = list(value)
        x = 0
        while x < len(buffer):
            c = buffer[x]
            if c == '.' or c == '_' or c == '-':
                buffer.insert(x, '\\')
                x += 1
                end_lenient += 1
            elif lenient and x >= start_lenient and x <= end_lenient:
                if not quoted and c == '\\':
                    quoted = True
                    x += 1
                    continue
                if (not quoted and 
                    not ((c >= 'a' and c <= 'z') or (c >= 'A' and c <= 'Z') or (c >= '0' and c <= '9'))):
                    buffer.insert(x, '\\')
                    x += 1
                    end_lenient += 1
                quoted = False
            x += 1
        
        return ''.join(buffer)
    
    @staticmethod
    def well_formed_to_pattern(value: str) -> re.Pattern:
        sb = []
        x = 0
        while x < len(value):
            if value[x] == '*':
                sb.append(".*")
            elif value[x] == '?':
                sb.append(".")
            elif value[x] == '\\' and (x + 1) < len(value):
                sb.append('\\')
                sb.append(value[x])
                sb.append('\\')
                x += 1
                sb.append(value[x])
            elif ((value[x] >= 'a' and value[x] <= 'z') or
                  (value[x] >= 'A' and value[x] <= 'Z') or
                  (value[x] >= '0' and value[x] <= '9')):
                sb.append(value[x])
            else:
                sb.append('\\')
                sb.append(value[x])
            x += 1
        return re.compile(''.join(sb))