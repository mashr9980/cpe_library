#!/usr/bin/env python3

import xml.etree.ElementTree as ET
import pandas as pd
import re
import logging
from typing import List, Dict, Optional
import random
from pathlib import Path

try:
    from processor.cpe import Cpe
    from processor.cpe_parser import CpeParser
    from values.part import Part
    from values.logical_value import LogicalValue
    from exceptions import CpeParsingException
except ImportError as e:
    print(f"Error importing CPE parser modules: {e}")
    raise

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CpeXmlToExcelConverter:
    
    def __init__(self, xml_file_path: str, sample_percentage: float = 0.01):
        self.xml_file_path = xml_file_path
        self.sample_percentage = sample_percentage
        self.namespaces = {
            'cpe': 'http://cpe.mitre.org/dictionary/2.0',
            'cpe-23': 'http://scap.nist.gov/schema/cpe-extension/2.3'
        }
    
    def parse_xml_file(self) -> List[Dict]:
        logger.info(f"Parsing XML file: {self.xml_file_path}")
        
        try:
            tree = ET.parse(self.xml_file_path)
            root = tree.getroot()
        except ET.ParseError as e:
            logger.error(f"Failed to parse XML file: {e}")
            raise
        except FileNotFoundError:
            logger.error(f"XML file not found: {self.xml_file_path}")
            raise
        
        cpe_items = root.findall('.//cpe:cpe-item', self.namespaces)
        total_items = len(cpe_items)
        
        sample_size = max(1, int(total_items * self.sample_percentage))
        logger.info(f"Found {total_items} CPE items, sampling {sample_size} items ({self.sample_percentage*100:.2f}%)")
        
        sampled_items = random.sample(cpe_items, sample_size)
        
        parsed_data = []
        for item in sampled_items:
            try:
                cpe_data = self.parse_cpe_item(item)
                if cpe_data:
                    parsed_data.append(cpe_data)
            except Exception as e:
                logger.warning(f"Failed to parse CPE item: {e}")
                continue
        
        logger.info(f"Successfully parsed {len(parsed_data)} CPE items")
        return parsed_data
    
    def parse_cpe_item(self, cpe_item: ET.Element) -> Optional[Dict]:
        try:
            cpe_22_uri = cpe_item.get('name', '')
            
            cpe_23_element = cpe_item.find('.//cpe-23:cpe23-item', self.namespaces)
            cpe_23_fs = cpe_23_element.get('name', '') if cpe_23_element is not None else ''
            
            title_element = cpe_item.find('.//cpe:title', self.namespaces)
            title = title_element.text if title_element is not None else ''
            
            references = []
            ref_elements = cpe_item.findall('.//cpe:reference', self.namespaces)
            for ref in ref_elements:
                href = ref.get('href', '')
                if href:
                    references.append(href)
            
            cpe_string = cpe_23_fs if cpe_23_fs else cpe_22_uri
            
            if not cpe_string:
                return None
            
            parsed_cpe = CpeParser.parse(cpe_string)
            
            return self.extract_cpe_components(parsed_cpe, title, references, cpe_string)
            
        except CpeParsingException:
            return None
        except Exception:
            return None
    
    def extract_cpe_components(self, cpe: Cpe, title: str, references: List[str], cpe_string: str) -> Dict:
        vendor_machine = cpe.get_vendor()
        product_machine = cpe.get_product()
        version = cpe.get_version()
        update = cpe.get_update()
        edition = cpe.get_edition()
        language = cpe.get_language()
        target_sw = cpe.get_target_sw()
        target_hw = cpe.get_target_hw()
        part = cpe.get_part()
        
        vendor_human = self.generate_human_readable_name(vendor_machine)
        product_human = self.generate_human_readable_name(product_machine)
        
        validation_result = self.validate_extracted_data(
            vendor_human, vendor_machine, product_human, product_machine, 
            version, target_sw, title
        )
        
        category = self.get_category_from_part(part)
        
        return {
            'cpe': cpe_string,
            'Title': title,
            'vendor_human': vendor_human,
            'product_human': product_human,
            'Validation Product Name': validation_result,
            'part': part.get_abbreviation(),
            'target_softwares': [target_sw] if target_sw != '*' else ['*'],
            'target_hardwares': [target_hw] if target_hw != '*' else ['*'],
            'versions': [version] if version != '-' else ['-'],
            'updates': [update] if update != '*' else ['*'],
            'editions': [edition] if edition != '*' else ['*'],
            'languages': [language] if language != '*' else ['*'],
            'references': references,
            'category': category
        }
    
    def generate_human_readable_name(self, machine_name: str) -> str:
        if machine_name in ['*', '-']:
            return machine_name
        
        human_name = machine_name.replace('_', ' ').replace('-', ' ')
        
        words = human_name.split()
        capitalized_words = []
        
        for word in words:
            if re.match(r'^[A-Z]{2,}$', word):
                capitalized_words.append(word)
            elif re.match(r'^v?\d+(\.\d+)*', word):
                capitalized_words.append(word)
            else:
                capitalized_words.append(word.capitalize())
        
        return ' '.join(capitalized_words)
    
    def normalize_for_comparison(self, text: str) -> str:
        if not text or text in ['*', '-']:
            return text
        
        normalized = re.sub(r'[^a-zA-Z0-9]', '', text.lower())
        return normalized
    
    def extract_key_words(self, text: str) -> set:
        if not text or text in ['*', '-']:
            return set()
        
        words = re.findall(r'[a-zA-Z0-9]+', text.lower())
        return {word for word in words if len(word) > 2}
    
    def split_camel_case(self, text: str) -> list:
        """Split camelCase or PascalCase words"""
        if not text:
            return []
        
        words = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)|[0-9]+', text)
        return [word.lower() for word in words if len(word) > 1]
    
    def get_word_variations(self, text: str) -> set:
        """Get various word forms from text"""
        if not text or text in ['*', '-']:
            return set()
        
        variations = set()
        
        # Original words
        words = re.findall(r'[a-zA-Z0-9]+', text.lower())
        variations.update(word for word in words if len(word) > 2)
        
        # Split camelCase
        camel_words = self.split_camel_case(text)
        variations.update(word for word in camel_words if len(word) > 2)
        
        # Handle common abbreviations and expansions
        text_lower = text.lower()
        if 'cms' in text_lower:
            variations.update(['cms', 'management', 'system'])
        if 'wp' in text_lower:
            variations.update(['wp', 'wordpress'])
        if 'foundation' in text_lower:
            variations.add('foundation')
        if 'software' in text_lower:
            variations.add('software')
        if 'group' in text_lower:
            variations.add('group')
        if 'tech' in text_lower:
            variations.update(['tech', 'technology'])
        
        return variations
    
    def validate_extracted_data(self, vendor_human: str, vendor_machine: str, 
                              product_human: str, product_machine: str,
                              version: str, target_sw: str, title: str) -> bool:
        try:
            if not all([vendor_human, vendor_machine, product_human, product_machine]):
                return False
            
            if any(x in ['*', '-'] for x in [vendor_human, vendor_machine, product_human, product_machine]):
                return False
            
            vendor_human_norm = self.normalize_for_comparison(vendor_human)
            vendor_machine_norm = self.normalize_for_comparison(vendor_machine)
            product_human_norm = self.normalize_for_comparison(product_human)
            product_machine_norm = self.normalize_for_comparison(product_machine)
            
            if not vendor_human_norm or not vendor_machine_norm:
                return False
            if not product_human_norm or not product_machine_norm:
                return False
            
            # Relaxed start/end character matching - allow some flexibility
            vendor_start_match = (vendor_human_norm[0] == vendor_machine_norm[0] or 
                                abs(ord(vendor_human_norm[0]) - ord(vendor_machine_norm[0])) <= 2)
            vendor_end_match = (vendor_human_norm[-1] == vendor_machine_norm[-1] or
                               abs(ord(vendor_human_norm[-1]) - ord(vendor_machine_norm[-1])) <= 2)
            product_start_match = (product_human_norm[0] == product_machine_norm[0] or
                                 abs(ord(product_human_norm[0]) - ord(product_machine_norm[0])) <= 2)
            product_end_match = (product_human_norm[-1] == product_machine_norm[-1] or
                                abs(ord(product_human_norm[-1]) - ord(product_machine_norm[-1])) <= 2)
            
            if not (vendor_start_match and vendor_end_match):
                return False
            if not (product_start_match and product_end_match):
                return False
            
            title_variations = self.get_word_variations(title)
            vendor_variations = self.get_word_variations(vendor_human)
            product_variations = self.get_word_variations(product_human)
            
            # Check vendor match
            vendor_match = False
            if vendor_variations:
                vendor_overlap = len(vendor_variations.intersection(title_variations))
                vendor_match = vendor_overlap > 0
                
                # Additional check for partial matches
                if not vendor_match:
                    for vendor_word in vendor_variations:
                        for title_word in title_variations:
                            if (vendor_word in title_word or title_word in vendor_word) and len(vendor_word) > 3:
                                vendor_match = True
                                break
                        if vendor_match:
                            break
            else:
                vendor_match = True
            
            # Check product match
            product_match = False
            if product_variations:
                product_overlap = len(product_variations.intersection(title_variations))
                product_match = product_overlap > 0
                
                # Additional check for partial matches
                if not product_match:
                    for product_word in product_variations:
                        for title_word in title_variations:
                            if (product_word in title_word or title_word in product_word) and len(product_word) > 3:
                                product_match = True
                                break
                        if product_match:
                            break
            else:
                product_match = True
            
            return vendor_match and product_match
            
        except (IndexError, AttributeError):
            return False
    
    def get_category_from_part(self, part: Part) -> str:
        if part == Part.APPLICATION:
            return "Application"
        elif part == Part.OPERATING_SYSTEM:
            return "Operating System"
        elif part == Part.HARDWARE_DEVICE:
            return "Hardware"
        else:
            return "Unknown"
    
    def create_excel_file(self, data: List[Dict], output_file: str = "cpe_extracted_data.xlsx"):
        logger.info(f"Creating Excel file: {output_file}")
        
        columns = [
            'cpe', 'Title', 'vendor_human', 'product_human', 'Validation Product Name',
            'part', 'target_softwares', 'target_hardwares', 'versions', 'updates',
            'editions', 'languages', 'references', 'category', 'Unnamed: 12'
        ]
        
        df = pd.DataFrame(data)
        
        df = df.reindex(columns=columns, fill_value='')
        
        df['Unnamed: 12'] = ''
        
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Sheet1', index=False)
        
        logger.info(f"Excel file created successfully: {output_file}")
        logger.info(f"Total records: {len(df)}")
        logger.info(f"Validation passed: {df['Validation Product Name'].sum()}")
        logger.info(f"Validation failed: {len(df) - df['Validation Product Name'].sum()}")
    
    def run(self, output_file: str = "cpe_extracted_data.xlsx"):
        logger.info("Starting CPE XML to Excel conversion")
        
        if not Path(self.xml_file_path).exists():
            logger.error(f"XML file not found: {self.xml_file_path}")
            raise FileNotFoundError(f"XML file not found: {self.xml_file_path}")
        
        cpe_data = self.parse_xml_file()
        
        if not cpe_data:
            logger.error("No valid CPE data found")
            return
        
        self.create_excel_file(cpe_data, output_file)
        
        logger.info("CPE XML to Excel conversion completed successfully")

def main():
    XML_FILE_PATH = "official-cpe-dictionary_v2.3.xml"
    SAMPLE_PERCENTAGE = 0.0001
    OUTPUT_FILE = f"output/cpe_extracted_data_{SAMPLE_PERCENTAGE}.xlsx"
    
    try:
        converter = CpeXmlToExcelConverter(
            xml_file_path=XML_FILE_PATH,
            sample_percentage=SAMPLE_PERCENTAGE
        )
        
        converter.run(OUTPUT_FILE)
        
        print(f"\nConversion completed successfully!")
        print(f"Input: {XML_FILE_PATH}")
        print(f"Output: {OUTPUT_FILE}")
        print(f"Sample size: {SAMPLE_PERCENTAGE*100:.2f}%")
        
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print(f"Please ensure {XML_FILE_PATH} exists in the current directory")
    except Exception as e:
        print(f"Unexpected error: {e}")
        logger.exception("Unexpected error occurred")

if __name__ == "__main__":
    main()