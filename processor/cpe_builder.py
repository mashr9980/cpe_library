# cpe_parser/cpe_builder.py
from typing import Union
from values.part import Part
from values.logical_value import LogicalValue
from util.convert import Convert
from processor.cpe import Cpe

class CpeBuilder:
    def __init__(self):
        self.reset()
    
    def reset(self):
        self._part = Part.ANY
        self._vendor = LogicalValue.ANY.get_abbreviation()
        self._product = LogicalValue.ANY.get_abbreviation()
        self._version = LogicalValue.ANY.get_abbreviation()
        self._update = LogicalValue.ANY.get_abbreviation()
        self._edition = LogicalValue.ANY.get_abbreviation()
        self._language = LogicalValue.ANY.get_abbreviation()
        self._sw_edition = LogicalValue.ANY.get_abbreviation()
        self._target_sw = LogicalValue.ANY.get_abbreviation()
        self._target_hw = LogicalValue.ANY.get_abbreviation()
        self._other = LogicalValue.ANY.get_abbreviation()
    
    def part(self, part: Union[Part, str]) -> 'CpeBuilder':
        if isinstance(part, str):
            self._part = Part.get_enum(part)
        else:
            self._part = part
        return self
    
    def vendor(self, vendor: Union[str, LogicalValue]) -> 'CpeBuilder':
        if isinstance(vendor, LogicalValue):
            self._vendor = vendor.get_abbreviation()
        else:
            self._vendor = Convert.to_well_formed(vendor)
        return self
    
    def product(self, product: Union[str, LogicalValue]) -> 'CpeBuilder':
        if isinstance(product, LogicalValue):
            self._product = product.get_abbreviation()
        else:
            self._product = Convert.to_well_formed(product)
        return self
    
    def version(self, version: Union[str, LogicalValue]) -> 'CpeBuilder':
        if isinstance(version, LogicalValue):
            self._version = version.get_abbreviation()
        else:
            self._version = Convert.to_well_formed(version)
        return self
    
    def update(self, update: Union[str, LogicalValue]) -> 'CpeBuilder':
        if isinstance(update, LogicalValue):
            self._update = update.get_abbreviation()
        else:
            self._update = Convert.to_well_formed(update)
        return self
    
    def edition(self, edition: Union[str, LogicalValue]) -> 'CpeBuilder':
        if isinstance(edition, LogicalValue):
            self._edition = edition.get_abbreviation()
        else:
            self._edition = Convert.to_well_formed(edition)
        return self
    
    def language(self, language: Union[str, LogicalValue]) -> 'CpeBuilder':
        if isinstance(language, LogicalValue):
            self._language = language.get_abbreviation()
        else:
            self._language = Convert.to_well_formed(language)
        return self
    
    def sw_edition(self, sw_edition: Union[str, LogicalValue]) -> 'CpeBuilder':
        if isinstance(sw_edition, LogicalValue):
            self._sw_edition = sw_edition.get_abbreviation()
        else:
            self._sw_edition = Convert.to_well_formed(sw_edition)
        return self
    
    def target_sw(self, target_sw: Union[str, LogicalValue]) -> 'CpeBuilder':
        if isinstance(target_sw, LogicalValue):
            self._target_sw = target_sw.get_abbreviation()
        else:
            self._target_sw = Convert.to_well_formed(target_sw)
        return self
    
    def target_hw(self, target_hw: Union[str, LogicalValue]) -> 'CpeBuilder':
        if isinstance(target_hw, LogicalValue):
            self._target_hw = target_hw.get_abbreviation()
        else:
            self._target_hw = Convert.to_well_formed(target_hw)
        return self
    
    def other(self, other: Union[str, LogicalValue]) -> 'CpeBuilder':
        if isinstance(other, LogicalValue):
            self._other = other.get_abbreviation()
        else:
            self._other = Convert.to_well_formed(other)
        return self
    
    def wf_vendor(self, vendor: str) -> 'CpeBuilder':
        self._vendor = vendor
        return self
    
    def wf_product(self, product: str) -> 'CpeBuilder':
        self._product = product
        return self
    
    def wf_version(self, version: str) -> 'CpeBuilder':
        self._version = version
        return self
    
    def wf_update(self, update: str) -> 'CpeBuilder':
        self._update = update
        return self
    
    def wf_edition(self, edition: str) -> 'CpeBuilder':
        self._edition = edition
        return self
    
    def wf_language(self, language: str) -> 'CpeBuilder':
        self._language = language
        return self
    
    def wf_sw_edition(self, sw_edition: str) -> 'CpeBuilder':
        self._sw_edition = sw_edition
        return self
    
    def wf_target_sw(self, target_sw: str) -> 'CpeBuilder':
        self._target_sw = target_sw
        return self
    
    def wf_target_hw(self, target_hw: str) -> 'CpeBuilder':
        self._target_hw = target_hw
        return self
    
    def wf_other(self, other: str) -> 'CpeBuilder':
        self._other = other
        return self
    
    def build(self) -> Cpe:
        cpe = Cpe(self._part, self._vendor, self._product, self._version, self._update,
                  self._edition, self._language, self._sw_edition, self._target_sw,
                  self._target_hw, self._other)
        self.reset()
        return cpe