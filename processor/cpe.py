# processor/cpe.py
import re
from typing import Optional, List
from processor.icpe import ICpe
from values.part import Part
from values.logical_value import LogicalValue
from values.relation import Relation
from exceptions.cpe_validation_exception import CpeValidationException
from util.validate import Validate
from util.convert import Convert

class Cpe(ICpe):
    VERSION_SPLIT_PATTERN = re.compile(r"(?:\.|:-)")
    DIGITS_AND_LETTERS_PATTERN = re.compile(r"^(\d+?)((?:[A-z]+)(.*))$")
    
    def __init__(self, part: Part, vendor: str, product: str, version: str, 
                 update: str, edition: str, language: str, sw_edition: str,
                 target_sw: str, target_hw: str, other: str):
        self._validate(vendor, product, version, update, edition, language, 
                      sw_edition, target_sw, target_hw, other)
        self.part = part
        self.vendor = vendor
        self.product = product
        self.version = version
        self.update = update
        self.edition = edition
        self.language = language
        self.sw_edition = sw_edition
        self.target_sw = target_sw
        self.target_hw = target_hw
        self.other = other
    
    def _validate(self, vendor1: str, product1: str, version1: str, update1: str,
                 edition1: str, language1: str, sw_edition1: str, target_sw1: str,
                 target_hw1: str, other1: str):
        components = [
            ("vendor", vendor1), ("product", product1), ("version", version1),
            ("update", update1), ("edition", edition1), ("language", language1),
            ("swEdition", sw_edition1), ("targetSw", target_sw1),
            ("targetHw", target_hw1), ("other", other1)
        ]
        
        for name, component in components:
            status = Validate.component(component)
            if not status.is_valid():
                raise CpeValidationException(f"Invalid {name} component: {status.get_message()}")
    
    def get_part(self) -> Part:
        return self.part
    
    def get_vendor(self) -> str:
        return Convert.from_well_formed(self.vendor)
    
    def get_product(self) -> str:
        return Convert.from_well_formed(self.product)
    
    def get_version(self) -> str:
        return Convert.from_well_formed(self.version)
    
    def get_update(self) -> str:
        return Convert.from_well_formed(self.update)
    
    def get_edition(self) -> str:
        return Convert.from_well_formed(self.edition)
    
    def get_language(self) -> str:
        return Convert.from_well_formed(self.language)
    
    def get_sw_edition(self) -> str:
        return Convert.from_well_formed(self.sw_edition)
    
    def get_target_sw(self) -> str:
        return Convert.from_well_formed(self.target_sw)
    
    def get_target_hw(self) -> str:
        return Convert.from_well_formed(self.target_hw)
    
    def get_other(self) -> str:
        return Convert.from_well_formed(self.other)
    
    def get_well_formed_vendor(self) -> str:
        return self.vendor
    
    def get_well_formed_product(self) -> str:
        return self.product
    
    def get_well_formed_version(self) -> str:
        return self.version
    
    def get_well_formed_update(self) -> str:
        return self.update
    
    def get_well_formed_edition(self) -> str:
        return self.edition
    
    def get_well_formed_language(self) -> str:
        return self.language
    
    def get_well_formed_sw_edition(self) -> str:
        return self.sw_edition
    
    def get_well_formed_target_sw(self) -> str:
        return self.target_sw
    
    def get_well_formed_target_hw(self) -> str:
        return self.target_hw
    
    def get_well_formed_other(self) -> str:
        return self.other
    
    def to_cpe22_uri(self) -> str:
        sb = ["cpe:/"]
        sb.append(Convert.well_formed_to_cpe_uri_part(self.part))
        sb.append(":")
        sb.append(Convert.well_formed_to_cpe_uri(self.vendor))
        sb.append(":")
        sb.append(Convert.well_formed_to_cpe_uri(self.product))
        sb.append(":")
        sb.append(Convert.well_formed_to_cpe_uri(self.version))
        sb.append(":")
        sb.append(Convert.well_formed_to_cpe_uri(self.update))
        sb.append(":")
        
        if not ((self.sw_edition == "" or "*" == self.sw_edition) and
                (self.target_sw == "" or "*" == self.target_sw) and
                (self.target_hw == "" or "*" == self.target_hw) and
                (self.other == "" or "*" == self.other)):
            sb.append("~")
            sb.append(Convert.well_formed_to_cpe_uri(self.edition))
            sb.append("~")
            sb.append(Convert.well_formed_to_cpe_uri(self.sw_edition))
            sb.append("~")
            sb.append(Convert.well_formed_to_cpe_uri(self.target_sw))
            sb.append("~")
            sb.append(Convert.well_formed_to_cpe_uri(self.target_hw))
            sb.append("~")
            sb.append(Convert.well_formed_to_cpe_uri(self.other))
            sb.append(":")
        else:
            sb.append(Convert.well_formed_to_cpe_uri(self.edition))
            sb.append(":")
        
        sb.append(Convert.well_formed_to_cpe_uri(self.language))
        
        result = ''.join(sb)
        return re.sub(r":*$", "", result)
    
    def to_cpe23_fs(self) -> str:
        return (f"cpe:2.3:{Convert.well_formed_to_fs_part(self.part)}:"
                f"{Convert.well_formed_to_fs(self.vendor)}:"
                f"{Convert.well_formed_to_fs(self.product)}:"
                f"{Convert.well_formed_to_fs(self.version)}:"
                f"{Convert.well_formed_to_fs(self.update)}:"
                f"{Convert.well_formed_to_fs(self.edition)}:"
                f"{Convert.well_formed_to_fs(self.language)}:"
                f"{Convert.well_formed_to_fs(self.sw_edition)}:"
                f"{Convert.well_formed_to_fs(self.target_sw)}:"
                f"{Convert.well_formed_to_fs(self.target_hw)}:"
                f"{Convert.well_formed_to_fs(self.other)}")
    
    def matches(self, target: 'ICpe') -> bool:
        result = True
        result &= self._compare_attributes_part(self.part, target.get_part())
        result &= self._compare_attributes_string(self.vendor, target.get_well_formed_vendor())
        result &= self._compare_attributes_string(self.product, target.get_well_formed_product())
        result &= self._compare_attributes_string(self.version, target.get_well_formed_version())
        result &= self._compare_attributes_string(self.update, target.get_well_formed_update())
        result &= self._compare_attributes_string(self.edition, target.get_well_formed_edition())
        result &= self._compare_attributes_string(self.language, target.get_well_formed_language())
        result &= self._compare_attributes_string(self.sw_edition, target.get_well_formed_sw_edition())
        result &= self._compare_attributes_string(self.target_sw, target.get_well_formed_target_sw())
        result &= self._compare_attributes_string(self.target_hw, target.get_well_formed_target_hw())
        result &= self._compare_attributes_string(self.other, target.get_well_formed_other())
        return result
    
    def matched_by(self, target: 'ICpe') -> bool:
        return target.matches(self)
    
    @staticmethod
    def _compare_attributes_part(left: Part, right: Part) -> bool:
        return Cpe.compare_attribute_part(left, right) != Relation.DISJOINT
    
    @staticmethod
    def compare_attribute_part(left: Part, right: Part) -> Relation:
        if left == right:
            return Relation.EQUAL
        elif left == Part.ANY:
            return Relation.SUPERSET
        elif right == Part.ANY:
            return Relation.SUBSET
        return Relation.DISJOINT
    
    @staticmethod
    def _compare_attributes_string(left: str, right: str) -> bool:
        return Cpe.compare_attribute_string(left, right) != Relation.DISJOINT
    
    @staticmethod
    def compare_attribute_string(left: str, right: str) -> Relation:
        if left.lower() == right.lower():
            return Relation.EQUAL
        elif LogicalValue.ANY.get_abbreviation() == left:
            return Relation.SUPERSET
        elif (LogicalValue.NA.get_abbreviation() == left and 
              LogicalValue.ANY.get_abbreviation() == right):
            return Relation.SUBSET
        elif LogicalValue.NA.get_abbreviation() == left:
            return Relation.DISJOINT
        elif LogicalValue.NA.get_abbreviation() == right:
            return Relation.DISJOINT
        elif LogicalValue.ANY.get_abbreviation() == right:
            return Relation.SUBSET
        
        if Cpe._contains_special_character(left):
            p = Convert.well_formed_to_pattern(left.lower())
            m = p.match(right.lower())
            return Relation.SUPERSET if m else Relation.DISJOINT
        return Relation.DISJOINT
    
    @staticmethod
    def _contains_special_character(value: str) -> bool:
        x = 0
        while x < len(value):
            c = value[x]
            if c == '?' or c == '*':
                return True
            elif c == '\\':
                x += 1
            x += 1
        return False
    
    def __hash__(self) -> int:
        return hash((self.part, self.vendor, self.product, self.version, self.update,
                    self.edition, self.language, self.sw_edition, self.target_sw,
                    self.target_hw, self.other))
    
    def __eq__(self, other) -> bool:
        if other is None or not isinstance(other, Cpe):
            return False
        
        return (self.part == other.part and
                self.vendor == other.vendor and
                self.product == other.product and
                self.version == other.version and
                self.update == other.update and
                self.edition == other.edition and
                self.language == other.language and
                self.sw_edition == other.sw_edition and
                self.target_sw == other.target_sw and
                self.target_hw == other.target_hw and
                self.other == other.other)
    
    def __str__(self) -> str:
        return self.to_cpe23_fs()
    
    def __lt__(self, other: 'ICpe') -> bool:
        return self._compare_to(other) < 0
    
    def _compare_to(self, other_object: Optional['ICpe']) -> int:
        if other_object is not None:
            before = -1
            equal = 0
            after = 1
            
            if self is other_object:
                return equal
            
            r = self.get_part().get_abbreviation().lower() < other_object.get_part().get_abbreviation().lower()
            if r:
                return before
            elif self.get_part().get_abbreviation().lower() > other_object.get_part().get_abbreviation().lower():
                return after
            
            r = self.get_vendor() < other_object.get_vendor()
            if r:
                return before
            elif self.get_vendor() > other_object.get_vendor():
                return after
            
            r = self.get_product() < other_object.get_product()
            if r:
                return before
            elif self.get_product() > other_object.get_product():
                return after
            
            r = self._compare_versions(self.get_version(), other_object.get_version())
            if r < 0:
                return before
            elif r > 0:
                return after
            
            r = self.get_update() < other_object.get_update()
            if r:
                return before
            elif self.get_update() > other_object.get_update():
                return after
            
            r = self.get_edition() < other_object.get_edition()
            if r:
                return before
            elif self.get_edition() > other_object.get_edition():
                return after
            
            r = self.get_language() < other_object.get_language()
            if r:
                return before
            elif self.get_language() > other_object.get_language():
                return after
            
            r = self.get_sw_edition() < other_object.get_sw_edition()
            if r:
                return before
            elif self.get_sw_edition() > other_object.get_sw_edition():
                return after
            
            r = self.get_target_sw() < other_object.get_target_sw()
            if r:
                return before
            elif self.get_target_sw() > other_object.get_target_sw():
                return after
            
            r = self.get_target_hw() < other_object.get_target_hw()
            if r:
                return before
            elif self.get_target_hw() > other_object.get_target_hw():
                return after
            
            r = self.get_other() < other_object.get_other()
            if r:
                return before
            elif self.get_other() > other_object.get_other():
                return after
            
            return equal
        return -1
    
    @staticmethod
    def _compare_versions(left: str, right: str) -> int:
        result = 0
        sub_left = Cpe._split_version(left)
        sub_right = Cpe._split_version(right)
        sub_max = min(len(sub_left), len(sub_right))
        
        for x in range(sub_max):
            if Cpe._is_positive_integer(sub_left[x]) and Cpe._is_positive_integer(sub_right[x]):
                try:
                    result = (int(sub_left[x]) > int(sub_right[x])) - (int(sub_left[x]) < int(sub_right[x]))
                except ValueError:
                    if sub_left[x].lower() != sub_right[x].lower():
                        result = (sub_left[x] > sub_right[x]) - (sub_left[x] < sub_right[x])
            else:
                result = (sub_left[x] > sub_right[x]) - (sub_left[x] < sub_right[x])
            
            if result != 0:
                return result
        
        if len(sub_left) > len(sub_right):
            result = 1
        elif len(sub_right) > len(sub_left):
            result = -1
        
        return result
    
    @staticmethod
    def _split_version(s: str) -> List[str]:
        split_string = Cpe.VERSION_SPLIT_PATTERN.split(s)
        res = []
        
        for token in split_string:
            matcher = Cpe.DIGITS_AND_LETTERS_PATTERN.match(token)
            if matcher and matcher.group(3) == "":
                g1 = matcher.group(1)
                g2 = matcher.group(2)
                res.append(g1)
                res.append(g2)
            else:
                res.append(token)
        
        return res
    
    @staticmethod
    def _is_positive_integer(s: str) -> bool:
        if s is None or s == "":
            return False
        
        if s[0] == '0' and len(s) > 1:
            return False
        
        for c in s:
            if c < '0' or c > '9':
                return False
        
        return True