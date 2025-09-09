import re
from typing import Tuple, List, Dict
from collections import Counter

class AdvancedRuleBasedExtractor:
    
    @staticmethod
    def extract_vendor_product_from_group(titles: List[str], vendor_machine: str, product_machine: str) -> Tuple[str, str]:
        if not titles:
            return AdvancedRuleBasedExtractor.humanize_machine_identifier(vendor_machine), AdvancedRuleBasedExtractor.humanize_machine_identifier(product_machine)
        
        if len(titles) == 1:
            return AdvancedRuleBasedExtractor.extract_from_single_title(titles[0], vendor_machine, product_machine)
        
        most_common_left = AdvancedRuleBasedExtractor.find_most_common_left(titles)
        
        representative_title = titles[0]
        product_name = AdvancedRuleBasedExtractor.extract_product_after_vendor(representative_title, most_common_left, product_machine)
        
        return most_common_left, product_name
    
    @staticmethod
    def find_most_common_left(titles: List[str]) -> str:
        all_tokens = []
        for title in titles:
            tokens = title.split()
            if tokens:
                all_tokens.append(tokens)
        
        if not all_tokens:
            return ""
        
        min_length = min(len(tokens) for tokens in all_tokens)
        common_prefix = []
        
        for i in range(min_length):
            first_token = all_tokens[0][i]
            if all(tokens[i].lower() == first_token.lower() for tokens in all_tokens):
                common_prefix.append(first_token)
            else:
                break
        
        if common_prefix:
            return ' '.join(common_prefix)
        
        first_tokens = [tokens[0] for tokens in all_tokens]
        token_counter = Counter(token.lower() for token in first_tokens)
        most_common_lower = token_counter.most_common(1)[0][0]
        
        for token in first_tokens:
            if token.lower() == most_common_lower:
                return token
        
        return first_tokens[0]
    
    @staticmethod
    def extract_from_single_title(title: str, vendor_machine: str, product_machine: str) -> Tuple[str, str]:
        tokens = title.split()
        if not tokens:
            return AdvancedRuleBasedExtractor.humanize_machine_identifier(vendor_machine), AdvancedRuleBasedExtractor.humanize_machine_identifier(product_machine)
        
        if len(tokens) == 1:
            return tokens[0], tokens[0]
        
        vendor_tokens = re.split(r'[_\-]', vendor_machine.lower())
        vendor_tokens = [t for t in vendor_tokens if t]
        
        best_split = 1
        best_score = 0
        
        for i in range(1, min(len(tokens), 4)):
            candidate_vendor = ' '.join(tokens[:i]).lower()
            score = AdvancedRuleBasedExtractor.calculate_token_overlap(candidate_vendor, vendor_tokens)
            if score > best_score:
                best_score = score
                best_split = i
        
        vendor = ' '.join(tokens[:best_split])
        product = ' '.join(tokens[best_split:]) if best_split < len(tokens) else AdvancedRuleBasedExtractor.humanize_machine_identifier(product_machine)
        
        return vendor, product
    
    @staticmethod
    def extract_product_after_vendor(title: str, vendor: str, product_machine: str) -> str:
        if not vendor or not title:
            return AdvancedRuleBasedExtractor.humanize_machine_identifier(product_machine)
        
        vendor_pos = title.lower().find(vendor.lower())
        if vendor_pos == -1:
            return AdvancedRuleBasedExtractor.humanize_machine_identifier(product_machine)
        
        after_vendor_pos = vendor_pos + len(vendor)
        remaining = title[after_vendor_pos:].lstrip()
        
        if not remaining:
            return AdvancedRuleBasedExtractor.humanize_machine_identifier(product_machine)
        
        product_tokens = re.split(r'[_\-]', product_machine.lower())
        product_tokens = [t for t in product_tokens if t]
        
        words = remaining.split()
        best_match = None
        best_score = 0
        
        for i in range(1, len(words) + 1):
            candidate = ' '.join(words[:i])
            score = AdvancedRuleBasedExtractor.calculate_token_overlap(candidate.lower(), product_tokens)
            if score > best_score:
                best_score = score
                best_match = candidate
        
        return best_match if best_match else words[0] if words else AdvancedRuleBasedExtractor.humanize_machine_identifier(product_machine)
    
    @staticmethod
    def calculate_token_overlap(candidate: str, machine_tokens: List[str]) -> float:
        if not candidate or not machine_tokens:
            return 0.0
        
        candidate_tokens = re.findall(r'[a-z0-9]+', candidate.lower())
        if not candidate_tokens:
            return 0.0
        
        matches = 0
        for machine_token in machine_tokens:
            for candidate_token in candidate_tokens:
                if machine_token in candidate_token or candidate_token in machine_token:
                    matches += 1
                    break
        
        return matches / len(machine_tokens)
    
    @staticmethod
    def humanize_machine_identifier(machine_id: str) -> str:
        if not machine_id:
            return ""
        
        humanized = re.sub(r'[_\-]', ' ', machine_id)
        words = humanized.split()
        return ' '.join(word.capitalize() for word in words)
    
    @staticmethod
    def clean_title_for_extraction(title: str, version_info: Dict) -> str:
        cleaned = title
        
        version = version_info.get('version', '*')
        if version and version != '*' and version != '-':
            version_escaped = re.escape(version)
            cleaned = re.sub(rf'\b{version_escaped}\b.*$', '', cleaned, flags=re.IGNORECASE)
        
        update = version_info.get('update', '*')
        edition = version_info.get('edition', '*')
        sw_edition = version_info.get('sw_edition', '*')
        target_sw = version_info.get('target_sw', '*')
        target_hw = version_info.get('target_hw', '*')
        other = version_info.get('other', '*')
        
        components = [update, edition, sw_edition, target_sw, target_hw, other]
        for component in components:
            if component and component not in ('*', '-'):
                comp_escaped = re.escape(component)
                new_cleaned = re.sub(rf'\b{comp_escaped}\b.*$', '', cleaned, flags=re.IGNORECASE)
                if new_cleaned != cleaned:
                    cleaned = new_cleaned
                    break
        
        version_patterns = [
            r'\b\d+\.\d+[\.\d]*(?:\.\d+)*(?:[a-zA-Z]\d*)?(?:\s*(?:RC|Beta|Alpha|Build)\s*\d*)?.*$',
            r'\bv?\d+[\.\d\w\-]*.*$',
            r'\b\d{4}[\.\d]*.*$',
            r'\s+(?:for|on)\s+\w+.*$',
            r'\s+(?:build|beta|alpha|rc)\b.*$',
            r'\s+(?:pro|professional|enterprise|ultimate|lite|community|premium|edition|free|trial|standard)(?:\s+edition)?.*$'
        ]
        
        for pattern in version_patterns:
            new_cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
            if new_cleaned != cleaned and len(new_cleaned.strip()) > 0:
                cleaned = new_cleaned
                break
        
        return cleaned.strip()
    
    @staticmethod
    def validate_product_starts_after_space(title: str, vendor: str, product: str) -> bool:
        if not all([title, vendor, product]):
            return False
        
        vendor_pos = title.lower().find(vendor.lower())
        if vendor_pos == -1:
            return False
        
        after_vendor_pos = vendor_pos + len(vendor)
        if after_vendor_pos >= len(title):
            return False
        
        remaining = title[after_vendor_pos:]
        product_pos = remaining.lower().find(product.lower())
        
        if product_pos == -1:
            return False
        
        if product_pos == 0:
            return remaining[0].isspace()
        
        return remaining[product_pos - 1].isspace()
    
    @staticmethod
    def validate_character_alignment(human_name: str, machine_name: str) -> Dict[str, bool]:
        human_clean = re.sub(r'[^a-z0-9]', '', human_name.lower())
        machine_clean = re.sub(r'[^a-z0-9]', '', machine_name.lower())
        
        if not human_clean or not machine_clean:
            return {'start_match': False, 'end_match': False}
        
        start_match = human_clean[0] == machine_clean[0]
        end_match = human_clean[-1] == machine_clean[-1]
        
        return {'start_match': start_match, 'end_match': end_match}