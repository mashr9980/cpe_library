# from cpe_parser import CpeBuilder, CpeParser, Part, LogicalValue

from cpe_builder import CpeBuilder
from cpe_parser import CpeParser
from values.part import Part


def test_cpe_parser():
    """Test the CPE parser functionality"""
    print("=== CPE Parser Testing ===")
    
    # Example usage from the original Java code
    builder = CpeBuilder()
    apache = builder.part(Part.APPLICATION).vendor("apache").build()
    
    parsed = CpeParser.parse("cpe:2.3:a:apache:commons-text:1.6:*:*:*:*:*:*:*")
    
    if apache.matches(parsed):
        print("✅ Parsed CPE value is an application CPE for the vendor 'apache'")
    
    # Test some conversions
    print(f"CPE 2.3 FS: {parsed.to_cpe23_fs()}")
    print(f"CPE 2.2 URI: {parsed.to_cpe22_uri()}")
    
    # Test builder pattern
    cpe = (CpeBuilder()
           .part(Part.APPLICATION)
           .vendor("microsoft")
           .product("internet_explorer")
           .version("8.0.6001")
           .update("beta")
           .build())
    
    print(f"Built CPE: {cpe}")
    
    # Test parsing different formats
    cpe22 = CpeParser.parse("cpe:/a:hiox_india:guest_book:4.0")
    print(f"Parsed CPE 2.2: {cpe22}")
    
    cpe23 = CpeParser.parse("cpe:2.3:a:hiox_india:guest_book:4.0:*:*:*:*:*:*:*")
    print(f"Parsed CPE 2.3: {cpe23}")
    
    # Test matching
    print(f"CPE 2.2 matches CPE 2.3: {cpe22.matches(cpe23)}")
    print()

if __name__ == "__main__":
    test_cpe_parser()