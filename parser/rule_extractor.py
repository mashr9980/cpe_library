import re
from typing import Tuple

class RuleBasedExtractor:
    @staticmethod
    def clean_vendor_name(vendor: str, title: str) -> str:
        if not vendor or not title:
            return vendor
        
        vendor = re.sub(r'[_\-]', ' ', vendor)
        vendor = ' '.join(word.capitalize() for word in vendor.split())
        
        vendor = re.sub(r'\s+(?:project|foundation|org|com|net|innovations|team|group)$', '', vendor, flags=re.I)
        
        title_lower = title.lower()
        vendor_lower = vendor.lower()
        
        if vendor_lower in title_lower:
            start_idx = title_lower.find(vendor_lower)
            end_idx = start_idx + len(vendor_lower)
            title_vendor = title[start_idx:end_idx]
            
            suffixes = ["Inc", "LLC", "Corp", "Ltd", "Limited", "Foundation", "Systems", "Technologies"]
            for suffix in suffixes:
                pattern = rf"{re.escape(title_vendor)}\s+{suffix}\b"
                match = re.search(pattern, title, re.IGNORECASE)
                if match:
                    return match.group(0)
            
            return title_vendor
        
        return vendor
    
    @staticmethod
    def clean_product_name(product: str, title: str) -> str:
        if not product or not title:
            return product
        
        product = re.sub(r'[_\-]', ' ', product)
        product = ' '.join(word.capitalize() for word in product.split())
        
        product = re.sub(r'\s+v?\d+[\.\d\w\-]*$', '', product, flags=re.I)
        product = re.sub(r'\s+\d{4}[\.\d]*$', '', product)
        product = re.sub(r'\s+(?:for|on)\s+\w+.*$', '', product, flags=re.I)
        product = re.sub(r'\s+(?:pro|professional|enterprise|ultimate|lite|community|premium|edition|free|trial|standard)(?:\s+edition)?$', '', product, flags=re.I)
        product = re.sub(r'\s+(?:x86|x64|32-bit|64-bit|arm64)$', '', product, flags=re.I)
        product = re.sub(r'\s+(?:build|beta|alpha|rc)\b.*$', '', product, flags=re.I)
        
        return product.strip()
    
    @staticmethod
    def extract_from_title(title: str, vendor_machine: str, product_machine: str) -> Tuple[str, str]:
        if not title:
            return RuleBasedExtractor.clean_vendor_name(vendor_machine, ""), RuleBasedExtractor.clean_product_name(product_machine, "")
        
        title_clean = re.sub(r'\s+v?\d+[\.\d\w\-]*(?:\s+(?:for|on)\s+\w+.*)?$', '', title, flags=re.I)
        title_clean = re.sub(r'\s+\d{4}[\.\d]*$', '', title_clean)
        title_clean = re.sub(r'\s+(?:build|beta|alpha|rc|edition|pro|premium|enterprise|ultimate|lite|community|free|trial|standard)\b.*$', '', title_clean, flags=re.I)
        title_clean = title_clean.strip()
        
        if not title_clean:
            return RuleBasedExtractor.clean_vendor_name(vendor_machine, title), RuleBasedExtractor.clean_product_name(product_machine, title)
        
        words = title_clean.split()
        if len(words) == 1:
            return words[0], words[0]
        elif len(words) == 2:
            return words[0], words[1]
        else:
            vendor_tokens = re.split(r'[_\-]', vendor_machine.lower())
            best_split = 1
            best_score = 0
            
            for i in range(1, min(len(words), 4)):
                vendor_candidate = ' '.join(words[:i]).lower()
                score = sum(1 for token in vendor_tokens if token in vendor_candidate)
                if score > best_score:
                    best_score = score
                    best_split = i
            
            vendor = ' '.join(words[:best_split])
            product = ' '.join(words[best_split:])
            
            return vendor, product