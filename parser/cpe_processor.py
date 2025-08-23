import os
import xml.etree.ElementTree as ET
import pandas as pd
import logging
import random
import asyncio
from typing import List, Dict, Optional
from pathlib import Path
from collections import defaultdict

from processor.cpe import Cpe
from processor.cpe_parser import CpeParser
from values.part import Part
from exceptions import CpeParsingException
from parser.validators import TechnicalValidator
from parser.ai_corrector import OpenAICorrector
from parser.rule_extractor import RuleBasedExtractor

logger = logging.getLogger(__name__)

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
            self.openai_corrector = OpenAICorrector(openai_api_key)
        else:
            self.openai_corrector = None
            logger.warning("OpenAI API key not found, AI correction disabled")
    
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
        
        grouped = defaultdict(list)
        for item in raw_items:
            key = (item['vendor_machine'], item['product_machine'], item['part'])
            grouped[key].append(item)
        
        final_items = []
        for (vendor_machine, product_machine, part), items in grouped.items():
            representative = items[0]
            
            titles = [item['title'] for item in items if item['title']]
            combined_title = titles[0] if titles else ""
            
            all_cpes = [item['cpe'] for item in items]
            all_versions = list(set(item['version'] for item in items if item['version'] != "-"))
            all_references = []
            for item in items:
                all_references.extend(item.get('references', []))
            
            vendor_human, product_human = RuleBasedExtractor.extract_from_title(
                combined_title, vendor_machine, product_machine
            )
            
            validation = TechnicalValidator.validate_extraction(
                vendor_human, vendor_machine, product_human, product_machine,
                representative['version'], representative['target_sw'], combined_title
            )
            
            if not validation.is_valid and self.openai_corrector:
                logger.info(f"Attempting AI correction for: {vendor_machine} / {product_machine}")
                try:
                    correction = asyncio.run(self.openai_corrector.correct_extraction(
                        representative['cpe'], combined_title, vendor_machine, product_machine,
                        part.get_abbreviation(), representative['target_sw']
                    ))
                    if correction['vendor_name'] and correction['product_name']:
                        logger.info(f"AI correction: {vendor_human} -> {correction['vendor_name']}, {product_human} -> {correction['product_name']}")
                        vendor_human = correction['vendor_name']
                        product_human = correction['product_name']
                        
                        validation = TechnicalValidator.validate_extraction(
                            vendor_human, vendor_machine, product_human, product_machine,
                            representative['version'], representative['target_sw'], combined_title
                        )
                        logger.info(f"Post-correction validation: {validation.is_valid}")
                    else:
                        logger.warning("AI correction returned empty results")
                except Exception as e:
                    logger.error(f"AI correction failed: {e}")
            elif not validation.is_valid:
                logger.warning(f"Validation failed but no OpenAI corrector available for: {vendor_machine} / {product_machine}")
                logger.warning(f"Validation issues: {validation.issues}")
            
            final_item = {
                "cpe": " | ".join(all_cpes),
                "Title": combined_title,
                "vendor_human": vendor_human,
                "product_human": product_human,
                "Validation Product Name": validation.is_valid,
                "part": part.get_abbreviation(),
                "target_softwares": [representative['target_sw']] if representative['target_sw'] != "*" else ["*"],
                "target_hardwares": [representative['target_hw']] if representative['target_hw'] != "*" else ["*"],
                "versions": all_versions if all_versions else ["-"],
                "updates": [representative['update']] if representative['update'] != "*" else ["*"],
                "editions": [representative['edition']] if representative['edition'] != "*" else ["*"],
                "languages": [representative['language']] if representative['language'] != "*" else ["*"],
                "references": list(set(all_references)),
                "category": self.get_corrected_category(part, product_machine, combined_title)
            }
            
            final_items.append(final_item)
        
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
            "editions", "languages", "references", "category"
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
        
        if self.openai_corrector:
            logger.info("OpenAI corrector was available for failed validations")
        else:
            logger.warning("OpenAI corrector was NOT available - add OPENAI_API_KEY to enable AI corrections")
    
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