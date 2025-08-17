# cpe_parser/util/validate.py
import re
import logging
from typing import Optional
from exceptions import CpeParsingException
from values.status import Status
from values.part import Part
from exceptions.cpe_encoding_exception import CpeEncodingException
from internal.util.cpe23_part_iterator import Cpe23PartIterator
from .convert import Convert

class Validate:
    CPE_URI = re.compile(r"^[c][pP][eE]:/[AHOaho]?(:[A-Za-z0-9._~%-]*){0,6}$")
    
    @staticmethod
    def component(value: Optional[str]) -> Status:
        if value is not None and value != "":
            if "\\-" == value:
                return Status.SINGLE_QUOTED_HYPHEN
            for x in range(len(value)):
                c = value[x]
                if (c == '?' and x > 0 and x < len(value) - 1 and 
                    not ((value[x - 1] == '?' or value[x - 1] == '*' or value[x - 1] == '\\') or
                         (x < len(value) - 1 and (value[x + 1] == '?' or value[x + 1] == '*')))):
                    return Status.UNQUOTED_QUESTION_MARK
                elif c.isspace():
                    return Status.WHITESPACE
                elif ord(c) < 32 or ord(c) > 127:
                    return Status.NON_PRINTABLE
                elif c == '*' and x != 0 and value[x - 1] == '*':
                    return Status.ASTERISK_SEQUENCE
                elif (c == '*' and 
                      not ((x == 0 or x == len(value) - 1) or
                           (x > 0 and '\\' == value[x - 1]))):
                    return Status.UNQUOTED_ASTERISK
            return Status.VALID
        return Status.EMPTY
    
    @staticmethod
    def formatted_string(value: str) -> Status:
        try:
            instance = Cpe23PartIterator(value)
        except CpeParsingException:
            logging.warning(f"The CPE ({value}) is invalid as it is not in the formatted string format")
            return Status.INVALID
        
        try:
            Part.get_enum(instance.__next__())
        except CpeParsingException:
            logging.warning(f"The CPE ({value}) is invalid as it has an invalid part attribute")
            return Status.INVALID_PART
        
        attributes = ["vendor", "product", "version", "update", "edition", "language", 
                     "swEdition", "targetSw", "targetHw", "other"]
        
        for attr in attributes:
            try:
                status = Validate.component(instance.__next__())
                if not status.is_valid():
                    logging.warning(f"The CPE ({value}) has an invalid {attr} - {status.get_message()}")
                    return status
            except StopIteration:
                logging.warning(Status.TOO_FEW_ELEMENTS.get_message())
                return Status.TOO_FEW_ELEMENTS
        
        if instance.has_next():
            logging.warning(Status.TOO_MANY_ELEMENTS.get_message())
            return Status.TOO_MANY_ELEMENTS
        
        return Status.VALID
    
    @staticmethod
    def cpe_uri(value: str) -> Status:
        try:
            parts = value.split(":")
            if len(parts) > 8 or len(parts) == 1 or parts[0].lower() != "cpe":
                logging.warning(f"The CPE ({value}) is invalid as it is not in the CPE 2.2 URI format")
                return Status.INVALID
            
            if len(parts) >= 2 and len(parts[1]) == 2:
                found = False
                a = parts[1][1:]
                for p in Part:
                    if p.get_abbreviation() == a:
                        found = True
                        break
                if not found:
                    logging.warning(f"The CPE ({value}) is invalid as it has an invalid part attribute")
                    return Status.INVALID_PART
            else:
                logging.warning(f"The CPE ({value}) is invalid as it has an invalid part attribute")
                return Status.INVALID_PART
            
            component_names = ["vendor", "product", "version", "update", "edition", "language"]
            for i in range(2, min(len(parts), 8)):
                if i == 6:  # edition component
                    if parts[i].startswith("~"):
                        if Validate._count_character(parts[i], '~') != 5:
                            logging.warning(f"The CPE ({value}) has an invalid packed edition - too many entries")
                            return Status.INVALID
                        unpacked = parts[i].split("~")
                        for j in range(1, min(len(unpacked), 6)):
                            if unpacked[j] == "*":
                                logging.warning(f"The CPE ({value}) has an invalid packed component - asterisk")
                                return Status.INVALID
                            s = Validate.component(Convert.cpe_uri_to_well_formed(unpacked[j]))
                            if not s.is_valid():
                                logging.warning(f"The CPE ({value}) has an invalid packed component - {s.get_message()}")
                                return s
                    else:
                        if parts[i] == "*":
                            logging.warning(f"The CPE ({value}) has an invalid edition - asterisk")
                            return Status.INVALID
                        s = Validate.component(Convert.cpe_uri_to_well_formed(parts[i]))
                        if not s.is_valid():
                            logging.warning(f"The CPE ({value}) has an invalid edition - {s.get_message()}")
                            return s
                else:
                    if parts[i] == "*":
                        logging.warning(f"The CPE ({value}) has an invalid {component_names[i-2]} - asterisk")
                        return Status.INVALID
                    s = Validate.component(Convert.cpe_uri_to_well_formed(parts[i]))
                    if not s.is_valid():
                        logging.warning(f"The CPE ({value}) has an invalid {component_names[i-2]} - {s.get_message()}")
                        return s
        except CpeEncodingException:
            logging.warning(f"The CPE ({value}) has an unencoded special characters")
            return Status.INVALID
        
        return Status.VALID
    
    @staticmethod
    def _count_character(value: str, c: str) -> int:
        return value.count(c)
    
    @staticmethod
    def cpe(value: str) -> Status:
        if value.startswith("cpe:2.3:"):
            return Validate.formatted_string(value)
        return Validate.cpe_uri(value)