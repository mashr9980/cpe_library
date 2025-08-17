# xml_to_excel_processor.py - Process CPE XML and generate Excel
import xml.etree.ElementTree as ET
import pandas as pd
import os
import sys
from typing import List, Dict, Optional
from cpe_parser import CpeParser, CpeParsingException
from test import test_cpe_parser

class CPEXMLProcessor:
    def __init__(self, xml_file_path: str, sample_percentage: float = 0.01):
        """
        Initialize the CPE XML processor
        
        Args:
            xml_file_path: Path to the official-cpe-dictionary_v2.3.xml file
            sample_percentage: Percentage of data to process (0.01 = 1%, 1.0 = 100%)
        """
        self.xml_file_path = xml_file_path
        self.sample_percentage = sample_percentage
        self.namespaces = {
            'cpe': 'http://cpe.mitre.org/dictionary/2.0',
            'cpe-23': 'http://scap.nist.gov/schema/cpe-extension/2.3'
        }
        
    def parse_xml_to_dataframe(self) -> pd.DataFrame:
        """
        Parse the XML file and convert to a pandas DataFrame
        
        Returns:
            DataFrame with CPE data
        """
        print(f"📁 Processing XML file: {self.xml_file_path}")
        print(f"📊 Sample percentage: {self.sample_percentage * 100:.2f}%")
        
        # Parse XML file
        try:
            tree = ET.parse(self.xml_file_path)
            root = tree.getroot()
        except Exception as e:
            print(f"❌ Error parsing XML file: {e}")
            sys.exit(1)
        
        # Find all CPE items
        cpe_items = root.findall('.//cpe:cpe-item', self.namespaces)
        total_items = len(cpe_items)
        
        print(f"📝 Total CPE items found: {total_items:,}")
        
        # Calculate sample size
        sample_size = max(1, int(total_items * self.sample_percentage))
        print(f"🎯 Processing {sample_size:,} items ({self.sample_percentage * 100:.2f}%)")
        
        # Take sample
        sample_items = cpe_items[:sample_size]
        
        # Process items
        processed_data = []
        for i, item in enumerate(sample_items):
            try:
                cpe_data = self._process_cpe_item(item)
                if cpe_data:
                    processed_data.append(cpe_data)
                
                # Progress indicator
                if (i + 1) % 1000 == 0 or i == len(sample_items) - 1:
                    print(f"⏳ Processed {i + 1:,}/{len(sample_items):,} items...")
                    
            except Exception as e:
                print(f"⚠️  Error processing item {i}: {e}")
                continue
        
        print(f"✅ Successfully processed {len(processed_data):,} items")
        
        # Create DataFrame
        df = pd.DataFrame(processed_data)
        return df
    
    def _process_cpe_item(self, item) -> Optional[Dict]:
        """
        Process a single CPE item and extract relevant data
        
        Args:
            item: XML element representing a CPE item
            
        Returns:
            Dictionary with CPE data or None if processing fails
        """
        try:
            # Get CPE names
            cpe_22_name = item.get('name', '')
            cpe_23_element = item.find('.//cpe-23:cpe23-item', self.namespaces)
            cpe_23_name = cpe_23_element.get('name', '') if cpe_23_element is not None else ''
            
            # Get title
            title_element = item.find('.//cpe:title', self.namespaces)
            title = title_element.text if title_element is not None else ''
            
            # Get references
            references = []
            reference_elements = item.findall('.//cpe:reference', self.namespaces)
            for ref in reference_elements:
                href = ref.get('href', '')
                ref_text = ref.text or ''
                if href:
                    references.append(f"{ref_text}: {href}")
            
            references_str = ' | '.join(references)
            
            # Parse CPE using our parser
            cpe_data = self._parse_cpe_with_parser(cpe_23_name or cpe_22_name)
            
            # Combine all data
            result = {
                'cpe_22_uri': cpe_22_name,
                'cpe_23_fs': cpe_23_name,
                'title': title,
                'references': references_str,
                **cpe_data
            }
            
            return result
            
        except Exception as e:
            print(f"Error processing CPE item: {e}")
            return None
    
    def _parse_cpe_with_parser(self, cpe_string: str) -> Dict:
        """
        Parse CPE string using our CPE parser and extract components
        
        Args:
            cpe_string: CPE string to parse
            
        Returns:
            Dictionary with parsed CPE components
        """
        default_data = {
            'part': '',
            'vendor': '',
            'product': '',
            'version': '',
            'update': '',
            'edition': '',
            'language': '',
            'sw_edition': '',
            'target_sw': '',
            'target_hw': '',
            'other': '',
            'parsed_successfully': False,
            'parse_error': ''
        }
        
        if not cpe_string:
            default_data['parse_error'] = 'Empty CPE string'
            return default_data
        
        try:
            # Parse using our CPE parser
            cpe = CpeParser.parse(cpe_string)
            
            return {
                'part': cpe.get_part().get_abbreviation(),
                'vendor': cpe.get_vendor(),
                'product': cpe.get_product(),
                'version': cpe.get_version(),
                'update': cpe.get_update(),
                'edition': cpe.get_edition(),
                'language': cpe.get_language(),
                'sw_edition': cpe.get_sw_edition(),
                'target_sw': cpe.get_target_sw(),
                'target_hw': cpe.get_target_hw(),
                'other': cpe.get_other(),
                'parsed_successfully': True,
                'parse_error': ''
            }
            
        except CpeParsingException as e:
            default_data['parse_error'] = str(e)
            return default_data
        except Exception as e:
            default_data['parse_error'] = f"Unexpected error: {str(e)}"
            return default_data
    
    def save_to_excel(self, df: pd.DataFrame, output_file: str = "cpe_data.xlsx"):
        """
        Save DataFrame to Excel file
        
        Args:
            df: DataFrame to save
            output_file: Output Excel file path
        """
        print(f"💾 Saving data to Excel file: {output_file}")
        
        try:
            # Define column order for better readability
            column_order = [
                'cpe_22_uri',
                'cpe_23_fs', 
                'title',
                'part',
                'vendor',
                'product',
                'version',
                'update',
                'edition',
                'language',
                'sw_edition',
                'target_sw',
                'target_hw',
                'other',
                'parsed_successfully',
                'parse_error',
                'references'
            ]
            
            # Reorder columns if they exist
            available_columns = [col for col in column_order if col in df.columns]
            remaining_columns = [col for col in df.columns if col not in column_order]
            final_columns = available_columns + remaining_columns
            
            df_ordered = df[final_columns]
            
            # Save to Excel with formatting
            with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
                df_ordered.to_excel(writer, sheet_name='CPE_Data', index=False)
                
                # Get the workbook and worksheet
                workbook = writer.book
                worksheet = writer.sheets['CPE_Data']
                
                # Auto-adjust column widths
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    
                    adjusted_width = min(max_length + 2, 50)  # Cap at 50 characters
                    worksheet.column_dimensions[column_letter].width = adjusted_width
            
            print(f"✅ Excel file saved successfully!")
            print(f"📊 Total rows: {len(df):,}")
            print(f"📋 Total columns: {len(df.columns)}")
            
        except Exception as e:
            print(f"❌ Error saving Excel file: {e}")
    
    def process_and_save(self, output_file: str = "cpe_data.xlsx"):
        """
        Complete processing: parse XML and save to Excel
        
        Args:
            output_file: Output Excel file path
        """
        print("🚀 Starting CPE XML to Excel conversion...")
        
        # Check if XML file exists
        if not os.path.exists(self.xml_file_path):
            print(f"❌ XML file not found: {self.xml_file_path}")
            print("Please ensure the official-cpe-dictionary_v2.3.xml file is in the current directory")
            return
        
        # Parse XML to DataFrame
        df = self.parse_xml_to_dataframe()
        
        if df.empty:
            print("❌ No data was processed successfully")
            return
        
        # Save to Excel
        self.save_to_excel(df, output_file)
        
        # Print summary statistics
        self._print_summary_stats(df)
    
    def _print_summary_stats(self, df: pd.DataFrame):
        """Print summary statistics about the processed data"""
        print("\n📈 Summary Statistics:")
        print("=" * 50)
        
        if 'parsed_successfully' in df.columns:
            successful_parses = df['parsed_successfully'].sum()
            total_items = len(df)
            success_rate = (successful_parses / total_items) * 100
            print(f"✅ Successfully parsed: {successful_parses:,}/{total_items:,} ({success_rate:.1f}%)")
        
        if 'part' in df.columns:
            print(f"\n📊 CPE Parts distribution:")
            part_counts = df['part'].value_counts()
            for part, count in part_counts.items():
                if part:
                    part_name = {'a': 'Application', 'o': 'Operating System', 'h': 'Hardware'}.get(part, part)
                    print(f"   {part_name} ({part}): {count:,}")
        
        if 'vendor' in df.columns:
            unique_vendors = df['vendor'].nunique()
            print(f"\n🏢 Unique vendors: {unique_vendors:,}")
            
            top_vendors = df['vendor'].value_counts().head(5)
            print(f"   Top 5 vendors:")
            for vendor, count in top_vendors.items():
                if vendor and vendor != '*':
                    print(f"   - {vendor}: {count}")
        
        print("=" * 50)

def main():
    """Main function to run the CPE processing"""
    print("🏃‍♂️ Running CPE Parser Tests...")
    test_cpe_parser()
    
    print("🔄 Starting XML to Excel Processing...")
    
    # Configuration
    xml_file = "official-cpe-dictionary_v2.3.xml"
    output_file = "cpe_data_sample_2.xlsx"
    sample_percentage = 0.0001  # 1% for testing - change to 1.0 for 100%
    
    # Create processor and run
    processor = CPEXMLProcessor(xml_file, sample_percentage)
    processor.process_and_save(output_file)
    
    print(f"\n🎉 Process completed! Check '{output_file}' for results.")
    print(f"💡 To process all data, change sample_percentage to 1.0 in the main() function")

if __name__ == "__main__":
    main()
