import re
from typing import List, Dict

class ValidationResult:
    def __init__(self, is_valid: bool, issues: List[str] = None, confidence: float = 0.0):
        self.is_valid = is_valid
        self.issues = issues or []
        self.confidence = confidence

class TechnicalValidator:
    @staticmethod
    def validate_extraction(vendor_human: str, vendor_machine: str, product_human: str, 
                          product_machine: str, title: str) -> ValidationResult:
        issues = []
        confidence = 1.0
        
        if not vendor_human or not vendor_machine or not product_human or not product_machine:
            return ValidationResult(False, ["Missing required fields"], 0.0)
        
        vh_clean = re.sub(r'[^a-z0-9]', '', vendor_human.lower().strip())
        vm_clean = re.sub(r'[^a-z0-9]', '', vendor_machine.lower().strip())
        ph_clean = re.sub(r'[^a-z0-9]', '', product_human.lower().strip())
        pm_clean = re.sub(r'[^a-z0-9]', '', product_machine.lower().strip())
        
        if not vh_clean or not vm_clean or not ph_clean or not pm_clean:
            return ValidationResult(False, ["Empty fields after normalization"], 0.0)
        
        if vh_clean[0] != vm_clean[0]:
            issues.append("Vendor start character mismatch")
            confidence -= 0.2
        
        if vh_clean[-1] != vm_clean[-1]:
            issues.append("Vendor end character mismatch")
            confidence -= 0.2
        
        if ph_clean[0] != pm_clean[0]:
            issues.append("Product start character mismatch")
            confidence -= 0.2
        
        if ph_clean[-1] != pm_clean[-1]:
            issues.append("Product end character mismatch")
            confidence -= 0.2
        
        vendor_similarity = TechnicalValidator.jaro_winkler_similarity(vendor_human.lower(), vendor_machine.lower())
        product_similarity = TechnicalValidator.jaro_winkler_similarity(product_human.lower(), product_machine.lower())
        
        if vendor_similarity < 0.6:
            issues.append(f"Low vendor similarity: {vendor_similarity:.2f}")
            confidence -= 0.3
        
        if product_similarity < 0.6:
            issues.append(f"Low product similarity: {product_similarity:.2f}")
            confidence -= 0.3
        
        if not TechnicalValidator.validate_names_in_title(vendor_human, product_human, title):
            issues.append("Names not properly found in title")
            confidence -= 0.2
        
        if not TechnicalValidator.validate_product_after_space(title, vendor_human, product_human):
            issues.append("Product doesn't start after space")
            confidence -= 0.3
        
        is_valid = len(issues) <= 2 and confidence >= 0.5
        return ValidationResult(is_valid, issues, max(0.0, confidence))
    
    @staticmethod
    def validate_names_in_title(vendor: str, product: str, title: str) -> bool:
        if not all([vendor, product, title]):
            return False
        
        title_lower = title.lower()
        vendor_lower = vendor.lower()
        product_lower = product.lower()
        
        vendor_in_title = vendor_lower in title_lower
        product_in_title = product_lower in title_lower
        
        return vendor_in_title and product_in_title
    
    @staticmethod
    def validate_product_after_space(title: str, vendor: str, product: str) -> bool:
        if not all([title, vendor, product]):
            return False
        
        vendor_pos = title.lower().find(vendor.lower())
        if vendor_pos == -1:
            return True
        
        after_vendor = title[vendor_pos + len(vendor):]
        product_pos = after_vendor.lower().find(product.lower())
        
        if product_pos == -1:
            return True
        
        if product_pos == 0:
            return len(after_vendor) > 0 and after_vendor[0].isspace()
        
        return after_vendor[product_pos - 1].isspace()
    
    @staticmethod
    def jaro_winkler_similarity(s1: str, s2: str) -> float:
        if not s1 or not s2:
            return 0.0
        if s1 == s2:
            return 1.0
        
        len1, len2 = len(s1), len(s2)
        max_dist = max(len1, len2) // 2 - 1
        max_dist = max(0, max_dist)
        
        match1 = [False] * len1
        match2 = [False] * len2
        matches = 0
        
        for i in range(len1):
            start = max(0, i - max_dist)
            end = min(i + max_dist + 1, len2)
            for j in range(start, end):
                if match2[j] or s1[i] != s2[j]:
                    continue
                match1[i] = True
                match2[j] = True
                matches += 1
                break
        
        if matches == 0:
            return 0.0
        
        transpositions = 0
        k = 0
        for i in range(len1):
            if not match1[i]:
                continue
            while not match2[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1
        
        jaro = (matches / len1 + matches / len2 + (matches - transpositions/2) / matches) / 3
        
        prefix = 0
        for i in range(min(len1, len2, 4)):
            if s1[i] == s2[i]:
                prefix += 1
            else:
                break
        
        return jaro + 0.1 * prefix * (1 - jaro)