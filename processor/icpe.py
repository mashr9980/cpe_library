# cpe_parser/icpe.py
from abc import ABC, abstractmethod
from values.part import Part

class ICpe(ABC):
    @abstractmethod
    def get_part(self) -> Part:
        pass
    
    @abstractmethod
    def get_vendor(self) -> str:
        pass
    
    @abstractmethod
    def get_product(self) -> str:
        pass
    
    @abstractmethod
    def get_version(self) -> str:
        pass
    
    @abstractmethod
    def get_update(self) -> str:
        pass
    
    @abstractmethod
    def get_edition(self) -> str:
        pass
    
    @abstractmethod
    def get_language(self) -> str:
        pass
    
    @abstractmethod
    def get_sw_edition(self) -> str:
        pass
    
    @abstractmethod
    def get_target_sw(self) -> str:
        pass
    
    @abstractmethod
    def get_target_hw(self) -> str:
        pass
    
    @abstractmethod
    def get_other(self) -> str:
        pass
    
    @abstractmethod
    def get_well_formed_vendor(self) -> str:
        pass
    
    @abstractmethod
    def get_well_formed_product(self) -> str:
        pass
    
    @abstractmethod
    def get_well_formed_version(self) -> str:
        pass
    
    @abstractmethod
    def get_well_formed_update(self) -> str:
        pass
    
    @abstractmethod
    def get_well_formed_edition(self) -> str:
        pass
    
    @abstractmethod
    def get_well_formed_language(self) -> str:
        pass
    
    @abstractmethod
    def get_well_formed_sw_edition(self) -> str:
        pass
    
    @abstractmethod
    def get_well_formed_target_sw(self) -> str:
        pass
    
    @abstractmethod
    def get_well_formed_target_hw(self) -> str:
        pass
    
    @abstractmethod
    def get_well_formed_other(self) -> str:
        pass
    
    @abstractmethod
    def to_cpe22_uri(self) -> str:
        pass
    
    @abstractmethod
    def to_cpe23_fs(self) -> str:
        pass
    
    @abstractmethod
    def matches(self, target: 'ICpe') -> bool:
        pass
    
    @abstractmethod
    def matched_by(self, target: 'ICpe') -> bool:
        pass