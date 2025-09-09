import os
import xml.etree.ElementTree as ET
import pandas as pd
import logging
import random
import asyncio
import re
from typing import List, Dict, Optional
from pathlib import Path
from collections import defaultdict, Counter

from processor.cpe import Cpe
from processor.cpe_parser import CpeParser
from values.part import Part
from exceptions import CpeParsingException
from parser.ai_corrector import OpenAICorrector

logger = logging.getLogger(__name__)

class RuleBasedCpeProcessor:
    def __init__(self, xml_file_path: str, sample_percentage: float = 0.01):
        self.xml_file_path = xml_file_path
        self.sample_percentage = sample_percentage
        self.namespaces = {
            "cpe": "http://cpe.mitre.org/dictionary/2.0",
            "cpe-23": "http://scap.nist.gov/schema/cpe-extension/2.3"
        }
        
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            self.ai_corrector = OpenAICorrector(openai_api_key)
        else:
            self.ai_corrector = None
            logger.warning("No OpenAI API key found - AI correction disabled")
    
    def parse_xml_file(self) -> List[Dict]:
        logger.info(f"Parsing XML file: {self.xml_file_path}")
        try:
            tree = ET.parse(self.xml_file_path)
            root = tree.getroot()
        except ET.ParseError as e:
            raise
        except FileNotFoundError:
            raise
        
        cpe_items = root.findall(".//cpe:cpe-item", self.namespaces)
        total_items = len(cpe_items)
        sample_size = max(1, int(total_items * self.sample_percentage))
        logger.info(f"Found {total_items} CPE items, sampling {sample_size} items")
        sampled_items = random.sample(cpe_items, sample_size)
        
        grouped_data = self.group_and_process_items(sampled_items)
        logger.info(f"Successfully processed {len(grouped_data)} unique vendor-product combinations")
        return grouped_data
    
    def group_and_process_items(self, cpe_items: List[ET.Element]) -> List[Dict]:
        raw_items = []
        for item in cpe_items:
            try:
                parsed_item = self.parse_single_item(item)
                if parsed_item:
                    raw_items.append(parsed_item)
            except Exception:
                continue
        
        logger.info(f"Parsed {len(raw_items)} raw items from XML")
        
        # STEP 1: Group by exact identifier (vendor_machine|product_machine)
        groups = defaultdict(list)
        for item in raw_items:
            key = (item['vendor_machine'], item['product_machine'])
            groups[key].append(item)
        
        logger.info(f"Created {len(groups)} unique identifier groups")
        
        final_items = []
        exceptions_for_ai = []
        
        for (vendor_machine, product_machine), items in groups.items():
            # Clean all titles by removing versions and components
            cleaned_titles = []
            for item in items:
                cleaned_title = self.clean_title_remove_versions(item['title'], item)
                if cleaned_title:
                    cleaned_titles.append(cleaned_title)
            
            if not cleaned_titles:
                cleaned_titles = [item['title'] for item in items if item['title']]
            
            # STEP 2: Get most common left part from cleaned titles
            vendor_human = self.get_most_common_left_part(cleaned_titles, vendor_machine)
            
            # STEP 3: Extract product name starting after space
            representative_title = cleaned_titles[0] if cleaned_titles else items[0]['title']
            product_human = self.extract_product_after_vendor_space(
                representative_title, vendor_human, product_machine
            )
            
            # Handle vendor=product machine case
            if self.is_same_identifier(vendor_machine, product_machine):
                if vendor_human.lower() == product_human.lower():
                    product_human = self.differentiate_vendor_product(
                        representative_title, vendor_human, product_machine
                    )
            
            # Handle incomplete product names (Project/Foundation cases)
            product_human = self.handle_incomplete_product_names(
                vendor_human, product_human, product_machine, representative_title
            )
            
            # STEP 4: Validate extraction
            validation_result = self.validate_extraction_requirements(
                vendor_human, product_human, vendor_machine, product_machine, 
                representative_title, cleaned_titles
            )
            
            if validation_result['is_valid']:
                final_item = self.create_final_item(
                    items, vendor_human, product_human, vendor_machine, product_machine,
                    extraction_method="rule_based", confidence=validation_result['confidence'],
                    validation_result=validation_result
                )
                final_items.append(final_item)
                logger.debug(f"Rule-based success: {vendor_human} | {product_human}")
            else:
                exceptions_for_ai.append({
                    'items': items,
                    'vendor_machine': vendor_machine,
                    'product_machine': product_machine,
                    'rule_vendor': vendor_human,
                    'rule_product': product_human,
                    'validation_issues': validation_result['issues'],
                    'cleaned_titles': cleaned_titles
                })
                logger.debug(f"Exception for AI: {vendor_machine}|{product_machine} - {validation_result['issues']}")
        
        # Process exceptions with AI if available
        if exceptions_for_ai and self.ai_corrector:
            logger.info(f"Processing {len(exceptions_for_ai)} exceptions with AI")
            ai_corrected = self.process_exceptions_with_ai(exceptions_for_ai)
            final_items.extend(ai_corrected)
        elif exceptions_for_ai:
            logger.warning(f"Found {len(exceptions_for_ai)} exceptions but no AI corrector available")
            for exception in exceptions_for_ai:
                final_item = self.create_final_item(
                    exception['items'], exception['rule_vendor'], exception['rule_product'],
                    exception['vendor_machine'], exception['product_machine'],
                    extraction_method="rule_based_failed", confidence=0.0,
                    validation_result={'is_valid': False, 'issues': exception['validation_issues']}
                )
                final_items.append(final_item)
        
        rule_based_count = sum(1 for item in final_items if item.get('extraction_method') == 'rule_based')
        ai_corrected_count = sum(1 for item in final_items if item.get('extraction_method') == 'ai_corrected')
        failed_count = sum(1 for item in final_items if item.get('extraction_method') == 'rule_based_failed')
        
        logger.info(f"Rule-based extractions: {rule_based_count}")
        logger.info(f"AI-corrected exceptions: {ai_corrected_count}")
        logger.info(f"Failed extractions: {failed_count}")
        
        return final_items
    
    def clean_title_remove_versions(self, title: str, item: Dict) -> str:
        """Remove versions and CPE components from title for most-common-left analysis"""
        if not title:
            return ""
        
        cleaned = title.strip()
        
        # Remove explicit version from CPE
        version = item.get('version', '*')
        if version and version not in ('*', '-'):
            version_escaped = re.escape(version)
            cleaned = re.sub(rf'\b{version_escaped}\b.*$', '', cleaned, flags=re.IGNORECASE).strip()
        
        # Remove other CPE components if no explicit version
        if not version or version in ('*', '-'):
            components = [
                item.get('update', '*'), item.get('edition', '*'), 
                item.get('sw_edition', '*'), item.get('target_sw', '*'),
                item.get('target_hw', '*'), item.get('other', '*')
            ]
            for component in components:
                if component and component not in ('*', '-'):
                    comp_escaped = re.escape(component)
                    new_cleaned = re.sub(rf'\b{comp_escaped}\b.*$', '', cleaned, flags=re.IGNORECASE).strip()
                    if new_cleaned and new_cleaned != cleaned:
                        cleaned = new_cleaned
                        break
        
        # Remove common version patterns
        version_patterns = [
            r'\s+\d+\.\d+[\.\d]*(?:[a-zA-Z]\d*)?(?:\s*(?:RC|Beta|Alpha|Build|Release\s+Candidate)\s*\d*)?.*$',
            r'\s+v\d+[\.\d\w\-]*.*$',
            r'\s+\d{4}(?:\.\d+)*.*$',
            r'\s+(?:for|on)\s+\w+.*$',
            r'\s+(?:build|beta|alpha|rc)\b.*$',
        ]
        
        for pattern in version_patterns:
            new_cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE).strip()
            if new_cleaned and len(new_cleaned) >= len(cleaned) * 0.5:
                cleaned = new_cleaned
                break
        
        return cleaned
    
    def get_most_common_left_part(self, titles: List[str], vendor_machine: str) -> str:
        """Get most common part from left until version"""
        if not titles:
            return self.humanize_machine_identifier(vendor_machine)
        
        if len(titles) == 1:
            return self.extract_vendor_from_single_title(titles[0], vendor_machine)
        
        # Multiple titles: find common left prefix
        all_words = [title.split() for title in titles if title.strip()]
        if not all_words:
            return self.humanize_machine_identifier(vendor_machine)
        
        min_length = min(len(words) for words in all_words)
        common_prefix = []
        
        # Find exact common prefix (case-insensitive comparison, preserve original case)
        for i in range(min_length):
            first_word = all_words[0][i]
            if all(words[i].lower() == first_word.lower() for words in all_words):
                common_prefix.append(first_word)
            else:
                break
        
        if common_prefix:
            vendor_candidate = ' '.join(common_prefix)
            if self.validate_vendor_candidate(vendor_candidate, vendor_machine):
                return vendor_candidate
        
        # Fallback: most frequent first words with extension
        first_words = [words[0] for words in all_words]
        word_counts = Counter(word.lower() for word in first_words)
        most_common_lower = word_counts.most_common(1)[0][0]
        
        for word in first_words:
            if word.lower() == most_common_lower:
                extended_vendor = self.extend_vendor_name(word, titles, vendor_machine)
                return extended_vendor
        
        return self.humanize_machine_identifier(vendor_machine)
    
    def extract_vendor_from_single_title(self, title: str, vendor_machine: str) -> str:
        """Extract vendor from single title using machine identifier hints"""
        words = title.split()
        if not words:
            return self.humanize_machine_identifier(vendor_machine)
        
        vendor_tokens = re.split(r'[_\-]', vendor_machine.lower())
        vendor_tokens = [t for t in vendor_tokens if t and len(t) > 1]
        
        if not vendor_tokens:
            return words[0]
        
        # Find best match length for vendor
        best_length = 1
        best_score = 0
        
        for length in range(1, min(len(words) + 1, 5)):
            candidate = ' '.join(words[:length])
            score = self.calculate_vendor_match_score(candidate.lower(), vendor_tokens)
            if score > best_score:
                best_score = score
                best_length = length
        
        # Ensure we don't take too much (leave something for product)
        max_length = max(1, len(words) - 1)
        final_length = min(best_length, max_length)
        
        return ' '.join(words[:final_length])
    
    def extract_product_after_vendor_space(self, title: str, vendor: str, product_machine: str) -> str:
        """Product must start after a space, not mid-word"""
        if not title or not vendor:
            return self.humanize_machine_identifier(product_machine)
        
        title_lower = title.lower()
        vendor_lower = vendor.lower()
        
        vendor_pos = title_lower.find(vendor_lower)
        if vendor_pos == -1:
            return self.humanize_machine_identifier(product_machine)
        
        after_vendor_pos = vendor_pos + len(vendor)
        
        # Ensure we're at word boundary (space or end of string)
        if after_vendor_pos < len(title) and not title[after_vendor_pos].isspace():
            return self.humanize_machine_identifier(product_machine)
        
        # Get text after vendor
        remaining = title[after_vendor_pos:].strip()
        if not remaining:
            return self.humanize_machine_identifier(product_machine)
        
        # Clean product name
        product_name = self.clean_product_name_strict(remaining, product_machine)
        
        return product_name if product_name else self.humanize_machine_identifier(product_machine)
    
    def clean_product_name_strict(self, product_text: str, product_machine: str) -> str:
        """Clean product name according to requirements"""
        if not product_text:
            return ""
        
        cleaned = product_text.strip()
        
        # Remove target software indicators (major requirement)
        target_patterns = [
            r'\s+for\s+wordpress.*$',
            r'\s+for\s+windows.*$',
            r'\s+for\s+linux.*$',
            r'\s+for\s+android.*$',
            r'\s+for\s+ios.*$',
            r'\s+for\s+mac\s+os.*$',
            r'\s+for\s+node\.js.*$',
            r'\s+for\s+php.*$',
            r'\s+for\s+java.*$',
            r'\s+for\s+confluence.*$',
            r'\s+for\s+jenkins.*$',
            r'\s+for\s+\w+.*$',
        ]
        
        for pattern in target_patterns:
            new_cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
            if new_cleaned != cleaned:
                cleaned = new_cleaned.strip()
                break
        
        # Remove edition info
        edition_patterns = [
            r'\s+(?:pro|professional|enterprise|ultimate|lite|community|premium|standard|free|trial)\s+edition.*$',
            r'\s+(?:pro|professional|enterprise|ultimate|lite|community|premium|standard|free|trial)(?:\s|$)',
        ]
        
        for pattern in edition_patterns:
            new_cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
            if new_cleaned != cleaned and len(new_cleaned.strip()) > 0:
                cleaned = new_cleaned.strip()
                break
        
        # Remove version info
        version_patterns = [
            r'\s+\d+\.\d+[\.\d]*.*$',
            r'\s+v\d+[\.\d\w\-]*.*$',
            r'\s+\d{4}[\.\d]*.*$',
            r'\s+(?:build|beta|alpha|rc|release\s+candidate)\b.*$',
        ]
        
        for pattern in version_patterns:
            new_cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
            if new_cleaned != cleaned and len(new_cleaned.strip()) > 2:
                cleaned = new_cleaned.strip()
                break
        
        # Remove excessive parenthetical descriptions
        if '(' in cleaned and len(cleaned) > 40:
            paren_removed = re.sub(r'\s*\([^)]*\)\s*', ' ', cleaned).strip()
            paren_removed = re.sub(r'\s+', ' ', paren_removed)
            if len(paren_removed) > 3:
                cleaned = paren_removed
        
        return cleaned.strip()
    
    def is_same_identifier(self, vendor_machine: str, product_machine: str) -> bool:
        """Check if vendor and product machine identifiers are essentially the same"""
        v_clean = vendor_machine.replace('_', '').replace('-', '').lower()
        p_clean = product_machine.replace('_', '').replace('-', '').lower()
        return v_clean == p_clean
    
    def differentiate_vendor_product(self, title: str, vendor: str, product_machine: str) -> str:
        """Handle case where vendor=product machine identifiers"""
        words = title.split()
        vendor_words = vendor.split()
        
        # Try to find additional product-specific words after vendor
        if len(words) > len(vendor_words):
            additional_words = words[len(vendor_words):]
            # Take first 1-3 additional words as product differentiator
            product_extension = ' '.join(additional_words[:3])
            product_extension = self.clean_product_name_strict(product_extension, product_machine)
            
            if product_extension and len(product_extension) > 2:
                return product_extension
        
        return self.humanize_machine_identifier(product_machine)
    
    def handle_incomplete_product_names(self, vendor_human: str, product_human: str, 
                                      product_machine: str, title: str) -> str:
        """Fix incomplete product names for Project/Foundation cases"""
        # Check if vendor contains "Project" or "Foundation" but product doesn't
        vendor_lower = vendor_human.lower()
        product_lower = product_human.lower()
        
        organizational_suffixes = ['project', 'foundation', 'organization', 'org', 'team', 'group']
        
        # If vendor has org suffix but product is just the base name
        for suffix in organizational_suffixes:
            if suffix in vendor_lower and suffix not in product_lower:
                # Check if the full product name should include the organizational context
                machine_tokens = re.split(r'[_\-]', product_machine.lower())
                if suffix in machine_tokens or 'project' in machine_tokens:
                    # The product should probably include the project/foundation context
                    if f"{product_human} {suffix.title()}" in title:
                        return f"{product_human} {suffix.title()}"
        
        return product_human
    
    def validate_extraction_requirements(self, vendor_human: str, product_human: str, 
                                       vendor_machine: str, product_machine: str, 
                                       title: str, cleaned_titles: List[str]) -> Dict:
        """Validate according to client requirements"""
        issues = []
        confidence = 1.0
        
        # Basic validation
        if not vendor_human or not product_human:
            return {'is_valid': False, 'issues': ['Missing vendor or product'], 'confidence': 0.0}
        
        # Character alignment validation
        vh_clean = re.sub(r'[^a-z0-9]', '', vendor_human.lower())
        vm_clean = re.sub(r'[^a-z0-9]', '', vendor_machine.lower())
        ph_clean = re.sub(r'[^a-z0-9]', '', product_human.lower())
        pm_clean = re.sub(r'[^a-z0-9]', '', product_machine.lower())
        
        # Start/end character alignment
        if vh_clean and vm_clean and vh_clean[0] != vm_clean[0]:
            issues.append("Vendor start character mismatch")
            confidence -= 0.25
        
        if ph_clean and pm_clean and ph_clean[0] != pm_clean[0]:
            issues.append("Product start character mismatch")
            confidence -= 0.25
        
        if vh_clean and vm_clean and vh_clean[-1] != vm_clean[-1]:
            issues.append("Vendor end character mismatch")
            confidence -= 0.25
        
        if ph_clean and pm_clean and ph_clean[-1] != pm_clean[-1]:
            issues.append("Product end character mismatch")
            confidence -= 0.25
        
        # Similarity validation
        vendor_similarity = self.jaro_winkler_similarity(vendor_human.lower(), vendor_machine.lower())
        product_similarity = self.jaro_winkler_similarity(product_human.lower(), product_machine.lower())
        
        if vendor_similarity < 0.65:
            issues.append(f"Low vendor similarity: {vendor_similarity:.2f}")
            confidence -= 0.3
        
        if product_similarity < 0.65:
            issues.append(f"Low product similarity: {product_similarity:.2f}")
            confidence -= 0.3
        
        # Product starts after space validation
        if not self.validate_product_after_space_strict(title, vendor_human, product_human):
            issues.append("Product doesn't start after space")
            confidence -= 0.4
        
        # Title reconstruction validation
        reconstructed = f"{vendor_human} {product_human}".strip()
        if not any(reconstructed.lower() in t.lower() for t in [title] + cleaned_titles):
            issues.append("Reconstruction not found in title")
            confidence -= 0.15
        
        # Check for prohibited content in product name
        if re.search(r'\d+\.\d+', product_human):
            issues.append("Version found in product name")
            confidence -= 0.4
        
        if re.search(r'for\s+(wordpress|windows|linux|android|ios|mac|node\.js|php|java)', product_human, re.IGNORECASE):
            issues.append("Target software found in product name")
            confidence -= 0.5
        
        # Strict validation: no issues allowed for rule-based success
        is_valid = len(issues) == 0 and confidence >= 0.85
        
        return {
            'is_valid': is_valid,
            'issues': issues,
            'confidence': max(0.0, confidence),
            'vendor_similarity': vendor_similarity,
            'product_similarity': product_similarity
        }
    
    def validate_product_after_space_strict(self, title: str, vendor: str, product: str) -> bool:
        """Validate that product starts after a space"""
        if not all([title, vendor, product]):
            return False
        
        title_lower = title.lower()
        vendor_lower = vendor.lower()
        product_lower = product.lower()
        
        vendor_pos = title_lower.find(vendor_lower)
        if vendor_pos == -1:
            return False
        
        after_vendor_pos = vendor_pos + len(vendor)
        
        # Must have space after vendor
        if after_vendor_pos >= len(title) or not title[after_vendor_pos].isspace():
            return False
        
        # Find product in remaining text
        remaining = title[after_vendor_pos:].strip()
        product_pos = remaining.lower().find(product_lower)
        
        if product_pos == -1:
            return False
        
        # Product must start at beginning of remaining text (after space)
        return product_pos == 0
    
    def extend_vendor_name(self, base_vendor: str, titles: List[str], vendor_machine: str) -> str:
        """Try to extend vendor name with additional common words"""
        base_vendor_lower = base_vendor.lower()
        
        # Look for common second words
        second_words = []
        for title in titles:
            words = title.split()
            if len(words) > 1 and words[0].lower() == base_vendor_lower:
                second_words.append(words[1])
        
        if second_words:
            word_counts = Counter(word.lower() for word in second_words)
            if len(word_counts) == 1:  # All second words are the same
                most_common_second = word_counts.most_common(1)[0][0]
                for word in second_words:
                    if word.lower() == most_common_second:
                        extended = f"{base_vendor} {word}"
                        if self.validate_vendor_candidate(extended, vendor_machine):
                            return extended
        
        return base_vendor
    
    def validate_vendor_candidate(self, vendor: str, vendor_machine: str) -> bool:
        """Validate if vendor candidate makes sense"""
        if not vendor or len(vendor.strip()) < 2:
            return False
        
        similarity = self.jaro_winkler_similarity(vendor.lower(), vendor_machine.lower())
        return similarity >= 0.5
    
    def calculate_vendor_match_score(self, candidate: str, vendor_tokens: List[str]) -> float:
        """Calculate how well candidate matches vendor tokens"""
        if not candidate or not vendor_tokens:
            return 0.0
        
        candidate_tokens = re.findall(r'[a-z0-9]+', candidate.lower())
        if not candidate_tokens:
            return 0.0
        
        matches = 0
        for vendor_token in vendor_tokens:
            for candidate_token in candidate_tokens:
                if vendor_token in candidate_token or candidate_token in vendor_token:
                    matches += 1
                    break
        
        return matches / len(vendor_tokens)
    
    def humanize_machine_identifier(self, machine_id: str) -> str:
        """Convert machine identifier to human-readable format"""
        if not machine_id:
            return ""
        
        humanized = re.sub(r'[_\-]', ' ', machine_id)
        humanized = ' '.join(word.capitalize() for word in humanized.split())
        
        return humanized
    
    def jaro_winkler_similarity(self, s1: str, s2: str) -> float:
        """Calculate Jaro-Winkler similarity between two strings"""
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
    
    def process_exceptions_with_ai(self, exceptions: List[Dict]) -> List[Dict]:
        """Process exceptions using AI correction"""
        final_items = []
        
        for exception in exceptions:
            items = exception['items']
            vendor_machine = exception['vendor_machine']
            product_machine = exception['product_machine']
            
            try:
                ai_result = asyncio.run(self.ai_corrector.correct_extraction(
                    cpe=items[0]['cpe'],
                    title=items[0]['title'],
                    vendor_machine=vendor_machine,
                    product_machine=product_machine,
                    part=items[0]['part'].get_abbreviation(),
                    target_sw=items[0]['target_sw']
                ))
                
                vendor_human = ai_result.get('vendor_name', '').strip()
                product_human = ai_result.get('product_name', '').strip()
                
                if vendor_human and product_human:
                    validation_result = self.validate_extraction_requirements(
                        vendor_human, product_human, vendor_machine, product_machine, 
                        items[0]['title'], [items[0]['title']]
                    )
                    
                    final_item = self.create_final_item(
                        items, vendor_human, product_human, vendor_machine, product_machine,
                        extraction_method="ai_corrected", confidence=0.8,
                        validation_result=validation_result
                    )
                    final_items.append(final_item)
                else:
                    final_item = self.create_final_item(
                        items, exception['rule_vendor'], exception['rule_product'],
                        vendor_machine, product_machine,
                        extraction_method="ai_failed", confidence=0.0,
                        validation_result={'is_valid': False, 'issues': ['AI correction failed']}
                    )
                    final_items.append(final_item)
                    
            except Exception as e:
                logger.error(f"AI correction failed for {vendor_machine}|{product_machine}: {e}")
                final_item = self.create_final_item(
                    items, exception['rule_vendor'], exception['rule_product'],
                    vendor_machine, product_machine,
                    extraction_method="ai_error", confidence=0.0,
                    validation_result={'is_valid': False, 'issues': [f'AI error: {str(e)}']}
                )
                final_items.append(final_item)
        
        return final_items
    
    def create_final_item(self, items: List[Dict], vendor_human: str, product_human: str,
                         vendor_machine: str, product_machine: str, extraction_method: str,
                         confidence: float, validation_result: Dict) -> Dict:
        """Create final output item"""
        all_cpes = [item['cpe'] for item in items]
        all_versions = list(set(item['version'] for item in items if item['version'] != "-"))
        all_references = []
        for item in items:
            all_references.extend(item.get('references', []))
        
        rep = items[0]
        
        return {
            "cpe": " | ".join(all_cpes),
            "Title": rep['title'],
            "vendor_human": vendor_human,
            "product_human": product_human,
            "Validation Product Name": validation_result['is_valid'],
            "part": rep['part'].get_abbreviation(),
            "target_softwares": [rep['target_sw']] if rep['target_sw'] != "*" else ["*"],
            "target_hardwares": [rep['target_hw']] if rep['target_hw'] != "*" else ["*"],
            "versions": all_versions if all_versions else ["-"],
            "updates": [rep['update']] if rep['update'] != "*" else ["*"],
            "editions": [rep['edition']] if rep['edition'] != "*" else ["*"],
            "languages": [rep['language']] if rep['language'] != "*" else ["*"],
            "references": list(set(all_references)),
            "category": self.get_corrected_category(rep['part'], product_machine, rep['title']),
            "Part_Type": rep['part'].get_abbreviation(),
            "Vendor_Machine": vendor_machine,
            "Product_Machine": product_machine,
            "Group_Identifier": f"{vendor_machine}|{product_machine}",
            "Extraction_Method": extraction_method,
            "Confidence": confidence,
            "Validation_Issues": "; ".join(validation_result.get('issues', [])),
            "Vendor_Similarity": validation_result.get('vendor_similarity', 0.0),
            "Product_Similarity": validation_result.get('product_similarity', 0.0)
        }
    
    def parse_single_item(self, cpe_item: ET.Element) -> Optional[Dict]:
        """Parse a single CPE item from XML"""
        try:
            cpe_22_uri = cpe_item.get("name", "") or ""
            cpe_23_element = cpe_item.find(".//cpe-23:cpe23-item", self.namespaces)
            cpe_23_fs = cpe_23_element.get("name", "") if cpe_23_element is not None else ""
            title_element = cpe_item.find(".//cpe:title", self.namespaces)
            title = title_element.text if title_element is not None else ""
            
            references = []
            ref_elements = cpe_item.findall(".//cpe:reference", self.namespaces)
            for ref in ref_elements:
                href = ref.get("href", "")
                if href:
                    references.append(href)
            
            cpe_string = cpe_23_fs if cpe_23_fs else cpe_22_uri
            if not cpe_string:
                return None
            
            parsed_cpe = CpeParser.parse(cpe_string)
            
            return {
                "cpe": cpe_string,
                "title": title,
                "vendor_machine": parsed_cpe.get_vendor(),
                "product_machine": parsed_cpe.get_product(),
                "version": parsed_cpe.get_version(),
                "update": parsed_cpe.get_update(),
                "edition": parsed_cpe.get_edition(),
                "language": parsed_cpe.get_language(),
                "sw_edition": parsed_cpe.get_sw_edition(),
                "target_sw": parsed_cpe.get_target_sw(),
                "target_hw": parsed_cpe.get_target_hw(),
                "other": parsed_cpe.get_other(),
                "part": parsed_cpe.get_part(),
                "references": references
            }
        except CpeParsingException:
            return None
        except Exception:
            return None
    
    def get_category_from_part(self, part: Part) -> str:
        """Get category from CPE part"""
        if part == Part.APPLICATION:
            return "Application"
        elif part == Part.OPERATING_SYSTEM:
            return "Operating System"
        elif part == Part.HARDWARE_DEVICE:
            return "Hardware"
        else:
            return "Unknown"
    
    def get_corrected_category(self, part: Part, product_machine: str, title: str) -> str:
        """Get corrected category for hardware/firmware detection"""
        base_category = self.get_category_from_part(part)
        
        if part == Part.OPERATING_SYSTEM and self.should_be_hardware_firmware(product_machine, title):
            return "Hardware/Firmware"
        
        return base_category
    
    def should_be_hardware_firmware(self, product_machine: str, title: str) -> bool:
        """Determine if OS should be categorized as Hardware/Firmware"""
        firmware_indicators = [
            "firmware", "bios", "uefi", "bootloader", "microcode",
            "driver", "embedded", "controller", "device"
        ]
        hardware_indicators = [
            "router", "switch", "firewall", "camera", "printer",
            "scanner", "monitor", "keyboard", "mouse", "tablet",
            "phone", "gateway", "access_point", "nvr", "dvr"
        ]
        
        product_lower = product_machine.lower()
        title_lower = title.lower()
        
        has_firmware = any(indicator in product_lower or indicator in title_lower 
                          for indicator in firmware_indicators)
        has_hardware = any(indicator in product_lower or indicator in title_lower 
                          for indicator in hardware_indicators)
        
        return has_firmware or has_hardware
    
    def create_excel_file(self, data: List[Dict], output_file: str):
        """Create Excel output file"""
        logger.info(f"Creating Excel file: {output_file}")
        columns = [
            "cpe", "Title", "vendor_human", "product_human", "Validation Product Name",
            "part", "target_softwares", "target_hardwares", "versions", "updates",
            "editions", "languages", "references", "category", "Part_Type", 
            "Vendor_Machine", "Product_Machine", "Group_Identifier",
            "Extraction_Method", "Confidence", "Validation_Issues",
            "Vendor_Similarity", "Product_Similarity"
        ]
        df = pd.DataFrame(data)
        df = df.reindex(columns=columns, fill_value="")
        
        output_dir = Path(output_file).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Sheet1", index=False)
        
        logger.info(f"Excel file created successfully: {output_file}")
        logger.info(f"Total records: {len(df)}")
        valid_sum = df["Validation Product Name"].sum() if "Validation Product Name" in df.columns else 0
        logger.info(f"Validation passed: {valid_sum}")
        logger.info(f"Validation failed: {len(df) - valid_sum}")
        
        rule_based_count = df[df["Extraction_Method"] == "rule_based"].shape[0]
        ai_corrected_count = df[df["Extraction_Method"] == "ai_corrected"].shape[0]
        logger.info(f"Rule-based success rate: {rule_based_count}")
        logger.info(f"AI-corrected exceptions: {ai_corrected_count}")
    
    def run(self, output_file: str):
        """Main execution method"""
        logger.info("Starting RULE-BASED CPE processing (AI only for exceptions)")
        if not Path(self.xml_file_path).exists():
            raise FileNotFoundError(f"XML file not found: {self.xml_file_path}")
        
        cpe_data = self.parse_xml_file()
        if not cpe_data:
            logger.error("No valid CPE data found")
            return
        
        self.create_excel_file(cpe_data, output_file)
        logger.info("CPE processing completed successfully")

# Maintain backward compatibility
UnifiedCpeProcessor = RuleBasedCpeProcessor