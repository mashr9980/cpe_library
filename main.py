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
            
            # Use CPE 2.3 format as primary, fallback to 2.2
            primary_cpe = cpe_23_name or cpe_22_name
            
            # Get title
            title_element = item.find('.//cpe:title', self.namespaces)
            original_title = title_element.text if title_element is not None else ''
            
            # Get references as array
            references = []
            reference_elements = item.findall('.//cpe:reference', self.namespaces)
            for ref in reference_elements:
                href = ref.get('href', '')
                if href:
                    references.append(href)
            
            # Parse CPE using our parser
            cpe_data = self._parse_cpe_with_parser(primary_cpe)
            
            # Get machine values (raw from CPE)
            vendor_machine = cpe_data.get('vendor', '')
            product_machine = cpe_data.get('product', '')
            
            # Extract clean vendor/product names with technical validation
            vendor_human = self._clean_name_with_validation(vendor_machine, 'vendor')
            product_human = self._clean_name_with_validation(product_machine, 'product')
            
            # Technical validation
            validation_result = self._perform_technical_validation(
                vendor_human, vendor_machine,
                product_human, product_machine,
                cpe_data.get('version', '*'),
                cpe_data.get('target_sw', '*'),
                original_title
            )
            
            # Determine category based on part and other attributes
            category = self._determine_category(cpe_data, original_title)
            
            # Combine all data in the reference format
            result = {
                'cpe': primary_cpe,
                'Title': original_title,
                'vendor_human': vendor_human,
                'product_human': product_human,
                'vendor_machine': vendor_machine,  # Keep for validation
                'product_machine': product_machine,  # Keep for validation
                'Validation Product Name': validation_result['validation_passed'],
                'part': cpe_data.get('part', ''),
                'target_softwares': [cpe_data.get('target_sw', '*')] if cpe_data.get('target_sw') != '*' else ['*'],
                'target_hardwares': [cpe_data.get('target_hw', '*')] if cpe_data.get('target_hw') != '*' else ['*'],
                'versions': [cpe_data.get('version', '*')] if cpe_data.get('version') != '*' else ['*'],
                'updates': [cpe_data.get('update', '*')] if cpe_data.get('update') != '*' else ['*'],
                'editions': [cpe_data.get('edition', '*')] if cpe_data.get('edition') != '*' else ['*'],
                'languages': [cpe_data.get('language', '*')] if cpe_data.get('language') != '*' else ['*'],
                'references': references,
                'category': category,
                'validation_details': validation_result['details'],
                'constructed_title': validation_result['constructed_title']
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
            'version': '*',
            'update': '*',
            'edition': '*',
            'language': '*',
            'sw_edition': '*',
            'target_sw': '*',
            'target_hw': '*',
            'other': '*'
        }
        
        if not cpe_string:
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
                'other': cpe.get_other()
            }
            
        except CpeParsingException as e:
            print(f"CPE parsing error for '{cpe_string}': {e}")
            return default_data
        except Exception as e:
            print(f"Unexpected error parsing '{cpe_string}': {e}")
            return default_data
    
    def _clean_name_with_validation(self, name: str, name_type: str) -> str:
        """
        Clean vendor/product names while maintaining validation compatibility
        
        Args:
            name: Raw vendor or product name
            name_type: 'vendor' or 'product' for context
            
        Returns:
            Cleaned human-readable name that maintains start/end character validation
        """
        if not name or name in ['*', '-']:
            return ''
        
        original_name = name
        
        # Remove common suffixes but keep start/end characters intact
        suffixes_to_remove = [
            '_project', '_team', '_inc', '_corp', '_corporation', 
            '_ltd', '_llc', '_foundation', '_software', '_systems',
            '_technologies', '_tech', '_group', '_company', '_co'
        ]
        
        cleaned = name
        for suffix in suffixes_to_remove:
            if cleaned.lower().endswith(suffix):
                cleaned = cleaned[:-len(suffix)]
        
        # Replace underscores and hyphens with spaces, but keep original start/end
        cleaned = cleaned.replace('_', ' ').replace('-', ' ')
        
        # Handle special characters in names
        cleaned = cleaned.replace('\\', '').replace('/', ' ')
        
        # Clean multiple spaces and trim
        cleaned = ' '.join(cleaned.split())
        
        # Ensure we maintain the same start and end characters as original (validation requirement)
        if cleaned and original_name:
            # If cleaning changed start/end characters significantly, be more conservative
            if (cleaned.lower()[0] != original_name.lower()[0] or 
                cleaned.lower()[-1] != original_name.lower()[-1]):
                # Try a more conservative approach
                conservative_clean = original_name.replace('_', ' ').replace('-', ' ')
                conservative_clean = ' '.join(conservative_clean.split())
                if (conservative_clean.lower()[0] == original_name.lower()[0] and 
                    conservative_clean.lower()[-1] == original_name.lower()[-1]):
                    cleaned = conservative_clean
                else:
                    # Fall back to minimal cleaning
                    cleaned = original_name.replace('_', ' ')
        
        # Title case for better readability
        if cleaned:
            cleaned = cleaned.title()
            
        return cleaned
    
    def _perform_technical_validation(self, vendor_human: str, vendor_machine: str,
                                    product_human: str, product_machine: str,
                                    version: str, target_sw: str, original_title: str) -> Dict:
        """
        Perform technical validation according to specified rules
        
        Args:
            vendor_human: Human-readable vendor name
            vendor_machine: Machine vendor name from CPE
            product_human: Human-readable product name  
            product_machine: Machine product name from CPE
            version: Version from CPE
            target_sw: Target software from CPE
            original_title: Original title from XML
            
        Returns:
            Dictionary with validation results
        """
        validation_details = []
        validation_passed = True
        
        # Rule 1: Vendor_Human has to start with the same character as Vendor_Machine (lowercase)
        if vendor_human and vendor_machine:
            if vendor_human.lower()[0] != vendor_machine.lower()[0]:
                validation_details.append(f"Vendor start char mismatch: '{vendor_human[0]}' vs '{vendor_machine[0]}'")
                validation_passed = False
            
            # Rule 2: Vendor_Human has to end with the same character as Vendor_Machine (lowercase)
            if vendor_human.lower()[-1] != vendor_machine.lower()[-1]:
                validation_details.append(f"Vendor end char mismatch: '{vendor_human[-1]}' vs '{vendor_machine[-1]}'")
                validation_passed = False
        
        # Rule 3: Product_Human has to start with the same character as Product_Machine (lowercase)
        if product_human and product_machine:
            if product_human.lower()[0] != product_machine.lower()[0]:
                validation_details.append(f"Product start char mismatch: '{product_human[0]}' vs '{product_machine[0]}'")
                validation_passed = False
            
            # Rule 4: Product_Human has to end with the same character as Product_Machine (lowercase)
            if product_human.lower()[-1] != product_machine.lower()[-1]:
                validation_details.append(f"Product end char mismatch: '{product_human[-1]}' vs '{product_machine[-1]}'")
                validation_passed = False
        
        # Rule 5: Construct title and compare with original
        constructed_title = self._construct_title(vendor_human, product_human, version, target_sw)
        
        # Normalize both titles for comparison (remove extra spaces, convert to lowercase)
        normalized_original = ' '.join(original_title.lower().split())
        normalized_constructed = ' '.join(constructed_title.lower().split())
        
        if normalized_constructed not in normalized_original:
            validation_details.append(f"Title mismatch: constructed '{constructed_title}' not found in '{original_title}'")
            validation_passed = False
        
        return {
            'validation_passed': validation_passed,
            'details': ' | '.join(validation_details) if validation_details else 'All validations passed',
            'constructed_title': constructed_title
        }
    
    def _construct_title(self, vendor_human: str, product_human: str, version: str, target_sw: str) -> str:
        """
        Construct title according to the rule:
        Vendor_Human + space + Product_Human + space + Version (except if "-") + space + "for" + space + Target_Software
        
        Args:
            vendor_human: Human-readable vendor name
            product_human: Human-readable product name
            version: Version (skip if "-")
            target_sw: Target software
            
        Returns:
            Constructed title string
        """
        parts = []
        
        # Add vendor if available
        if vendor_human and vendor_human != '*':
            parts.append(vendor_human)
        
        # Add product if available
        if product_human and product_human != '*':
            parts.append(product_human)
        
        # Add version if not "-" or "*"
        if version and version not in ['-', '*']:
            parts.append(version)
        
        # Add "for" + target software if target_sw is not "*"
        if target_sw and target_sw != '*':
            parts.extend(['for', target_sw])
        
        return ' '.join(parts)
    
    def _determine_category(self, cpe_data: Dict, title: str) -> str:
        """
        Determine the category based on CPE data and title
        
        Args:
            cpe_data: Parsed CPE data
            title: CPE title
            
        Returns:
            Category string
        """
        part = cpe_data.get('part', '').lower()
        target_sw = cpe_data.get('target_sw', '').lower()
        product = cpe_data.get('product', '').lower()
        title_lower = title.lower()
        
        # Determine category based on various factors
        if part == 'a':  # Application
            if any(term in target_sw for term in ['android', 'ios']):
                return 'Mobile Application'
            elif any(term in target_sw for term in ['node.js', 'nodejs']):
                return 'Node.js Package'
            elif any(term in target_sw for term in ['wordpress', 'drupal', 'joomla']):
                return 'CMS Plugin'
            elif any(term in title_lower for term in ['firmware', 'bios']):
                return 'Firmware'
            else:
                return 'Application'
        elif part == 'o':  # Operating System
            if any(term in product for term in ['firmware', 'bios']):
                return 'Firmware'
            else:
                return 'Operating System'
        elif part == 'h':  # Hardware
            return 'Hardware'
        else:
            return 'Unknown'
    
    def save_to_excel(self, df: pd.DataFrame, output_file: str = "cpe_data.xlsx"):
        """
        Save DataFrame to Excel file
        
        Args:
            df: DataFrame to save
            output_file: Output Excel file path
        """
        print(f"💾 Saving data to Excel file: {output_file}")
        
        try:
            # Define exact column order to match reference file
            column_order = [
                'cpe',
                'Title',
                'vendor_human',
                'product_human',
                'vendor_machine',  # Keep for reference/debugging
                'product_machine',  # Keep for reference/debugging
                'Validation Product Name',
                'part',
                'target_softwares',
                'target_hardwares',
                'versions',
                'updates',
                'editions',
                'languages',
                'references',
                'category',
                'validation_details',  # Technical validation results
                'constructed_title'    # Constructed title for validation
            ]
            
            # Ensure all required columns exist
            for col in column_order:
                if col not in df.columns:
                    df[col] = ''
            
            # Reorder columns to match reference
            df_ordered = df[column_order]
            
            # Convert array columns to string representation to match reference format
            array_columns = ['target_softwares', 'target_hardwares', 'versions', 'updates', 'editions', 'languages', 'references']
            for col in array_columns:
                if col in df_ordered.columns:
                    df_ordered[col] = df_ordered[col].apply(lambda x: str(x) if isinstance(x, list) else str([x]) if x else "['*']")
            
            # Save to Excel with formatting matching reference
            with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
                df_ordered.to_excel(writer, sheet_name='Sheet1', index=False)
                
                # Get the workbook and worksheet
                workbook = writer.book
                worksheet = writer.sheets['Sheet1']
                
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
                    
                    adjusted_width = min(max_length + 2, 60)  # Increased cap for validation details
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
        print("🚀 Starting CPE XML to Excel conversion with technical validation...")
        
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
        
        # Print summary statistics including validation
        self._print_summary_stats(df)
    
    def _print_summary_stats(self, df: pd.DataFrame):
        """Print summary statistics about the processed data"""
        print("\n📈 Summary Statistics:")
        print("=" * 50)
        
        total_items = len(df)
        print(f"✅ Total items processed: {total_items:,}")
        
        # Technical validation statistics
        if 'Validation Product Name' in df.columns:
            validation_passed = df['Validation Product Name'].sum()
            validation_rate = (validation_passed / total_items) * 100
            print(f"🔍 Technical validation passed: {validation_passed:,}/{total_items:,} ({validation_rate:.1f}%)")
            
            # Show common validation issues
            if 'validation_details' in df.columns:
                failed_validations = df[df['Validation Product Name'] == False]
                if len(failed_validations) > 0:
                    print(f"\n⚠️  Common validation issues:")
                    validation_issues = failed_validations['validation_details'].value_counts().head(5)
                    for issue, count in validation_issues.items():
                        if 'All validations passed' not in issue:
                            print(f"   - {issue}: {count} cases")
        
        if 'part' in df.columns:
            print(f"\n📊 CPE Parts distribution:")
            part_counts = df['part'].value_counts()
            for part, count in part_counts.items():
                if part:
                    part_name = {'a': 'Application', 'o': 'Operating System', 'h': 'Hardware'}.get(part, part)
                    print(f"   {part_name} ({part}): {count:,}")
        
        if 'vendor_human' in df.columns:
            unique_vendors = df['vendor_human'].nunique()
            print(f"\n🏢 Unique vendors: {unique_vendors:,}")
            
            top_vendors = df['vendor_human'].value_counts().head(5)
            print(f"   Top 5 vendors:")
            for vendor, count in top_vendors.items():
                if vendor and vendor != '*':
                    print(f"   - {vendor}: {count}")
        
        if 'category' in df.columns:
            print(f"\n📂 Categories:")
            category_counts = df['category'].value_counts()
            for category, count in category_counts.items():
                print(f"   {category}: {count:,}")
        
        print("=" * 50)

def main():
    """Main function to run the CPE processing"""
    print("🏃‍♂️ Running CPE Parser Tests...")
    test_cpe_parser()
    
    print("🔄 Starting XML to Excel Processing...")
    
    # Configuration
    xml_file = "official-cpe-dictionary_v2.3.xml"
    output_file = "cpe_data_sample.xlsx"
    sample_percentage = 0.01  # 1% for testing - change to 1.0 for 100%
    
    # Create processor and run
    processor = CPEXMLProcessor(xml_file, sample_percentage)
    processor.process_and_save(output_file)
    
    print(f"\n🎉 Process completed! Check '{output_file}' for results.")
    print(f"💡 To process all data, change sample_percentage to 1.0 in the main() function")

if __name__ == "__main__":
    main()