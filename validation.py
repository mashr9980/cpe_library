import os
import pandas as pd
import openai
import logging
import json
import time
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class CpeVendorProductCorrector:
    def __init__(self, input_excel_path: str, output_excel_path: str):
        self.input_excel_path = input_excel_path
        self.output_excel_path = output_excel_path
        
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        openai.api_key = openai_api_key
        self.client = openai.OpenAI(api_key=openai_api_key)
        
    def read_excel_data(self) -> pd.DataFrame:
        logger.info(f"Reading Excel file: {self.input_excel_path}")
        try:
            df = pd.read_excel(self.input_excel_path)
            logger.info(f"Successfully loaded {len(df)} rows from Excel file")
            return df
        except Exception as e:
            logger.error(f"Error reading Excel file: {e}")
            raise

    def correct_vendor_product_names(self, cpe: str, title: str) -> Dict:
        system_prompt = """You are a vendor and product name extraction expert. Extract the correct vendor name and product name from the CPE string and title.

Rules for vendor names:
- Use the official company/organization name as it appears in the title
- Keep proper capitalization and spacing
- Remove unnecessary suffixes like "Inc.", "LLC", "Corp" unless they're part of the brand
- Use the full name, not abbreviations when possible

Rules for product names:
- Use the exact product name as it appears in the title
- Keep proper capitalization and spacing
- Include version numbers only if they're part of the product name itself
- Remove version numbers that are separate from the product name
- Keep model numbers if they're part of the product name

Respond ONLY with valid JSON."""

        user_prompt = f"""Extract the correct vendor and product names from this data:

CPE: {cpe}
Title: {title}

Return JSON with corrected names:
{{
    "vendor_name": "...",
    "product_name": "..."
}}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=200,
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            return {
                "vendor_name": result.get("vendor_name", "").strip(),
                "product_name": result.get("product_name", "").strip()
            }
            
        except Exception as e:
            logger.error(f"Error calling OpenAI API: {e}")
            return {
                "vendor_name": "",
                "product_name": ""
            }

    def process_excel_file(self):
        if not Path(self.input_excel_path).exists():
            raise FileNotFoundError(f"Input Excel file not found: {self.input_excel_path}")
        
        df = self.read_excel_data()
        
        logger.info("Starting vendor/product name correction process...")
        
        corrected_vendors = []
        corrected_products = []
        
        for index, row in df.iterrows():
            logger.info(f"Processing row {index + 1}/{len(df)}")
            
            cpe = str(row.get('cpe', ''))
            title = str(row.get('Title', ''))
            
            if cpe and title:
                correction_result = self.correct_vendor_product_names(cpe, title)
                corrected_vendors.append(correction_result.get('vendor_name', row.get('vendor_human', '')))
                corrected_products.append(correction_result.get('product_name', row.get('product_human', '')))
            else:
                corrected_vendors.append(row.get('vendor_human', ''))
                corrected_products.append(row.get('product_human', ''))
            
            time.sleep(0.1)
        
        df['vendor_human'] = corrected_vendors
        df['product_human'] = corrected_products
        
        final_columns = [
            "cpe", "Title", "vendor_human", "product_human", "Validation Product Name",
            "part", "target_softwares", "target_hardwares", "versions", "updates",
            "editions", "languages", "references", "category"
        ]
        
        df_final = df[final_columns]
        
        output_dir = Path(self.output_excel_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        with pd.ExcelWriter(self.output_excel_path, engine="openpyxl") as writer:
            df_final.to_excel(writer, sheet_name="Sheet1", index=False)
        
        logger.info(f"Corrected Excel file created: {self.output_excel_path}")
        logger.info(f"Total rows processed: {len(df)}")
        
        changes_made = 0
        for i in range(len(df)):
            original_vendor = df.iloc[i].get('vendor_human', '') if hasattr(df.iloc[i], 'get') else ''
            original_product = df.iloc[i].get('product_human', '') if hasattr(df.iloc[i], 'get') else ''
            if (corrected_vendors[i] != original_vendor or corrected_products[i] != original_product):
                changes_made += 1
        
        logger.info(f"Vendor/Product names corrected in {changes_made} rows")

def main():
    INPUT_EXCEL_PATH = os.getenv("INPUT_EXCEL_PATH", "output/cpe_extracted_data_0.0003.xlsx")
    OUTPUT_EXCEL_PATH = os.getenv("OUTPUT_EXCEL_PATH", "output/cpe_1.xlsx")
    
    try:
        processor = CpeVendorProductCorrector(INPUT_EXCEL_PATH, OUTPUT_EXCEL_PATH)
        processor.process_excel_file()
        print("Vendor/Product name correction process completed successfully!")
        print(f"Input file: {INPUT_EXCEL_PATH}")
        print(f"Output file: {OUTPUT_EXCEL_PATH}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()