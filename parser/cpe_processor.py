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

logger = logging.getLogger(__name__)

class IntelligentOpenAIProcessor:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.openai.com/v1/chat/completions"
    
    async def process_title_batch(self, items: List[Dict]) -> List[Dict]:
        if not items:
            return []
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        batch_data = []
        for idx, item in enumerate(items):
            batch_data.append({
                "id": idx,
                "title": item.get('title', ''),
                "vendor_machine": item.get('vendor_machine', ''),
                "product_machine": item.get('product_machine', ''),
                "version": item.get('version', '*'),
                "update": item.get('update', '*'),
                "edition": item.get('edition', '*'),
                "language": item.get('language', '*'),
                "sw_edition": item.get('sw_edition', '*'),
                "target_sw": item.get('target_sw', '*'),
                "target_hw": item.get('target_hw', '*'),
                "other": item.get('other', '*'),
                "all_titles": item.get('all_titles', []),
                "all_versions": item.get('all_versions', [])
            })
        
        system_prompt = """You are an expert CPE (Common Platform Enumeration) processor handling 1.4M+ records. Your task is to intelligently extract clean vendor and product names from software/hardware titles.

**CORE OBJECTIVE:**
Extract human-readable vendor and product names that reconstruct perfectly back to a cleaned title.

**KEY PRINCIPLES:**

1. **INTELLIGENT TITLE CLEANING**
   - Remove version numbers, build numbers, release candidates, betas, alphas
   - Remove platform/target info (for Windows, for Android, etc.)
   - Remove edition info (Enterprise, Pro, Free, etc.) unless core to product identity
   - Remove extra descriptive text while preserving essential product identity
   - Result should be: "[Vendor] [Product]" format

2. **SMART VENDOR-PRODUCT SPLITTING**
   - Use vendor_machine and product_machine as intelligent hints for boundaries
   - Handle complex patterns: "[Company] Project [Product]", "[Org] [Long Product Name]"
   - Preserve complete company names: "Apache Software Foundation", "Red Hat"
   - Handle parenthetical info intelligently: "Company (Details)" vs "Product (Feature)"

3. **MACHINE IDENTIFIER ALIGNMENT**
   - Ensure first/last characters align between human names and machine identifiers
   - vendor_human[0].lower() == vendor_machine[0], vendor_human[-1].lower() == vendor_machine[-1]  
   - Same alignment rules for product names
   - Handle special characters by ignoring them for alignment (spaces, hyphens, underscores)

4. **CONTEXT-AWARE DECISIONS**
   - Use all_titles array to understand patterns across related entries
   - Use all_versions to distinguish between version info and product names
   - When vendor_machine == product_machine, both extractions should typically be identical
   - Consider target platforms and editions as context, not core identity

5. **QUALITY VALIDATION**
   - Reconstructed "[vendor_human] [product_human]" should make logical sense
   - Names should sound natural and professional
   - Avoid awkward splits that create meaningless vendor or product names

**INPUT UNDERSTANDING:**
- title: Original full title from CPE database
- vendor_machine: Machine-readable vendor identifier (hints for vendor boundary)
- product_machine: Machine-readable product identifier (hints for product boundary)  
- version, update, edition, etc.: CPE component data for context
- all_titles: Related titles in same group for pattern recognition
- all_versions: Version variations to help distinguish version vs product info

**OUTPUT REQUIREMENTS:**
```json
[
  {
    "id": 0,
    "cleaned_title": "Vendor Product",
    "vendor_human": "Vendor",
    "product_human": "Product",
    "confidence": 0.95,
    "reasoning": "Brief explanation of extraction logic"
  }
]
```

**EXAMPLES:**

Input: "Apache Software Foundation Zookeeper 3.0.1"
- vendor_machine: "apache", product_machine: "zookeeper"
- Output: cleaned_title: "Apache Software Foundation Zookeeper", vendor_human: "Apache Software Foundation", product_human: "Zookeeper"

Input: "Squeeze Project Squeeze for WordPress" 
- vendor_machine: "squeeze_project", product_machine: "squeeze"
- Output: cleaned_title: "Squeeze Project Squeeze", vendor_human: "Squeeze Project", product_human: "Squeeze"

Input: "Microsoft Visual Studio 2017 15.9.20"
- vendor_machine: "microsoft", product_machine: "visual_studio_2017"  
- Output: cleaned_title: "Microsoft Visual Studio 2017", vendor_human: "Microsoft", product_human: "Visual Studio 2017"

**CRITICAL SUCCESS METRICS:**
1. Character alignment between human and machine identifiers
2. Perfect reconstruction: cleaned_title == vendor_human + " " + product_human
3. Natural, professional-sounding names
4. Consistent handling of similar patterns across the dataset

Be intelligent, contextual, and precise. Handle edge cases gracefully."""

        user_content = f"Process these CPE entries and extract clean vendor/product names:\n\n{json.dumps(batch_data, indent=2)}"
        
        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": 4000,
            "temperature": 0.1
        }
        
        try:
            def make_request():
                response = requests.post(self.base_url, headers=headers, json=payload, timeout=180)
                response.raise_for_status()
                return response.json()
            
            result = await asyncio.to_thread(make_request)
            content = result["choices"][0]["message"]["content"]
            
            if not content or not content.strip():
                logger.warning("OpenAI returned empty response")
                return [{'vendor_human': '', 'product_human': '', 'cleaned_title': ''} for _ in items]
            
            content = content.strip()
            if content.startswith('```json'):
                content = content[7:]
            if content.startswith('```'):
                content = content[3:]  
            if content.endswith('```'):
                content = content[:-3]
            content = content.strip()
            
            if not content:
                logger.warning("OpenAI response was only markdown")
                return [{'vendor_human': '', 'product_human': '', 'cleaned_title': ''} for _ in items]
            
            try:
                extracted_data = json.loads(content)
            except json.JSONDecodeError as e:
                logger.warning(f"OpenAI returned invalid JSON: {str(e)[:200]}")
                return [{'vendor_human': '', 'product_human': '', 'cleaned_title': ''} for _ in items]
            
            if not isinstance(extracted_data, list):
                logger.warning("OpenAI response is not a list")
                return [{'vendor_human': '', 'product_human': '', 'cleaned_title': ''} for _ in items]
            
            results = []
            for i in range(len(items)):
                found_result = None
                for item in extracted_data:
                    if isinstance(item, dict) and item.get('id') == i:
                        found_result = {
                            'vendor_human': item.get('vendor_human', '').strip(),
                            'product_human': item.get('product_human', '').strip(),
                            'cleaned_title': item.get('cleaned_title', '').strip(),
                            'confidence': item.get('confidence', 0.0),
                            'reasoning': item.get('reasoning', '')
                        }
                        break
                
                if not found_result:
                    results.append({
                        'vendor_human': '', 
                        'product_human': '', 
                        'cleaned_title': '',
                        'confidence': 0.0,
                        'reasoning': 'No result found'
                    })
                else:
                    results.append(found_result)
            
            return results
            
        except Exception as e:
            logger.error(f"OpenAI processing failed: {e}")
            return [{'vendor_human': '', 'product_human': '', 'cleaned_title': '', 'confidence': 0.0, 'reasoning': 'API error'} for _ in items]

class UnifiedCpeProcessor:
    def __init__(self, xml_file_path: str, sample_percentage: float = 0.01):
        self.xml_file_path = xml_file_path
        self.sample_percentage = sample_percentage
        self.namespaces = {
            "cpe": "http://cpe.mitre.org/dictionary/2.0",
            "cpe-23": "http://scap.nist.gov/schema/cpe-extension/2.3"
        }
        
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        
        self.intelligent_processor = IntelligentOpenAIProcessor(openai_api_key)
        logger.info("Initialized with intelligent OpenAI processor")
    
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
        
        groups = defaultdict(list)
        for item in raw_items:
            key = (item['vendor_machine'], item['product_machine'])
            groups[key].append(item)
        
        logger.info(f"Created {len(groups)} unique identifier groups")
        
        final_items = []
        batch_size = 25
        group_items = list(groups.items())
        
        for i in range(0, len(group_items), batch_size):
            batch_groups = group_items[i:i + batch_size]
            batch_items_for_ai = []
            batch_metadata = []
            
            for (vendor_machine, product_machine), items in batch_groups:
                titles = [item['title'] for item in items if item['title']]
                versions = list(set(item['version'] for item in items if item['version'] != '-'))
                
                representative = items[0]
                
                batch_item = {
                    'title': titles[0] if titles else "",
                    'vendor_machine': vendor_machine,
                    'product_machine': product_machine,
                    'version': representative['version'],
                    'update': representative['update'],
                    'edition': representative['edition'],
                    'language': representative['language'],
                    'sw_edition': representative['sw_edition'],
                    'target_sw': representative['target_sw'],
                    'target_hw': representative['target_hw'],
                    'other': representative['other'],
                    'all_titles': titles[:5],
                    'all_versions': versions[:5]
                }
                
                batch_items_for_ai.append(batch_item)
                batch_metadata.append({
                    'items': items,
                    'vendor_machine': vendor_machine,
                    'product_machine': product_machine,
                    'group_identifier': f"{vendor_machine}|{product_machine}",
                    'representative': representative
                })
            
            if batch_items_for_ai:
                logger.info(f"Processing batch {i//batch_size + 1}/{(len(group_items) + batch_size - 1)//batch_size} with {len(batch_items_for_ai)} groups")
                
                extraction_results = asyncio.run(self.intelligent_processor.process_title_batch(batch_items_for_ai))
                
                for idx, metadata in enumerate(batch_metadata):
                    if (idx < len(extraction_results) and extraction_results[idx] and 
                        extraction_results[idx]['vendor_human'] and extraction_results[idx]['product_human']):
                        
                        result = extraction_results[idx]
                        vendor_human = result['vendor_human']
                        product_human = result['product_human']
                        cleaned_title = result['cleaned_title']
                        confidence = result['confidence']
                        reasoning = result['reasoning']
                        
                        validation = self.validate_extraction(
                            vendor_human, product_human, cleaned_title,
                            metadata['vendor_machine'], metadata['product_machine']
                        )
                        
                        logger.info(f"Processed group {metadata['group_identifier']}: {vendor_human} | {product_human} (confidence: {confidence:.2f}, valid: {validation['is_valid']})")
                        
                    else:
                        vendor_human = metadata['vendor_machine'].replace('_', ' ').title()
                        product_human = metadata['product_machine'].replace('_', ' ').title()
                        cleaned_title = f"{vendor_human} {product_human}"
                        confidence = 0.0
                        reasoning = "Fallback due to AI processing failure"
                        validation = {'is_valid': False, 'issues': ['AI processing failed']}
                        logger.warning(f"AI processing failed for group {metadata['group_identifier']}, using fallback")
                    
                    all_cpes = [item['cpe'] for item in metadata['items']]
                    all_versions = list(set(item['version'] for item in metadata['items'] if item['version'] != "-"))
                    all_references = []
                    for item in metadata['items']:
                        all_references.extend(item.get('references', []))
                    
                    rep = metadata['representative']
                    
                    final_item = {
                        "cpe": " | ".join(all_cpes),
                        "Title": batch_items_for_ai[idx]['title'] if idx < len(batch_items_for_ai) else "",
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
                        "category": self.get_corrected_category(rep['part'], metadata['product_machine'], batch_items_for_ai[idx]['title'] if idx < len(batch_items_for_ai) else ""),
                        "Part_Type": rep['part'].get_abbreviation(),
                        "Vendor_Machine": metadata['vendor_machine'],
                        "Product_Machine": metadata['product_machine'],
                        "Group_Identifier": metadata['group_identifier'],
                        "AI_Confidence": confidence,
                        "AI_Reasoning": reasoning,
                        "Cleaned_Title": cleaned_title,
                        "Validation_Issues": "; ".join(validation['issues'])
                    }
                    
                    final_items.append(final_item)
        
        logger.info(f"Successfully processed {len(final_items)} final items from {len(groups)} groups")
        return final_items
    
    def validate_extraction(self, vendor_human: str, product_human: str, cleaned_title: str,
                          vendor_machine: str, product_machine: str) -> Dict:
        issues = []
        
        if not vendor_human or not product_human or not cleaned_title:
            issues.append("Missing required fields")
            return {'is_valid': False, 'issues': issues}
        
        # Special handling for vendor=product machine cases
        if vendor_machine == product_machine:
            # For same machines, both names should be identical and equal cleaned_title
            if vendor_human != product_human:
                issues.append("Vendor and product should be identical for same machines")
            if vendor_human != cleaned_title:
                issues.append("Names should equal cleaned title for same machines")
        else:
            # For different machines, standard reconstruction
            reconstructed = f"{vendor_human} {product_human}".strip()
            if reconstructed != cleaned_title:
                issues.append("Reconstruction mismatch")
        
        def clean_for_alignment(s: str) -> str:
            return re.sub(r'[^a-zA-Z0-9]', '', s.lower())
        
        vh_clean = clean_for_alignment(vendor_human)
        vm_clean = clean_for_alignment(vendor_machine)
        ph_clean = clean_for_alignment(product_human)
        pm_clean = clean_for_alignment(product_machine)
        
        # Character alignment validation (more lenient for complex cases)
        if vendor_machine == product_machine:
            # For same machines, validate against machine identifier
            if vh_clean and vm_clean:
                if not (vh_clean.startswith(vm_clean[0]) or vm_clean.startswith(vh_clean[0])):
                    issues.append("Character alignment mismatch")
        else:
            # For different machines, validate each separately with more flexibility
            if vh_clean and vm_clean and len(vh_clean) > 0 and len(vm_clean) > 0:
                if vh_clean[0] != vm_clean[0]:
                    issues.append("Vendor start character mismatch")
            
            if ph_clean and pm_clean and len(ph_clean) > 0 and len(pm_clean) > 0:
                if ph_clean[0] != pm_clean[0]:
                    issues.append("Product start character mismatch")
        
        is_valid = len(issues) == 0
        return {'is_valid': is_valid, 'issues': issues}
    
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
            "AI_Confidence", "AI_Reasoning", "Cleaned_Title", "Validation_Issues"
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
        
        high_confidence = df[df["AI_Confidence"] >= 0.8].shape[0] if "AI_Confidence" in df.columns else 0
        logger.info(f"High confidence extractions (>=0.8): {high_confidence}")
    
    def run(self, output_file: str):
        logger.info("Starting intelligent OpenAI-driven CPE processing")
        if not Path(self.xml_file_path).exists():
            raise FileNotFoundError(f"XML file not found: {self.xml_file_path}")
        
        cpe_data = self.parse_xml_file()
        if not cpe_data:
            logger.error("No valid CPE data found")
            return
        
        self.create_excel_file(cpe_data, output_file)
        logger.info("CPE processing completed successfully")