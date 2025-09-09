import os
import logging
from dotenv import load_dotenv
from parser.cpe_processor import RuleBasedCpeProcessor

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def main():
    XML_FILE_PATH = os.getenv("CPE_XML_PATH")
    SAMPLE_PERCENTAGE = float(os.getenv("CPE_SAMPLE_PERCENTAGE"))
    OUTPUT_FILE = os.getenv("CPE_OUTPUT_PATH")
    
    try:
        processor = RuleBasedCpeProcessor(xml_file_path=XML_FILE_PATH, sample_percentage=SAMPLE_PERCENTAGE)
        processor.run(OUTPUT_FILE)
        print("Processing completed successfully!")
        print(f"Output: {OUTPUT_FILE}")
        print(f"Sample size: {SAMPLE_PERCENTAGE*100:.5f}%")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print(f"Please ensure {XML_FILE_PATH} exists in the current directory")
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()