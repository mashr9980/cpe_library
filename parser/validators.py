import re
from typing import List

class ValidationResult:
    def __init__(self, is_valid: bool, issues: List[str] = None):
        self.is_valid = is_valid
        self.issues = issues or []

class TechnicalValidator:
    @staticmethod
    def validate_extraction(vendor_human: str, vendor_machine: str, product_human: str, 
                          product_machine: str, version: str, target_sw: str, title: str) -> ValidationResult:
        issues = []
        
        if not vendor_human or not vendor_machine or not product_human or not product_machine:
            issues.append("Missing required fields")
            return ValidationResult(False, issues)
        
        vh_clean = re.sub(r'[^a-z0-9]', '', vendor_human.lower().strip())
        vm_clean = re.sub(r'[^a-z0-9]', '', vendor_machine.lower().strip())
        ph_clean = re.sub(r'[^a-z0-9]', '', product_human.lower().strip())
        pm_clean = re.sub(r'[^a-z0-9]', '', product_machine.lower().strip())
        
        if not vh_clean or not vm_clean or not ph_clean or not pm_clean:
            issues.append("Empty fields after normalization")
            return ValidationResult(False, issues)
        
        if vh_clean[0] != vm_clean[0]:
            issues.append("Vendor start character mismatch")
        
        if vh_clean[-1] != vm_clean[-1]:
            issues.append("Vendor end character mismatch")
        
        if ph_clean[0] != pm_clean[0]:
            issues.append("Product start character mismatch")
        
        if ph_clean[-1] != pm_clean[-1]:
            issues.append("Product end character mismatch")
        
        vendor_tokens = set(re.findall(r'[a-z0-9]+', vendor_human.lower()))
        machine_vendor_tokens = set(re.findall(r'[a-z0-9]+', vendor_machine.lower()))
        product_tokens = set(re.findall(r'[a-z0-9]+', product_human.lower()))
        machine_product_tokens = set(re.findall(r'[a-z0-9]+', product_machine.lower()))
        
        vendor_overlap = len(vendor_tokens & machine_vendor_tokens) / max(len(vendor_tokens), len(machine_vendor_tokens)) if vendor_tokens else 0
        product_overlap = len(product_tokens & machine_product_tokens) / max(len(product_tokens), len(machine_product_tokens)) if product_tokens else 0
        
        if vendor_overlap < 0.3:
            issues.append("Insufficient vendor token overlap")
        
        if product_overlap < 0.3:
            issues.append("Insufficient product token overlap")
        
        title_lower = title.lower()
        vendor_found = any(token in title_lower for token in vendor_tokens if len(token) > 2)
        product_found = any(token in title_lower for token in product_tokens if len(token) > 2)
        
        if not vendor_found and vendor_human.lower() not in title_lower:
            issues.append("Vendor name not found in title")
        
        if not product_found and product_human.lower() not in title_lower:
            issues.append("Product name not found in title")
        
        return ValidationResult(len(issues) <= 2, issues)