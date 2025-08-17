# cpe_parser/cpe_parser.py
from cpe import Cpe
from cpe_builder import CpeBuilder
from exceptions import CpeParsingException
from cpe_builder import CpeBuilder
from exceptions.cpe_encoding_exception import CpeEncodingException
from exceptions.cpe_validation_exception import CpeValidationException
from util.convert import Convert
from internal.util.cpe23_part_iterator import Cpe23PartIterator

class CpeParser:
    @staticmethod
    def parse(cpe_string: str, lenient: bool = False) -> Cpe:
        if cpe_string is None:
            raise CpeParsingException("CPE String is null and cannot be parsed")
        elif cpe_string.startswith("cpe:/"):
            return CpeParser._parse22(cpe_string, lenient)
        elif cpe_string.startswith("cpe:2.3:"):
            return CpeParser._parse23(cpe_string, lenient)
        raise CpeParsingException("The CPE string specified does not conform to the CPE 2.2 or 2.3 specification")
    
    @staticmethod
    def _parse22(cpe_string: str, lenient: bool = False) -> Cpe:
        if cpe_string is None or cpe_string == "":
            raise CpeParsingException("CPE String is null is empty - unable to parse")
        
        cb = CpeBuilder()
        parts = cpe_string.split(":")
        
        if len(parts) <= 1 or len(parts) > 8:
            raise CpeParsingException(f"CPE String is invalid - too many components specified: {cpe_string}")
        
        if len(parts[1]) == 0 or len(parts[1]) > 2:
            raise CpeParsingException(f"CPE String contains a malformed part: {cpe_string}")
        
        try:
            if len(parts[1]) > 1:
                cb.part(parts[1][1:])
            
            if len(parts) > 2:
                cb.wf_vendor(Convert.cpe_uri_to_well_formed(parts[2], lenient))
            if len(parts) > 3:
                cb.wf_product(Convert.cpe_uri_to_well_formed(parts[3], lenient))
            if len(parts) > 4:
                cb.wf_version(Convert.cpe_uri_to_well_formed(parts[4], lenient))
            if len(parts) > 5:
                cb.wf_update(Convert.cpe_uri_to_well_formed(parts[5], lenient))
            if len(parts) > 6:
                CpeParser._unpack_edition(parts[6], cb, lenient)
            if len(parts) > 7:
                cb.wf_language(Convert.cpe_uri_to_well_formed(parts[7], lenient))
            
            return cb.build()
        except (CpeValidationException, CpeEncodingException) as ex:
            raise CpeParsingException(str(ex))
    
    @staticmethod
    def _unpack_edition(edition: str, cb: CpeBuilder, lenient: bool):
        if edition is None or edition == "":
            return
        
        try:
            unpacked = edition.split("~")
            if edition.startswith("~"):
                if len(unpacked) > 1:
                    cb.wf_edition(Convert.cpe_uri_to_well_formed(unpacked[1], lenient))
                if len(unpacked) > 2:
                    cb.wf_sw_edition(Convert.cpe_uri_to_well_formed(unpacked[2], lenient))
                if len(unpacked) > 3:
                    cb.wf_target_sw(Convert.cpe_uri_to_well_formed(unpacked[3], lenient))
                if len(unpacked) > 4:
                    cb.wf_target_hw(Convert.cpe_uri_to_well_formed(unpacked[4], lenient))
                if len(unpacked) > 5:
                    cb.wf_other(Convert.cpe_uri_to_well_formed(unpacked[5], lenient))
                if len(unpacked) > 6:
                    raise CpeParsingException("Invalid packed edition")
            else:
                cb.wf_edition(Convert.cpe_uri_to_well_formed(edition, lenient))
        except CpeEncodingException as ex:
            raise CpeParsingException(str(ex))
    
    @staticmethod
    def _parse23(cpe_string: str, lenient: bool = False) -> Cpe:
        if cpe_string is None or cpe_string == "":
            raise CpeParsingException("CPE String is null is empty - unable to parse")
        
        cb = CpeBuilder()
        cpe = Cpe23PartIterator(cpe_string)
        
        try:
            cb.part(next(cpe))
            cb.wf_vendor(Convert.fs_to_well_formed(next(cpe), lenient))
            cb.wf_product(Convert.fs_to_well_formed(next(cpe), lenient))
            cb.wf_version(Convert.fs_to_well_formed(next(cpe), lenient))
            cb.wf_update(Convert.fs_to_well_formed(next(cpe), lenient))
            cb.wf_edition(Convert.fs_to_well_formed(next(cpe), lenient))
            cb.wf_language(Convert.fs_to_well_formed(next(cpe), lenient))
            cb.wf_sw_edition(Convert.fs_to_well_formed(next(cpe), lenient))
            cb.wf_target_sw(Convert.fs_to_well_formed(next(cpe), lenient))
            cb.wf_target_hw(Convert.fs_to_well_formed(next(cpe), lenient))
            cb.wf_other(Convert.fs_to_well_formed(next(cpe), lenient))
        except StopIteration:
            raise CpeParsingException(f"Invalid CPE (too few components): {cpe_string}")
        
        if cpe.has_next():
            raise CpeParsingException(f"Invalid CPE (too many components): {cpe_string}")
        
        try:
            return cb.build()
        except CpeValidationException as ex:
            raise CpeParsingException(str(ex))