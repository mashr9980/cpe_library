import os
import xml.etree.ElementTree as ET
import pandas as pd
import logging
import random
import asyncio
import json
import requests
import re
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from collections import defaultdict, Counter

from processor.cpe import Cpe
from processor.cpe_parser import CpeParser
from values.part import Part
from exceptions import CpeParsingException
from parser.validators import TechnicalValidator

logger = logging.getLogger(__name__)

def jaro_winkler_similarity(s1: str, s2: str) -> float:
    """Calculate Jaro-Winkler similarity between two strings (lowercase comparison)"""
    s1, s2 = s1.lower(), s2.lower()
    
    if s1 == s2:
        return 1.0
    
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0
    
    # Maximum allowed distance
    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0
    
    # Initialize match arrays
    s1_matches = [False] * len1
    s2_matches = [False] * len2
    
    matches = 0
    transpositions = 0
    
    # Find matches
    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = s2_matches[j] = True
            matches += 1
            break
    
    if matches == 0:
        return 0.0
    
    # Count transpositions
    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1
    
    # Calculate Jaro similarity
    jaro = (matches / len1 + matches / len2 + (matches - transpositions / 2) / matches) / 3.0
    
    # Calculate common prefix (up to 4 characters)
    prefix = 0
    for i in range(min(len1, len2, 4)):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break
    
    # Calculate Jaro-Winkler similarity
    return jaro + (0.1 * prefix * (1 - jaro))

class SystematicExtractor:
    @staticmethod
    def remove_version_from_title(title: str, version: str) -> str:
        """Remove version from title using comprehensive patterns"""
        if not title:
            return ""
        
        # If we have an explicit version, try to remove it first
        if version and version not in ["*", "-"]:
            # Escape special regex characters in version
            version_escaped = re.escape(version)
            # Try to remove the version with optional prefixes
            patterns = [
                rf'\s+v?{version_escaped}(?:\s|$)',
                rf'\s+{version_escaped}(?:\s|$)',
                rf'\s+version\s+{version_escaped}(?:\s|$)',
            ]
            
            for pattern in patterns:
                title = re.sub(pattern, ' ', title, flags=re.I)
        
        # Remove common version patterns
        version_patterns = [
            r'\s+v?\d+\.[\d\w\.\-\(\)]+(?:\s|$)',        # v1.2.3, 1.2.3.4, 12.0(31)SZ2
            r'\s+\d{4}v?[\d\.\-]+(?:\s|$)',              # 7400v2.02.01.2019
            r'\s+\d+\.\d+\(\d+\)[A-Z]+\d*(?:\s|$)',      # 12.0(31)SZ2
            r'\s+build\s+\d+(?:\s|$)',                    # build 123
            r'\s+(?:beta|alpha|rc)\s*\d*(?:\s|$)',        # beta, alpha, rc1
            r'\s+\d{4}(?:\.\d+)*(?:\s|$)',               # 2023, 2023.1
        ]
        
        for pattern in version_patterns:
            title = re.sub(pattern, ' ', title, flags=re.I)
        
        return re.sub(r'\s+', ' ', title).strip()
    
    @staticmethod
    def remove_cpe_components_from_title(title: str, update: str, edition: str, language: str, 
                                        sw_edition: str, target_sw: str, target_hw: str, other: str) -> str:
        """Remove CPE components from title when no version exists"""
        if not title:
            return ""
        
        components = [update, edition, language, sw_edition, target_sw, target_hw, other]
        valid_components = [comp.replace('_', ' ') for comp in components 
                           if comp and comp not in ['*', '-']]
        
        result_title = title
        for comp in valid_components:
            # Remove component with optional "for" prefix
            patterns = [
                rf'\s+for\s+{re.escape(comp)}(?:\s|$)',
                rf'\s+{re.escape(comp)}(?:\s|$)',
                rf'\s+on\s+{re.escape(comp)}(?:\s|$)',
            ]
            
            for pattern in patterns:
                result_title = re.sub(pattern, ' ', result_title, flags=re.I)
        
        return re.sub(r'\s+', ' ', result_title).strip()
    
    @staticmethod
    def get_most_common_left_correct(titles: List[str], versions: List[str], 
                                   updates: List[str], editions: List[str], languages: List[str],
                                   sw_editions: List[str], target_sws: List[str], 
                                   target_hws: List[str], others: List[str]) -> str:
        """Get most common left part by properly removing versions and components"""
        if not titles:
            return ""
        
        cleaned_titles = []
        
        for i, title in enumerate(titles):
            if not title:
                continue
                
            # Get corresponding components for this title
            version = versions[i] if i < len(versions) else ""
            update = updates[i] if i < len(updates) else "*"
            edition = editions[i] if i < len(editions) else "*"
            language = languages[i] if i < len(languages) else "*"
            sw_edition = sw_editions[i] if i < len(sw_editions) else "*"
            target_sw = target_sws[i] if i < len(target_sws) else "*"
            target_hw = target_hws[i] if i < len(target_hws) else "*"
            other = others[i] if i < len(others) else "*"
            
            # First remove version
            cleaned = SystematicExtractor.remove_version_from_title(title, version)
            
            # Then remove other CPE components
            cleaned = SystematicExtractor.remove_cpe_components_from_title(
                cleaned, update, edition, language, sw_edition, target_sw, target_hw, other
            )
            
            if cleaned:
                cleaned_titles.append(cleaned)
        
        if not cleaned_titles:
            return ""
        
        # Return most frequent cleaned title
        counter = Counter(cleaned_titles)
        return counter.most_common(1)[0][0]
    
    @staticmethod
    def split_vendor_product_systematic(most_common_left: str, vendor_machine: str, product_machine: str) -> Tuple[str, str]:
        """Split vendor and product using systematic methodology"""
        if not most_common_left:
            return vendor_machine.replace('_', ' ').replace('-', ' '), product_machine.replace('_', ' ').replace('-', ' ')
        
        # Handle vendor=product case
        if vendor_machine == product_machine:
            return most_common_left, most_common_left
        
        # Convert product machine to tokens
        product_tokens = product_machine.replace('_', ' ').replace('-', ' ').lower().split()
        if not product_tokens:
            # Fallback to first space split
            parts = most_common_left.split(' ', 1)
            return (parts[0], parts[1]) if len(parts) == 2 else (most_common_left, product_machine)
        
        # Find product start position (must be word boundary)
        text_lower = most_common_left.lower()
        first_token = product_tokens[0]
        
        # Find all positions where first product token starts at word boundary
        valid_positions = []
        start = 0
        while True:
            pos = text_lower.find(first_token, start)
            if pos == -1:
                break
            
            # Check if it's a word boundary (after space/start, before space/end)
            is_word_start = (pos == 0) or (not most_common_left[pos - 1].isalnum())
            end_pos = pos + len(first_token)
            is_word_end = (end_pos >= len(most_common_left)) or (not most_common_left[end_pos].isalnum())
            
            # Must not start at beginning and must be word boundary
            if pos > 0 and is_word_start and is_word_end:
                valid_positions.append(pos)
            
            start = pos + 1
        
        if not valid_positions:
            # No valid product position found, split at first space
            space_pos = most_common_left.find(' ')
            if space_pos > 0:
                return most_common_left[:space_pos], most_common_left[space_pos + 1:]
            else:
                return most_common_left, product_machine.replace('_', ' ').replace('-', ' ')
        
        # Score positions based on token overlap
        best_pos = valid_positions[0]
        best_score = 0
        
        for pos in valid_positions:
            product_part = most_common_left[pos:].strip()
            product_part_tokens = set(product_part.lower().split())
            machine_tokens = set(product_tokens)
            
            overlap = len(product_part_tokens & machine_tokens)
            if overlap > best_score:
                best_score = overlap
                best_pos = pos
        
        # Split at best position
        vendor_part = most_common_left[:best_pos].strip()
        product_part = most_common_left[best_pos:].strip()
        
        return vendor_part, product_part
    
    @staticmethod
    def validate_systematic(title: str, vendor_extracted: str, product_extracted: str,
                          vendor_machine: str, product_machine: str, 
                          version: str, update: str, edition: str, language: str,
                          sw_edition: str, target_sw: str, target_hw: str, other: str) -> Dict:
        """Validate extraction using systematic approach"""
        issues = []
        
        # Step 1: Reconstruct and validate against title
        reconstructed = f"{vendor_extracted} {product_extracted}".strip()
        
        # Clean the original title same way we did for extraction
        title_cleaned = SystematicExtractor.remove_version_from_title(title, version)
        title_cleaned = SystematicExtractor.remove_cpe_components_from_title(
            title_cleaned, update, edition, language, sw_edition, target_sw, target_hw, other
        )
        
        # Case-sensitive validation
        if not title_cleaned.startswith(reconstructed):
            # Also try with original title
            if not title.startswith(reconstructed):
                issues.append("Reconstruction fails to match title beginning")
        
        # Step 2: Character validation
        vendor_start_match = 0
        vendor_end_match = 0
        product_start_match = 0
        product_end_match = 0
        
        if vendor_extracted and vendor_machine:
            v_clean = re.sub(r'[^a-zA-Z0-9]', '', vendor_extracted.lower())
            vm_clean = re.sub(r'[^a-zA-Z0-9]', '', vendor_machine.lower())
            if v_clean and vm_clean:
                if v_clean[0] == vm_clean[0]:
                    vendor_start_match = 1
                if v_clean[-1] == vm_clean[-1]:
                    vendor_end_match = 1
        
        if product_extracted and product_machine:
            p_clean = re.sub(r'[^a-zA-Z0-9]', '', product_extracted.lower())
            pm_clean = re.sub(r'[^a-zA-Z0-9]', '', product_machine.lower())
            if p_clean and pm_clean:
                if p_clean[0] == pm_clean[0]:
                    product_start_match = 1
                if p_clean[-1] == pm_clean[-1]:
                    product_end_match = 1
        
        # Step 3: Similarity validation
        vendor_similarity = jaro_winkler_similarity(vendor_extracted or "", vendor_machine or "")
        product_similarity = jaro_winkler_similarity(product_extracted or "", product_machine or "")
        
        # Step 4: Overall validation
        char_score = vendor_start_match + vendor_end_match + product_start_match + product_end_match
        similarity_threshold = 0.7
        
        if vendor_similarity < similarity_threshold:
            issues.append(f"Low vendor similarity: {vendor_similarity:.3f}")
        if product_similarity < similarity_threshold:
            issues.append(f"Low product similarity: {product_similarity:.3f}")
        
        is_valid = (len(issues) <= 1 and char_score >= 2 and 
                   vendor_similarity >= similarity_threshold and 
                   product_similarity >= similarity_threshold)
        
        return {
            'is_valid': is_valid,
            'issues': issues,
            'vendor_start_match': vendor_start_match,
            'vendor_end_match': vendor_end_match,
            'product_start_match': product_start_match,
            'product_end_match': product_end_match,
            'vendor_similarity': round(vendor_similarity, 3),
            'product_similarity': round(product_similarity, 3),
            'char_alignment_score': char_score
        }

class OpenAIExtractor:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.openai.com/v1/chat/completions"
    
    async def extract_vendor_product_batch(self, items: List[Dict]) -> List[Dict]:
        if not items:
            return []
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        batch_input = []
        for idx, item in enumerate(items):
            batch_input.append({
                "id": item['cpe'],
                "group_identifier": f"{item['vendor_machine']}|{item['product_machine']}",
                "title": item['title'],
                "vendor_machine": item['vendor_machine'],
                "product_machine": item['product_machine'],
                "version": item.get('version', '*'),
                "most_common_left": item.get('most_common_left', ''),
                "group_size": item.get('group_size', 1),
                "sample_titles": item.get('sample_titles', [])
            })
        
        system_prompt = """You are a CPE expert implementing EXACT systematic methodology. Follow this PRECISE algorithm:

**ALGORITHM STEPS:**

STEP 1: UNDERSTAND THE GROUP
- group_identifier shows the exact (vendor_machine|product_machine) pattern
- All items in group share identical machine identifiers
- most_common_left is the correctly cleaned title (versions/components removed)

STEP 2: LOCATE PRODUCT START POSITION
- Find where product_machine tokens appear in most_common_left
- CRITICAL: Product must start AFTER a space (word boundary), NEVER at beginning
- Search case-insensitive but preserve original casing

STEP 3: SPLIT AT CORRECT POSITION
- Vendor = everything BEFORE product start position
- Product = everything FROM product start position onward
- Preserve exact casing from most_common_left

**CRITICAL EXAMPLES:**

Example 1:
- group_identifier: "dell|g5"  
- most_common_left: "Dell G5"
- Algorithm: Find "g5" → appears as "G5" starting at position 5 (after space)
- Result: vendor="Dell", product="G5"

Example 2:
- group_identifier: "mulesoft|apikit"
- most_common_left: "MuleSoft APIKit" 
- Algorithm: Find "apikit" → appears as "APIKit" starting at position 9 (after space)
- Result: vendor="MuleSoft", product="APIKit"

Example 3:
- group_identifier: "netapp|web_services"
- most_common_left: "NetApp E-series SANtricity Web Services"
- Algorithm: Find "web" → appears as "Web" starting at position 29 (after space)
- Result: vendor="NetApp E-series SANtricity", product="Web Services"

**SPECIAL CASES:**

Vendor=Product Case:
- group_identifier: "openimageio|openimageio"
- most_common_left: "OpenImageIO (OIIO)"
- Result: vendor="OpenImageIO (OIIO)", product="OpenImageIO (OIIO)" (identical)

**VALIDATION RULES:**
1. Product NEVER starts at position 0
2. Product MUST start after whitespace/punctuation  
3. Use first valid word-boundary match
4. Preserve exact casing from most_common_left
5. Handle compound words correctly (don't split mid-word)

**FAILURE HANDLING:**
If no valid product position found:
- Split at first space as fallback
- Ensure vendor gets left part, product gets right part

**OUTPUT FORMAT:**
```json
[
  {"id": "<cpe>", "vendor_name": "<vendor>", "product_name": "<product>"}
]
```

**CRITICAL RULE:** The most_common_left is already properly cleaned. Simply find the product position and split there."""

        user_content = f"Apply the systematic algorithm to extract vendor and product from these groups:\n\n{json.dumps(batch_input, indent=2)}"
        
        payload = {
            "model": "gpt-5",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": 2000,
            "temperature": 0.0
        }
        
        try:
            def make_request():
                response = requests.post(self.base_url, headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                return response.json()
            
            result = await asyncio.to_thread(make_request)
            content = result["choices"][0]["message"]["content"]
            
            if content.startswith('```json'):
                content = content[7:-3]
            elif content.startswith('```'):
                content = content[3:-3]
            
            extracted_data = json.loads(content)
            
            results = []
            cpe_to_index = {item['cpe']: idx for idx, item in enumerate(batch_input)}
            
            for item in extracted_data:
                if isinstance(item, dict) and 'id' in item:
                    cpe_id = item['id']
                    if cpe_id in cpe_to_index:
                        results.append({
                            'vendor_name': item.get('vendor_name', '').strip(),
                            'product_name': item.get('product_name', '').strip()
                        })
                    else:
                        results.append({'vendor_name': '', 'product_name': ''})
                else:
                    results.append({'vendor_name': '', 'product_name': ''})
            
            while len(results) < len(items):
                results.append({'vendor_name': '', 'product_name': ''})
            
            return results[:len(items)]
            
        except Exception as e:
            logger.error(f"OpenAI batch extraction failed: {e}")
            return [{'vendor_name': '', 'product_name': ''} for _ in items]

class UnifiedCpeProcessor:
    def __init__(self, xml_file_path: str, sample_percentage: float = 0.01):
        self.xml_file_path = xml_file_path
        self.sample_percentage = sample_percentage
        self.namespaces = {
            "cpe": "http://cpe.mitre.org/dictionary/2.0",
            "cpe-23": "http://scap.nist.gov/schema/cpe-extension/2.3"
        }
        self.extractor = SystematicExtractor()
        
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            self.openai_extractor = OpenAIExtractor(openai_api_key)
        else:
            self.openai_extractor = None
            logger.warning("OpenAI API key not found, using systematic fallback")
    
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
    
    async def extract_with_openai(self, items: List[Dict]) -> List[Dict]:
        if not self.openai_extractor:
            return []
        
        try:
            return await self.openai_extractor.extract_vendor_product_batch(items)
        except Exception as e:
            logger.error(f"OpenAI extraction failed: {e}")
            return []
    
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
        
        # Group by (vendor_machine, product_machine)
        groups = defaultdict(list)
        for item in raw_items:
            key = (item['vendor_machine'], item['product_machine'])
            groups[key].append(item)
        
        logger.info(f"Created {len(groups)} unique identifier groups")
        
        final_items = []
        batch_size = 50
        group_items = list(groups.items())
        
        for i in range(0, len(group_items), batch_size):
            batch_groups = group_items[i:i + batch_size]
            batch_items_for_ai = []
            batch_metadata = []
            
            for (vendor_machine, product_machine), items in batch_groups:
                # Extract data for systematic processing
                titles = [item['title'] for item in items if item['title']]
                versions = [item['version'] for item in items]
                updates = [item['update'] for item in items]
                editions = [item['edition'] for item in items]
                languages = [item['language'] for item in items]
                sw_editions = [item['sw_edition'] for item in items]
                target_sws = [item['target_sw'] for item in items]
                target_hws = [item['target_hw'] for item in items]
                others = [item['other'] for item in items]
                
                # Get CORRECT most common left using systematic approach
                most_common_left = self.extractor.get_most_common_left_correct(
                    titles, versions, updates, editions, languages,
                    sw_editions, target_sws, target_hws, others
                )
                
                representative = items[0]
                
                batch_item = {
                    'cpe': representative['cpe'],
                    'title': titles[0] if titles else "",
                    'vendor_machine': vendor_machine,
                    'product_machine': product_machine,
                    'version': representative['version'],
                    'most_common_left': most_common_left,
                    'group_size': len(items),
                    'sample_titles': titles[:3]  # Sample for AI context
                }
                
                batch_items_for_ai.append(batch_item)
                batch_metadata.append({
                    'items': items,
                    'titles': titles,
                    'vendor_machine': vendor_machine,
                    'product_machine': product_machine,
                    'group_size': len(items),
                    'most_common_left': most_common_left,
                    'representative': representative,
                    'group_identifier': f"{vendor_machine}|{product_machine}"
                })
            
            if batch_items_for_ai:
                logger.info(f"Processing batch {i//batch_size + 1}/{(len(group_items) + batch_size - 1)//batch_size} with {len(batch_items_for_ai)} groups")
                
                # Try OpenAI first
                extraction_results = asyncio.run(self.extract_with_openai(batch_items_for_ai))
                
                for idx, metadata in enumerate(batch_metadata):
                    # Use OpenAI result if available and valid
                    if (idx < len(extraction_results) and 
                        extraction_results[idx] and 
                        extraction_results[idx]['vendor_name'] and 
                        extraction_results[idx]['product_name']):
                        vendor_human = extraction_results[idx]['vendor_name']
                        product_human = extraction_results[idx]['product_name']
                    else:
                        # Use systematic fallback
                        vendor_human, product_human = self.extractor.split_vendor_product_systematic(
                            metadata['most_common_left'], 
                            metadata['vendor_machine'], 
                            metadata['product_machine']
                        )
                    
                    # Perform systematic validation
                    rep = metadata['representative']
                    validation = self.extractor.validate_systematic(
                        metadata['titles'][0] if metadata['titles'] else "",
                        vendor_human, product_human,
                        metadata['vendor_machine'], metadata['product_machine'],
                        rep['version'], rep['update'], rep['edition'], rep['language'],
                        rep['sw_edition'], rep['target_sw'], rep['target_hw'], rep['other']
                    )
                    
                    # Collect all data from group
                    all_cpes = [item['cpe'] for item in metadata['items']]
                    all_versions = list(set(item['version'] for item in metadata['items'] if item['version'] != "-"))
                    all_references = []
                    for item in metadata['items']:
                        all_references.extend(item.get('references', []))
                    
                    final_item = {
                        "cpe": " | ".join(all_cpes),
                        "Title": metadata['titles'][0] if metadata['titles'] else "",
                        "vendor_human": vendor_human,
                        "product_human": product_human,
                        "Validation Product Name": validation['is_valid'],
                        "part": rep['part'].get_abbreviation(),
                        "target_softwares": [rep['target_sw']] if rep['target_sw'] != "*" else ["*"],
                        "target_hardwares": [rep['target_hw']] if rep['target_hw'] != "*" else ["*"],
                        "versions": all_versions if all_versions else ["-"],
                        "updates": [rep['update']] if rep['update'] != "*" else ["*"],
                        "editions": [rep['edition']] if rep['edition'] != "*" else ["*"],
                        "languages": [rep['language']] if rep['language'] != "*" else ["*"],
                        "references": list(set(all_references)),
                        "category": self.get_corrected_category(rep['part'], metadata['product_machine'], metadata['titles'][0] if metadata['titles'] else ""),
                        "Part_Type": rep['part'].get_abbreviation(),
                        "Vendor_Machine": metadata['vendor_machine'],
                        "Product_Machine": metadata['product_machine'],
                        "Group_Identifier": metadata['group_identifier'],
                        "Validation_Vendor_Start": validation['vendor_start_match'],
                        "Validation_Vendor_End": validation['vendor_end_match'],
                        "Validation_Product_Start": validation['product_start_match'],
                        "Validation_Product_End": validation['product_end_match'],
                        "Validation_Title_Full": metadata['titles'][0] if metadata['titles'] else "",
                        "Validation_Vendor": vendor_human,
                        "Validation_Product": product_human,
                        "Validation_Final": validation['is_valid'],
                        "Group_Size": metadata['group_size'],
                        "Vendor_Similarity": validation['vendor_similarity'],
                        "Product_Similarity": validation['product_similarity'],
                        "Most_Common_Left": metadata['most_common_left'],
                        "Validation_Issues": "; ".join(validation['issues'])
                    }
                    
                    final_items.append(final_item)
        
        logger.info(f"Successfully processed {len(final_items)} final items from {len(groups)} groups")
        return final_items
    
    def parse_single_item(self, cpe_item: ET.Element) -> Optional[Dict]:
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
        if part == Part.APPLICATION:
            return "Application"
        elif part == Part.OPERATING_SYSTEM:
            return "Operating System"
        elif part == Part.HARDWARE_DEVICE:
            return "Hardware"
        else:
            return "Unknown"
    
    def get_corrected_category(self, part: Part, product_machine: str, title: str) -> str:
        base_category = self.get_category_from_part(part)
        
        if part == Part.OPERATING_SYSTEM and self.should_be_hardware_firmware(product_machine, title):
            return "Hardware/Firmware"
        
        return base_category
    
    def should_be_hardware_firmware(self, product_machine: str, title: str) -> bool:
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
        logger.info(f"Creating Excel file: {output_file}")
        columns = [
            "cpe", "Title", "vendor_human", "product_human", "Validation Product Name",
            "part", "target_softwares", "target_hardwares", "versions", "updates",
            "editions", "languages", "references", "category", "Part_Type", 
            "Vendor_Machine", "Product_Machine", "Group_Identifier", 
            "Validation_Vendor_Start", "Validation_Vendor_End", 
            "Validation_Product_Start", "Validation_Product_End",
            "Validation_Title_Full", "Validation_Vendor", "Validation_Product", 
            "Validation_Final", "Group_Size", "Vendor_Similarity", "Product_Similarity", 
            "Most_Common_Left", "Validation_Issues"
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
    
    def run(self, output_file: str):
        logger.info("Starting unified CPE processing")
        if not Path(self.xml_file_path).exists():
            raise FileNotFoundError(f"XML file not found: {self.xml_file_path}")
        
        cpe_data = self.parse_xml_file()
        if not cpe_data:
            logger.error("No valid CPE data found")
            return
        
        self.create_excel_file(cpe_data, output_file)
        logger.info("CPE processing completed successfully")