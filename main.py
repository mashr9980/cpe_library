#!/usr/bin/env python3

import xml.etree.ElementTree as ET
import pandas as pd
import re
import logging
from typing import List, Dict, Optional, Tuple
import random
from pathlib import Path
import asyncio

from processor.azure_client import AzureOpenAI
# from azure_client import AzureOpenAI

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
        self.azure_client = AzureOpenAI(
            endpoint="https://ext-dev-software-kgraph-resource.cognitiveservices.azure.com/openai/deployments/o4-mini/chat/completions?api-version=2025-01-01-preview",
            api_key="2MQMrPxchgTJK0yYpEgJL1uS6cnsyjG1LiEmrd6VDCizTzzHilGeJQQJ99BHACPV0roXJ3w3AAAAACOGRdDV"
        )
    
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
                cpe_data = asyncio.run(self.parse_cpe_item(item))
                if cpe_data:
                    parsed_data.append(cpe_data)
            except Exception as e:
                logger.warning(f"Failed to parse CPE item: {e}")
                continue
        
        logger.info(f"Successfully parsed {len(parsed_data)} CPE items")
        return parsed_data
    
    async def parse_cpe_item(self, cpe_item: ET.Element) -> Optional[Dict]:
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
            
            return await self.extract_cpe_components(parsed_cpe, title, references, cpe_string)
            
        except CpeParsingException:
            return None
        except Exception:
            return None
    
    async def extract_cpe_components(self, cpe: Cpe, title: str, references: List[str], cpe_string: str) -> Dict:
        vendor_machine = cpe.get_vendor()
        product_machine = cpe.get_product()
        version = cpe.get_version()
        update = cpe.get_update()
        edition = cpe.get_edition()
        language = cpe.get_language()
        target_sw = cpe.get_target_sw()
        target_hw = cpe.get_target_hw()
        part = cpe.get_part()
        
        vendor_human, product_human = await self.extract_names_from_title_intelligent(title, vendor_machine, product_machine)
        
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
    
    async def extract_names_from_title_intelligent(self, title: str, vendor_machine: str, product_machine: str) -> Tuple[str, str]:
        if not title or title in ['*', '-']:
            return vendor_machine, product_machine
        
        title_analysis = self.analyze_title_structure(title)
        
        if title_analysis['single_entity']:
            vendor_human = await self.extract_single_entity_vendor(title, vendor_machine, product_machine)
            product_human = await self.extract_single_entity_product(title, vendor_machine, product_machine, vendor_human)
        else:
            vendor_human = await self.extract_multi_entity_vendor(title, vendor_machine, title_analysis)
            product_human = await self.extract_multi_entity_product(title, product_machine, vendor_human, title_analysis)
        
        vendor_human, product_human = self.ensure_different_names(vendor_human, product_human, title, vendor_machine, product_machine)
        
        return vendor_human, product_human
    
    def analyze_title_structure(self, title: str) -> Dict:
        words = title.split()
        
        company_indicators = ['Corp', 'Corporation', 'Inc', 'LLC', 'Ltd', 'Limited', 'AG', 'GmbH', 'Software', 'Foundation', 'Project', 'Systems', 'Technologies', 'Tech', 'Labs', 'Studio', 'Studios', 'Group', 'Team', 'Company']
        
        has_company_indicator = any(indicator in words for indicator in company_indicators)
        
        known_single_entities = ['OpenSSL', 'MySQL', 'PostgreSQL', 'MongoDB', 'Redis', 'Nginx', 'Apache', 'PHP', 'Python', 'Ruby', 'Node', 'jQuery', 'Vue', 'React', 'Angular']
        
        is_single_entity = any(entity.lower() in title.lower() for entity in known_single_entities)
        
        single_word_title = len([w for w in words if not re.match(r'\d+[\.\d]*', w)]) <= 2
        
        return {
            'single_entity': is_single_entity or (single_word_title and not has_company_indicator),
            'has_company_indicator': has_company_indicator,
            'word_count': len(words),
            'company_indicators': company_indicators
        }
    
    async def extract_single_entity_vendor(self, title: str, vendor_machine: str, product_machine: str) -> str:
        if vendor_machine == product_machine:
            first_word = title.split()[0] if title.split() else vendor_machine
            
            version_removed = re.sub(r'\s+\d+[\.\d]*.*$', '', first_word)
            return self.preserve_case_from_title(version_removed, title)
        
        return await self.extract_vendor_with_ai(title, vendor_machine)
    
    async def extract_single_entity_product(self, title: str, vendor_machine: str, product_machine: str, vendor_human: str) -> str:
        if vendor_machine == product_machine:
            first_part = title.split()[0] if title.split() else product_machine
            version_removed = re.sub(r'\s+\d+[\.\d]*.*$', '', first_part)
            return self.preserve_case_from_title(version_removed, title)
        
        title_without_vendor = title.replace(vendor_human, "").strip()
        return await self.extract_product_with_ai(title_without_vendor if title_without_vendor else title, product_machine)
    
    async def extract_multi_entity_vendor(self, title: str, vendor_machine: str, title_analysis: Dict) -> str:
        words = title.split()
        
        for i, word in enumerate(words):
            if word in title_analysis['company_indicators'] and i > 0:
                vendor_candidate = ' '.join(words[:i+1])
                if self.matches_machine_name(vendor_candidate, vendor_machine):
                    return self.preserve_case_from_title(vendor_candidate, title)
        
        return await self.extract_vendor_with_ai(title, vendor_machine)
    
    async def extract_multi_entity_product(self, title: str, product_machine: str, vendor_human: str, title_analysis: Dict) -> str:
        title_without_vendor = title.replace(vendor_human, "").strip()
        
        if not title_without_vendor:
            return await self.extract_product_with_ai(title, product_machine)
        
        product_candidate = self.extract_product_from_remaining_title(title_without_vendor)
        
        if self.matches_machine_name(product_candidate, product_machine):
            return self.preserve_case_from_title(product_candidate, title)
        
        return await self.extract_product_with_ai(title_without_vendor, product_machine)
    
    def extract_product_from_remaining_title(self, remaining_title: str) -> str:
        words = remaining_title.strip().split()
        
        stop_patterns = [r'\d+[\.\d]*', r'for\s+\w+', r'version\s*\d+', r'v\d+', r'beta', r'alpha', r'release', r'candidate', r'build']
        
        for i, word in enumerate(words):
            if any(re.search(pattern, word.lower()) for pattern in stop_patterns):
                if i > 0:
                    return ' '.join(words[:i])
                break
        
        max_words = min(len(words), 4)
        return ' '.join(words[:max_words])
    
    async def extract_vendor_with_ai(self, title: str, vendor_machine: str) -> str:
        prompt = f"""Extract the exact vendor/company name from this title, preserving original case and spacing:

Title: "{title}"
Machine reference: "{vendor_machine}"

Rules:
1. Extract ONLY the company/vendor name as it appears
2. Preserve exact case (IBM stays IBM, not Ibm)
3. Include company suffixes (LLC, Inc, Corp, etc.) if present
4. Do not include product names
5. Return only the vendor name, nothing else

Vendor name:"""

        try:
            response = await self.azure_client.chat.completions.create(
                model="o4-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=30
            )
            
            result = response.choices[0].message.content.strip()
            
            if result and len(result.split()) <= 4 and any(word.lower() in title.lower() for word in result.split()):
                return result
                
        except Exception as e:
            logger.warning(f"Azure OpenAI vendor extraction failed: {e}")
        
        return self.generate_human_readable_name(vendor_machine)
    
    async def extract_product_with_ai(self, title: str, product_machine: str) -> str:
        prompt = f"""Extract the exact product name from this title, preserving original case:

Title: "{title}"
Machine reference: "{product_machine}"

Rules:
1. Extract ONLY the product name as it appears
2. Preserve exact case and formatting
3. Remove version numbers and build info
4. Remove platform suffixes (for WordPress, for Android, etc.)
5. Return only the product name, nothing else

Product name:"""

        try:
            response = await self.azure_client.chat.completions.create(
                model="o4-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50
            )
            
            result = response.choices[0].message.content.strip()
            
            if result:
                cleaned = self.clean_product_name(result, title)
                if cleaned and any(word.lower() in title.lower() for word in cleaned.split()):
                    return cleaned
                    
        except Exception as e:
            logger.warning(f"Azure OpenAI product extraction failed: {e}")
        
        return self.generate_human_readable_name(product_machine)
    
    def matches_machine_name(self, candidate: str, machine_name: str) -> bool:
        candidate_clean = re.sub(r'[^a-zA-Z0-9]', '', candidate.lower())
        machine_clean = re.sub(r'[^a-zA-Z0-9]', '', machine_name.lower())
        
        return (candidate_clean == machine_clean or 
                candidate_clean in machine_clean or 
                machine_clean in candidate_clean)
    
    def preserve_case_from_title(self, text: str, title: str) -> str:
        text_lower = text.lower()
        title_lower = title.lower()
        
        start_index = title_lower.find(text_lower)
        if start_index != -1:
            return title[start_index:start_index + len(text)]
        
        return text
    
    def ensure_different_names(self, vendor_human: str, product_human: str, title: str, vendor_machine: str, product_machine: str) -> Tuple[str, str]:
        if vendor_human == product_human:
            if vendor_machine != product_machine:
                vendor_human = self.generate_human_readable_name(vendor_machine)
                product_human = self.generate_human_readable_name(product_machine)
            else:
                words = title.split()
                if len(words) >= 2:
                    vendor_human = words[0]
                    product_human = ' '.join(words[1:3]) if len(words) > 2 else words[1]
                    
                    product_human = re.sub(r'\s+\d+[\.\d]*.*$', '', product_human).strip()
                else:
                    product_human = f"{vendor_human} Software"
        
        return vendor_human, product_human
    
    def clean_product_name(self, product_name: str, title: str) -> str:
        version_patterns = [
            r'\s+\d+[\.\d]*.*$',
            r'\s+v\d+.*$',
            r'\s+\d{4}-\d{2}-\d{2}.*$',
            r'\s+[Bb]eta.*$',
            r'\s+[Rr]elease.*$',
            r'\s+[Bb]uild.*$',
            r'\s+[Aa]lpha.*$'
        ]
        
        cleaned = product_name
        for pattern in version_patterns:
            cleaned = re.sub(pattern, '', cleaned)
        
        platform_patterns = [
            r'\s+for\s+\w+.*$',
            r'\s+on\s+\w+.*$'
        ]
        
        for pattern in platform_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        return cleaned.strip()
    
    def generate_human_readable_name(self, machine_name: str) -> str:
        if machine_name in ['*', '-']:
            return machine_name
        
        human_name = machine_name.replace('_', ' ').replace('-', ' ')
        
        words = human_name.split()
        capitalized_words = []
        
        acronyms = ['IBM', 'API', 'SDK', 'IDE', 'CLI', 'GUI', 'CPU', 'GPU', 'RAM', 'SSD', 'HDD', 'USB', 'HTTP', 'HTTPS', 'FTP', 'SSH', 'VPN', 'DNS', 'URL', 'XML', 'JSON', 'HTML', 'CSS', 'JS', 'PHP', 'SQL']
        
        for word in words:
            if word.upper() in acronyms:
                capitalized_words.append(word.upper())
            elif re.match(r'^v?\d+(\.\d+)*', word):
                capitalized_words.append(word)
            else:
                capitalized_words.append(word.capitalize())
        
        return ' '.join(capitalized_words)
    
    def validate_extracted_data(self, vendor_human: str, vendor_machine: str, 
                              product_human: str, product_machine: str,
                              version: str, target_sw: str, title: str) -> bool:
        try:
            if not all([vendor_human, vendor_machine, product_human, product_machine]):
                return False
            
            if any(x in ['*', '-'] for x in [vendor_human, vendor_machine, product_human, product_machine]):
                return False
            
            if vendor_human.strip() == product_human.strip():
                return False
            
            title_lower = title.lower()
            vendor_lower = vendor_human.lower()
            product_lower = product_human.lower()
            
            vendor_in_title = vendor_lower in title_lower
            product_in_title = product_lower in title_lower
            
            if not vendor_in_title:
                vendor_words = vendor_lower.split()
                vendor_in_title = any(word in title_lower for word in vendor_words if len(word) > 2)
            
            if not product_in_title:
                product_words = product_lower.split()
                product_in_title = any(word in title_lower for word in product_words if len(word) > 2)
            
            return vendor_in_title and product_in_title
            
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
    SAMPLE_PERCENTAGE = 0.00011
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