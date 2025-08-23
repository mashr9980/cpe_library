import os
import xml.etree.ElementTree as ET
import pandas as pd
import logging
import random
import asyncio
import json
import requests
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from collections import defaultdict

from processor.cpe import Cpe
from processor.cpe_parser import CpeParser
from values.part import Part
from exceptions import CpeParsingException
from parser.validators import TechnicalValidator

logger = logging.getLogger(__name__)

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
                "id": idx,
                "cpe": item['cpe'],
                "title": item['title'],
                "vendor_machine": item['vendor_machine'],
                "product_machine": item['product_machine'],
                "part": item['part'].get_abbreviation()
            })
        
        system_prompt = """You are a CPE expert processing 1.4M+ records. Extract vendor/product names with STRICT machine identifier alignment and consistent suffix handling.

MACHINE IDENTIFIER ALIGNMENT (CRITICAL):
1. VENDOR ALIGNMENT:
   - "fork-cms" → "Fork CMS" (not "Fork") - align with full machine name
   - "vektor-inc" → "Vektor Inc" (not "Vektor") - preserve suffix for alignment  
   - "rsvpmaker_project" → "RSVPMaker Project" (not "RSVPMaker") - keep project suffix
   - "better-auth" → "Better Auth" - direct mapping
   - "auto_delete_posts_project" → "Auto Delete Posts Project" - keep all parts

2. PRODUCT ALIGNMENT:
   - "forkcms" → "Fork CMS" (matches vendor pattern)
   - "vk_block_patterns" → "VK Block Patterns" 
   - "better_auth" → "Better Auth"
   - "pachno" → "Pachno" (simple direct mapping, no additions)

CONSISTENT SUFFIX RULES:
- Keep ALL suffixes in machine identifiers: Project, Inc, Foundation, Corp, Ltd
- Only remove if suffix appears EXTRA in title beyond machine identifier
- "Microsoft Corporation" + machine="microsoft" → "Microsoft" (remove extra)
- "RSVPMaker Project" + machine="rsvpmaker_project" → "RSVPMaker Project" (keep for alignment)

VENDOR=PRODUCT RESOLUTION:
When vendor and product would be identical:
1. Check if machine identifiers are different
2. If different machines, map each to its machine exactly
3. If same machines, use base name for vendor, add minimal qualifier for product:
   - "pachno"/"pachno" → "Pachno"/"Pachno" (keep same if machines identical)
   - Never add words not in machine identifiers

CRITICAL VALIDATION ALIGNMENT:
- First character: vendor_human[0].lower() == vendor_machine[0].lower()
- Last character: vendor_human[-1].lower() == vendor_machine[-1].lower() 
- Same rules for product alignment
- Semantic token overlap ≥70%

TITLE PROCESSING:
1. Remove versions: \d+\.\d+(\.\d+)*, "Update \d+", "Beta \d+", build numbers
2. Remove platforms: "for WordPress", "for Node.js", etc.
3. Remove editions: Pro, Enterprise, Premium (unless in machine identifier)
4. Keep year identifiers if in machine: "Visual Studio 2022", "Office 365"

EXAMPLES:
- Title: "Fork CMS 5.8.1", Machines: "fork-cms"/"forkcms" → "Fork CMS"/"Fork CMS"
- Title: "Vektor, Inc. VK Block Patterns 1.4.1", Machines: "vektor-inc"/"vk_block_patterns" → "Vektor Inc"/"VK Block Patterns"  
- Title: "Better Auth 0.5.3 Beta 8", Machines: "better-auth"/"better_auth" → "Better Auth"/"Better Auth"
- Title: "Pachno Pachno 1.0.2", Machines: "pachno"/"pachno" → "Pachno"/"Pachno"

OUTPUT: JSON array [{"id": int, "vendor_name": "string", "product_name": "string"}]
ENSURE: Perfect character alignment with machine identifiers for validation success."""

        user_content = f"Extract vendor and product names from these CPE entries:\n\n{json.dumps(batch_input, indent=2)}"
        
        payload = {
            "model": "gpt-5",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": 2000,
            "temperature": 0.1
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
            for item in extracted_data:
                if item['id'] < len(items):
                    results.append({
                        'vendor_name': item.get('vendor_name', '').strip(),
                        'product_name': item.get('product_name', '').strip()
                    })
                else:
                    results.append({'vendor_name': '', 'product_name': ''})
            
            return results
            
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
        
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            self.openai_extractor = OpenAIExtractor(openai_api_key)
        else:
            self.openai_extractor = None
            logger.warning("OpenAI API key not found, extraction disabled")
    
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
        
        # Enhanced grouping with similarity detection
        grouped = defaultdict(list)
        group_stats = defaultdict(int)
        
        for item in raw_items:
            # Primary grouping key
            primary_key = (item['vendor_machine'], item['product_machine'], item['part'].get_abbreviation())
            grouped[primary_key].append(item)
            group_stats[primary_key] += 1
        
        logger.info(f"Created {len(grouped)} unique groups from raw items")
        
        # Log grouping statistics
        large_groups = {k: v for k, v in group_stats.items() if v > 1}
        if large_groups:
            logger.info(f"Groups with multiple items: {len(large_groups)}")
            for (vendor, product, part), count in sorted(large_groups.items(), key=lambda x: x[1], reverse=True)[:5]:
                logger.info(f"  {vendor}/{product} ({part}): {count} items")
        
        # Process groups in batches for efficiency
        final_items = []
        batch_size = 50  # Process 50 groups at a time for OpenAI
        group_items = list(grouped.items())
        
        for i in range(0, len(group_items), batch_size):
            batch_groups = group_items[i:i + batch_size]
            batch_items_for_ai = []
            batch_metadata = []
            
            for (vendor_machine, product_machine, part_str), items in batch_groups:
                representative = items[0]
                
                # Select best title from group
                titles = [item['title'] for item in items if item['title']]
                best_title = self.select_best_title_advanced(titles, vendor_machine, product_machine)
                
                # Aggregate data from all items in group
                all_cpes = [item['cpe'] for item in items]
                all_versions = list(set(item['version'] for item in items if item['version'] != "-"))
                all_references = []
                for item in items:
                    all_references.extend(item.get('references', []))
                
                batch_item = {
                    'cpe': representative['cpe'],
                    'title': best_title,
                    'vendor_machine': vendor_machine,
                    'product_machine': product_machine,
                    'part': representative['part']
                }
                
                batch_items_for_ai.append(batch_item)
                batch_metadata.append({
                    'items': items,
                    'all_cpes': all_cpes,
                    'all_versions': all_versions,
                    'all_references': all_references,
                    'representative': representative,
                    'best_title': best_title,
                    'part_str': part_str,
                    'vendor_machine': vendor_machine,
                    'product_machine': product_machine,
                    'group_size': len(items)
                })
            
            # Process batch with OpenAI
            if batch_items_for_ai:
                logger.info(f"Processing batch {i//batch_size + 1}/{(len(group_items) + batch_size - 1)//batch_size} with {len(batch_items_for_ai)} groups")
                extraction_results = asyncio.run(self.extract_with_openai(batch_items_for_ai))
                
                # Create final items from batch results
                for idx, metadata in enumerate(batch_metadata):
                    if idx < len(extraction_results) and extraction_results[idx]:
                        vendor_human = extraction_results[idx]['vendor_name'] or self.fallback_vendor_aligned(metadata['vendor_machine'])
                        product_human = extraction_results[idx]['product_name'] or self.fallback_product_aligned(metadata['product_machine'])
                    else:
                        vendor_human = self.fallback_vendor_aligned(metadata['vendor_machine'])
                        product_human = self.fallback_product_aligned(metadata['product_machine'])
                    
                    # Enhanced validation with machine alignment
                    validation = self.validate_extraction_enhanced(
                        vendor_human, metadata['vendor_machine'], 
                        product_human, metadata['product_machine'],
                        metadata['representative']['version'], 
                        metadata['representative']['target_sw'], 
                        metadata['best_title']
                    )
                    
                    final_item = {
                        "cpe": " | ".join(metadata['all_cpes']),
                        "Title": metadata['best_title'],
                        "vendor_human": vendor_human,
                        "product_human": product_human,
                        "Validation Product Name": validation['is_valid'],
                        "part": metadata['part_str'],
                        "target_softwares": [metadata['representative']['target_sw']] if metadata['representative']['target_sw'] != "*" else ["*"],
                        "target_hardwares": [metadata['representative']['target_hw']] if metadata['representative']['target_hw'] != "*" else ["*"],
                        "versions": metadata['all_versions'] if metadata['all_versions'] else ["-"],
                        "updates": [metadata['representative']['update']] if metadata['representative']['update'] != "*" else ["*"],
                        "editions": [metadata['representative']['edition']] if metadata['representative']['edition'] != "*" else ["*"],
                        "languages": [metadata['representative']['language']] if metadata['representative']['language'] != "*" else ["*"],
                        "references": list(set(metadata['all_references'])),
                        "category": self.get_corrected_category(metadata['representative']['part'], metadata['product_machine'], metadata['best_title']),
                        "Part_Type": metadata['part_str'],
                        "Vendor_Machine": metadata['vendor_machine'],
                        "Product_Machine": metadata['product_machine'],
                        "Validation_Vendor_Start": validation['vendor_start_match'],
                        "Validation_Vendor_End": validation['vendor_end_match'],
                        "Validation_Product_Start": validation['product_start_match'],
                        "Validation_Product_End": validation['product_end_match'],
                        "Validation_Title_Full": metadata['best_title'],
                        "Validation_Vendor": vendor_human,
                        "Validation_Product": product_human,
                        "Validation_Final": validation['is_valid'],
                        "Group_Size": metadata['group_size']
                    }
                    
                    final_items.append(final_item)
        
        logger.info(f"Successfully processed {len(final_items)} final items from {len(grouped)} groups")
        return final_items
    
    def select_best_title_advanced(self, titles: List[str], vendor_machine: str, product_machine: str) -> str:
        if not titles:
            return ""
        if len(titles) == 1:
            return titles[0]
        
        scored_titles = []
        vendor_tokens = set(vendor_machine.lower().replace('_', ' ').replace('-', ' ').split())
        product_tokens = set(product_machine.lower().replace('_', ' ').replace('-', ' ').split())
        
        for title in titles:
            score = 0
            title_lower = title.lower()
            
            # Prefer titles with proper capitalization
            if any(char.isupper() for char in title):
                score += 3
            
            # Prefer longer, more descriptive titles
            if len(title.split()) > 3:
                score += 2
            
            # Prefer titles containing vendor tokens
            vendor_overlap = len(vendor_tokens.intersection(set(title_lower.split())))
            score += vendor_overlap * 2
            
            # Prefer titles containing product tokens  
            product_overlap = len(product_tokens.intersection(set(title_lower.split())))
            score += product_overlap * 2
            
            # Prefer titles with version information (shows completeness)
            if any(char.isdigit() and '.' in title for char in title):
                score += 1
            
            scored_titles.append((title, score))
        
        return max(scored_titles, key=lambda x: x[1])[0]
    
    def fallback_vendor_aligned(self, vendor_machine: str) -> str:
        """Create vendor name that aligns with machine identifier for validation"""
        if not vendor_machine:
            return "Unknown"
        
        # Handle compound machine names
        if '-' in vendor_machine or '_' in vendor_machine:
            parts = vendor_machine.replace('-', ' ').replace('_', ' ').split()
            vendor = ' '.join(word.capitalize() for word in parts)
        else:
            vendor = vendor_machine.capitalize()
        
        # Don't remove suffixes - keep for alignment
        return vendor
    
    def fallback_product_aligned(self, product_machine: str) -> str:
        """Create product name that aligns with machine identifier for validation"""
        if not product_machine:
            return "Unknown"
        
        # Handle compound machine names
        if '-' in product_machine or '_' in product_machine:
            parts = product_machine.replace('-', ' ').replace('_', ' ').split()
            product = ' '.join(word.capitalize() for word in parts)
        else:
            product = product_machine.capitalize()
        
        return product
    
    def validate_extraction_enhanced(self, vendor_human: str, vendor_machine: str, 
                                   product_human: str, product_machine: str,
                                   version: str, target_sw: str, title: str) -> Dict:
        """Enhanced validation with strict character alignment"""
        issues = []
        
        # Character alignment validation
        vendor_start_match = 0
        vendor_end_match = 0
        product_start_match = 0
        product_end_match = 0
        
        if vendor_human and vendor_machine:
            if vendor_human[0].lower() == vendor_machine[0].lower():
                vendor_start_match = 1
            if vendor_human[-1].lower() == vendor_machine[-1].lower():
                vendor_end_match = 1
        
        if product_human and product_machine:
            if product_human[0].lower() == product_machine[0].lower():
                product_start_match = 1
            if product_human[-1].lower() == product_machine[-1].lower():
                product_end_match = 1
        
        # Semantic validation
        if not vendor_human or not product_human:
            issues.append("Missing vendor or product")
        
        # Token overlap validation
        if vendor_human and vendor_machine:
            vendor_tokens = set(vendor_human.lower().replace('-', ' ').split())
            machine_vendor_tokens = set(vendor_machine.lower().replace('-', ' ').replace('_', ' ').split())
            vendor_overlap = len(vendor_tokens & machine_vendor_tokens) / max(len(vendor_tokens), len(machine_vendor_tokens)) if vendor_tokens else 0
            if vendor_overlap < 0.5:
                issues.append("Low vendor token overlap")
        
        if product_human and product_machine:
            product_tokens = set(product_human.lower().replace('-', ' ').split())
            machine_product_tokens = set(product_machine.lower().replace('-', ' ').replace('_', ' ').split())
            product_overlap = len(product_tokens & machine_product_tokens) / max(len(product_tokens), len(machine_product_tokens)) if product_tokens else 0
            if product_overlap < 0.5:
                issues.append("Low product token overlap")
        
        # Overall validation
        character_alignment_score = vendor_start_match + vendor_end_match + product_start_match + product_end_match
        is_valid = len(issues) <= 1 and character_alignment_score >= 2
        
        return {
            'is_valid': is_valid,
            'issues': issues,
            'vendor_start_match': vendor_start_match,
            'vendor_end_match': vendor_end_match,
            'product_start_match': product_start_match,
            'product_end_match': product_end_match,
            'character_alignment_score': character_alignment_score
        }
    
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
                "target_sw": parsed_cpe.get_target_sw(),
                "target_hw": parsed_cpe.get_target_hw(),
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
            "Vendor_Machine", "Product_Machine", "Validation_Vendor_Start", 
            "Validation_Vendor_End", "Validation_Product_Start", "Validation_Product_End",
            "Validation_Title_Full", "Validation_Vendor", "Validation_Product", "Validation_Final"
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