# cpe_converter_ai.py
import os
import xml.etree.ElementTree as ET
import pandas as pd
import re
import logging
from typing import List, Dict, Optional, Tuple
import random
from pathlib import Path
import asyncio
from processor.azure_client import AzureOpenAI
from processor.cpe_resolver_ai import CpeVendorProductResolver, _affinity
import os
from dotenv import load_dotenv

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

class CpeXmlToExcelConverter:
    def __init__(self, xml_file_path: str, sample_percentage: float = 0.01):
        self.xml_file_path = xml_file_path
        self.sample_percentage = sample_percentage
        self.namespaces = {
            "cpe": "http://cpe.mitre.org/dictionary/2.0",
            "cpe-23": "http://scap.nist.gov/schema/cpe-extension/2.3"
        }
        endpoint = os.getenv("AZURE_OPENAI_CHAT_COMPLETIONS_ENDPOINT", "https://ext-dev-software-kgraph-resource.cognitiveservices.azure.com/openai/deployments/o4-mini/chat/completions?api-version=2025-01-01-preview")
        api_key = os.getenv("AZURE_OPENAI_API_KEY", "2MQMrPxchgTJK0yYpEgJL1uS6cnsyjG1LiEmrd6VDCizTzzHilGeJQQJ99BHACPV0roXJ3w3AAAAACOGRdDV")
        if not endpoint or not api_key:
            raise RuntimeError("Missing AZURE_OPENAI_CHAT_COMPLETIONS_ENDPOINT or AZURE_OPENAI_API_KEY")
        self.azure_client = AzureOpenAI(endpoint=endpoint, api_key=api_key)
        self.resolver = CpeVendorProductResolver(self.azure_client)

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
        parsed_data = []
        for item in sampled_items:
            try:
                cpe_data = asyncio.run(self.parse_cpe_item(item))
                if cpe_data:
                    parsed_data.append(cpe_data)
            except Exception:
                continue
        logger.info(f"Successfully parsed {len(parsed_data)} CPE items")
        return parsed_data

    async def parse_cpe_item(self, cpe_item: ET.Element) -> Optional[Dict]:
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
        vendor_human, product_human = await self.resolver.resolve(title or "", vendor_machine or "", product_machine or "")
        validation_result = self.validate_extracted_data(vendor_human, vendor_machine, product_human, product_machine, version, target_sw, title)
        category = self.get_category_from_part(part)
        return {
            "cpe": cpe_string,
            "Title": title,
            "vendor_human": vendor_human,
            "product_human": product_human,
            "Validation Product Name": validation_result,
            "part": part.get_abbreviation(),
            "target_softwares": [target_sw] if target_sw != "*" else ["*"],
            "target_hardwares": [target_hw] if target_hw != "*" else ["*"],
            "versions": [version] if version != "-" else ["-"],
            "updates": [update] if update != "*" else ["*"],
            "editions": [edition] if edition != "*" else ["*"],
            "languages": [language] if language != "*" else ["*"],
            "references": references,
            "category": category
        }

    def names_exist_in_title(self, vendor_name: str, product_name: str, title: str) -> bool:
        title_lower = title.lower()
        vendor_in_title = vendor_name.lower() in title_lower
        product_in_title = product_name.lower() in title_lower
        if not vendor_in_title:
            vendor_words = vendor_name.lower().split()
            vendor_in_title = all(word in title_lower for word in vendor_words if len(word) > 2)
        if not product_in_title:
            product_words = product_name.lower().split()
            product_in_title = all(word in title_lower for word in product_words if len(word) > 2)
        return vendor_in_title and product_in_title

    def validate_extracted_data(self, vendor_human: str, vendor_machine: str, product_human: str, product_machine: str, version: str, target_sw: str, title: str) -> bool:
        try:
            if not all([vendor_human, vendor_machine, product_human, product_machine]):
                return False
            if any(x in ["*", "-"] for x in [vendor_human, vendor_machine, product_machine]):
                return False
            if _affinity(vendor_human, vendor_machine) < 0.15:
                return False
            if _affinity(product_human, product_machine) < 0.15:
                return False
            if not self.names_exist_in_title(vendor_human, product_human, title):
                return False
            return True
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
        logger.info("Starting CPE XML to Excel conversion")
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
    SAMPLE_PERCENTAGE = float(os.getenv("CPE_SAMPLE_PERCENTAGE", "0.00001"))
    OUTPUT_FILE = os.getenv("CPE_OUTPUT_PATH", f"output/cpe_extracted_data_{SAMPLE_PERCENTAGE}.xlsx")
    try:
        converter = CpeXmlToExcelConverter(xml_file_path=XML_FILE_PATH, sample_percentage=SAMPLE_PERCENTAGE)
        converter.run(OUTPUT_FILE)
        print("Conversion completed successfully!")
        print(f"Output: {OUTPUT_FILE}")
        print(f"Sample size: {SAMPLE_PERCENTAGE*100:.5f}%")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print(f"Please ensure {XML_FILE_PATH} exists in the current directory")
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()