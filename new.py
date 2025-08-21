# optimized_cpe_converter.py
import os
import xml.etree.ElementTree as ET
import pandas as pd
import re
import logging
from typing import List, Dict, Optional, Tuple, Set
import random
from pathlib import Path
from collections import defaultdict, Counter

try:
    from processor.cpe import Cpe
    from processor.cpe_parser import CpeParser
    from values.part import Part
    from values.logical_value import LogicalValue
    from exceptions import CpeParsingException
except ImportError as e:
    raise

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class OptimizedCpeXmlToExcelConverter:
    def __init__(self, xml_file_path: str, sample_percentage: float = 0.01):
        self.xml_file_path = xml_file_path
        self.sample_percentage = sample_percentage
        self.namespaces = {
            "cpe": "http://cpe.mitre.org/dictionary/2.0",
            "cpe-23": "http://scap.nist.gov/schema/cpe-extension/2.3"
        }

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
        
        grouped_data = self.group_cpe_items(sampled_items)
        processed_data = self.process_grouped_data(grouped_data)
        
        logger.info(f"Successfully processed {len(processed_data)} CPE items")
        return processed_data

    def group_cpe_items(self, cpe_items: List[ET.Element]) -> Dict[Tuple[str, str], List[Dict]]:
        grouped_data = defaultdict(list)
        
        for item in cpe_items:
            try:
                cpe_data = self.parse_cpe_item_basic(item)
                if cpe_data:
                    key = (cpe_data['vendor_machine'], cpe_data['product_machine'])
                    grouped_data[key].append(cpe_data)
            except Exception:
                continue
        
        logger.info(f"Grouped {len(cpe_items)} items into {len(grouped_data)} groups")
        return grouped_data

    def parse_cpe_item_basic(self, cpe_item: ET.Element) -> Optional[Dict]:
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

    def process_grouped_data(self, grouped_data: Dict[Tuple[str, str], List[Dict]]) -> List[Dict]:
        processed_data = []
        
        for (vendor_machine, product_machine), items in grouped_data.items():
            if not items:
                continue
            
            titles = [item['title'] for item in items if item['title']]
            
            if not titles:
                vendor_human = self.smart_humanize(vendor_machine)
                product_human = self.smart_humanize(product_machine)
            else:
                vendor_human, product_human = self.extract_from_grouped_titles(
                    titles, vendor_machine, product_machine
                )
            
            for item in items:
                processed_item = self.create_final_item(
                    item, vendor_human, product_human
                )
                processed_data.append(processed_item)
        
        return processed_data

    def extract_from_grouped_titles(self, titles: List[str], vendor_machine: str, product_machine: str) -> Tuple[str, str]:
        core_name = self.find_core_product_name(titles)
        
        if vendor_machine == product_machine:
            return core_name, core_name
        
        vendor_name = self.extract_vendor_from_core(core_name, vendor_machine)
        product_name = self.extract_product_from_core(core_name, product_machine, vendor_name)
        
        if not vendor_name or self.token_similarity(vendor_name, vendor_machine) < 0.2:
            vendor_name = self.smart_humanize(vendor_machine)
        
        if not product_name or self.token_similarity(product_name, product_machine) < 0.2:
            product_name = self.smart_humanize(product_machine)
        
        if vendor_name == product_name and vendor_machine != product_machine:
            words = core_name.split()
            if len(words) >= 2:
                vendor_name = words[0]
                product_name = ' '.join(words[1:])
        
        return vendor_name, product_name

    def find_core_product_name(self, titles: List[str]) -> str:
        clean_titles = []
        
        for title in titles:
            clean = self.aggressive_clean_title(title)
            if clean:
                clean_titles.append(clean)
        
        if not clean_titles:
            return ""
        
        if len(set(clean_titles)) == 1:
            return clean_titles[0]
        
        common = self.find_stable_common_part(clean_titles)
        return common if common else clean_titles[0]

    def aggressive_clean_title(self, title: str) -> str:
        if not title:
            return ""
        
        clean = title
        
        clean = re.sub(r'\s+v?\d+[\.\d\w\-]*(?:\s+(?:alpha|beta|rc|release|candidate|final|stable|dev|post|build|patch|hotfix|update)[\w\d\.\-]*)*(?:\s+\d+)*$', '', clean, flags=re.I)
        clean = re.sub(r'\s+\d{4}(?:\.\d+)*(?:\.\d+)*$', '', clean)
        clean = re.sub(r'\s+(?:for|on)\s+(?:wordpress|android|ios|iphone\s*os|windows|linux|macos|node\.js|python|java|rust|perl|go|php|ruby|visual\s*studio\s*code).*$', '', clean, flags=re.I)
        clean = re.sub(r'\s+(?:pro|professional|enterprise|ultimate|lite|community|trial|free|standard|business|premium)\s*(?:edition)?$', '', clean, flags=re.I)
        clean = re.sub(r'\s+(?:x86|x64|32-bit|64-bit|arm64)$', '', clean, flags=re.I)
        clean = re.sub(r'\s+\([^)]*\)\s*$', '', clean)
        clean = re.sub(r'\s+\-\s*$', '', clean)
        clean = re.sub(r'\s+firmware\s*$', '', clean, flags=re.I)
        clean = re.sub(r'\s{2,}', ' ', clean)
        
        return clean.strip()

    def find_stable_common_part(self, titles: List[str]) -> str:
        if not titles:
            return ""
        
        words_lists = [title.split() for title in titles]
        if not words_lists:
            return ""
        
        min_words = min(len(words) for words in words_lists)
        common_words = []
        
        for i in range(min_words):
            word = words_lists[0][i]
            if all(len(words) > i and words[i].lower() == word.lower() for words in words_lists[1:]):
                common_words.append(word)
            else:
                break
        
        result = ' '.join(common_words)
        
        if len(common_words) > 3:
            result = ' '.join(common_words[:3])
        
        return result

    def extract_vendor_from_core(self, core_name: str, vendor_machine: str) -> str:
        if not core_name:
            return self.smart_humanize(vendor_machine)
        
        words = core_name.split()
        if not words:
            return self.smart_humanize(vendor_machine)
        
        best_match = ""
        best_score = 0
        
        for i in range(1, min(4, len(words) + 1)):
            candidate = ' '.join(words[:i])
            score = self.token_similarity(candidate, vendor_machine)
            if score > best_score:
                best_match = candidate
                best_score = score
        
        if best_score > 0.3:
            return best_match
        
        machine_hint = self.smart_humanize(vendor_machine)
        for word in words:
            if self.token_similarity(word, vendor_machine) > 0.4:
                return word
        
        return words[0] if words else machine_hint

    def extract_product_from_core(self, core_name: str, product_machine: str, vendor_name: str) -> str:
        if not core_name:
            return self.smart_humanize(product_machine)
        
        words = core_name.split()
        vendor_words = vendor_name.split() if vendor_name else []
        
        remaining_words = []
        vendor_word_count = len(vendor_words)
        
        if vendor_words and len(words) >= vendor_word_count:
            match_count = 0
            for i, word in enumerate(words[:vendor_word_count]):
                if i < len(vendor_words) and word.lower() == vendor_words[i].lower():
                    match_count += 1
                else:
                    break
            
            if match_count > 0:
                remaining_words = words[match_count:]
            else:
                remaining_words = words
        else:
            remaining_words = words
        
        if remaining_words:
            product_candidate = ' '.join(remaining_words)
            if self.token_similarity(product_candidate, product_machine) > 0.2:
                return product_candidate
        
        best_match = ""
        best_score = 0
        
        for i in range(1, len(words) + 1):
            candidate = ' '.join(words[:i])
            if candidate != vendor_name:
                score = self.token_similarity(candidate, product_machine)
                if score > best_score:
                    best_match = candidate
                    best_score = score
        
        if best_score > 0.3:
            return best_match
        
        if remaining_words:
            return ' '.join(remaining_words)
        
        return self.smart_humanize(product_machine)

    def token_similarity(self, human_name: str, machine_name: str) -> float:
        if not human_name or not machine_name:
            return 0.0
        
        human_tokens = set(re.findall(r'\w+', human_name.lower()))
        machine_tokens = set(re.findall(r'\w+', re.sub(r'[_\-]', ' ', machine_name.lower())))
        
        if not human_tokens or not machine_tokens:
            return 0.0
        
        intersection = human_tokens & machine_tokens
        union = human_tokens | machine_tokens
        jaccard = len(intersection) / len(union)
        
        human_clean = re.sub(r'[^a-z0-9]', '', human_name.lower())
        machine_clean = re.sub(r'[^a-z0-9]', '', machine_name.lower())
        
        if human_clean in machine_clean or machine_clean in human_clean:
            jaccard += 0.4
        
        for h_token in human_tokens:
            for m_token in machine_tokens:
                if h_token in m_token or m_token in h_token:
                    jaccard += 0.1
                    break
        
        return min(jaccard, 1.0)

    def smart_humanize(self, machine_name: str) -> str:
        if not machine_name or machine_name in ['*', '-']:
            return machine_name
        
        humanized = machine_name.replace('_', ' ').replace('-', ' ')
        humanized = re.sub(r'([a-z])([A-Z])', r'\1 \2', humanized)
        
        words = humanized.split()
        result_words = []
        
        for word in words:
            if word.isupper() and len(word) > 1:
                result_words.append(word)
            elif re.match(r'^[A-Z]{2,}$', word):
                result_words.append(word)
            else:
                result_words.append(word.capitalize())
        
        return ' '.join(result_words)

    def create_final_item(self, item: Dict, vendor_human: str, product_human: str) -> Dict:
        validation_result = self.validate_extracted_data(
            vendor_human, item['vendor_machine'], 
            product_human, item['product_machine'], 
            item['title']
        )
        
        category = self.get_category_from_part(item['part'])
        
        return {
            "cpe": item['cpe'],
            "Title": item['title'],
            "vendor_human": vendor_human,
            "product_human": product_human,
            "Validation Product Name": validation_result,
            "part": item['part'].get_abbreviation(),
            "target_softwares": [item['target_sw']] if item['target_sw'] != "*" else ["*"],
            "target_hardwares": [item['target_hw']] if item['target_hw'] != "*" else ["*"],
            "versions": [item['version']] if item['version'] != "-" else ["-"],
            "updates": [item['update']] if item['update'] != "*" else ["*"],
            "editions": [item['edition']] if item['edition'] != "*" else ["*"],
            "languages": [item['language']] if item['language'] != "*" else ["*"],
            "references": item['references'],
            "category": category
        }

    def validate_extracted_data(self, vendor_human: str, vendor_machine: str, 
                               product_human: str, product_machine: str, title: str) -> bool:
        try:
            if not all([vendor_human, vendor_machine, product_human, product_machine]):
                return False
            
            if any(x in ["*", "-"] for x in [vendor_human, vendor_machine, product_machine]):
                return False
            
            vendor_similarity = self.token_similarity(vendor_human, vendor_machine)
            product_similarity = self.token_similarity(product_human, product_machine)
            
            if vendor_similarity < 0.1 and product_similarity < 0.1:
                return False
            
            if not self.flexible_title_check(vendor_human, product_human, title):
                return False
            
            return True
        except (IndexError, AttributeError):
            return False

    def flexible_title_check(self, vendor_name: str, product_name: str, title: str) -> bool:
        if not title:
            return False
        
        title_lower = title.lower()
        title_clean = re.sub(r'[^a-z0-9\s]', ' ', title_lower)
        title_clean = re.sub(r'\s+', ' ', title_clean).strip()
        
        vendor_clean = re.sub(r'[^a-z0-9\s]', ' ', vendor_name.lower())
        product_clean = re.sub(r'[^a-z0-9\s]', ' ', product_name.lower())
        
        vendor_words = [w for w in vendor_clean.split() if len(w) > 2]
        product_words = [w for w in product_clean.split() if len(w) > 2]
        
        vendor_found = len(vendor_words) == 0 or all(word in title_clean for word in vendor_words)
        product_found = len(product_words) == 0 or all(word in title_clean for word in product_words)
        
        if not vendor_found:
            vendor_found = any(word in title_clean for word in vendor_words) if vendor_words else True
        
        if not product_found:
            product_found = any(word in title_clean for word in product_words) if product_words else True
        
        return vendor_found and product_found

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
            "cpe","Title","vendor_human","product_human","Validation Product Name",
            "part","target_softwares","target_hardwares","versions","updates",
            "editions","languages","references","category","Unnamed: 12"
        ]
        df = pd.DataFrame(data)
        df = df.reindex(columns=columns, fill_value="")
        df["Unnamed: 12"] = ""
        
        with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Sheet1", index=False)
        
        logger.info(f"Excel file created successfully: {output_file}")
        logger.info(f"Total records: {len(df)}")
        valid_sum = df["Validation Product Name"].sum() if "Validation Product Name" in df.columns else 0
        logger.info(f"Validation passed: {valid_sum}")
        logger.info(f"Validation failed: {len(df) - valid_sum}")

    def run(self, output_file: str = "cpe_extracted_data.xlsx"):
        logger.info("Starting optimized CPE XML to Excel conversion")
        if not Path(self.xml_file_path).exists():
            raise FileNotFoundError(f"XML file not found: {self.xml_file_path}")
        
        cpe_data = self.parse_xml_file()
        if not cpe_data:
            logger.error("No valid CPE data found")
            return
        
        self.create_excel_file(cpe_data, output_file)
        logger.info("CPE XML to Excel conversion completed successfully")

def main():
    XML_FILE_PATH = os.getenv("CPE_XML_PATH", "official-cpe-dictionary_v2.3.xml")
    SAMPLE_PERCENTAGE = float(os.getenv("CPE_SAMPLE_PERCENTAGE", "0.0003"))
    OUTPUT_FILE = os.getenv("CPE_OUTPUT_PATH", f"output/cpe_extracted_data_{SAMPLE_PERCENTAGE}.xlsx")
    
    try:
        converter = OptimizedCpeXmlToExcelConverter(xml_file_path=XML_FILE_PATH, sample_percentage=SAMPLE_PERCENTAGE)
        converter.run(OUTPUT_FILE)
        print("Conversion completed successfully!")
        print(f"Output: {OUTPUT_FILE}")
        print(f"Sample size: {SAMPLE_PERCENTAGE*100:.5f}%")
        print("Optimized approach with better validation!")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print(f"Please ensure {XML_FILE_PATH} exists in the current directory")
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()