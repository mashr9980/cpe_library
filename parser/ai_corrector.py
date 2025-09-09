import json
import logging
import requests
import asyncio
from typing import Dict, List

logger = logging.getLogger(__name__)

class OpenAICorrector:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.openai.com/v1/chat/completions"
    
    async def extract_vendor_product_batch(self, items: List[Dict]) -> List[Dict]:
        if not items:
            return []
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        batch_input = []
        for idx, item in enumerate(items):
            batch_input.append({
                "id": idx,
                "cpe": item.get('cpe', ''),
                "title": item.get('title', ''),
                "vendor_machine": item.get('vendor_machine', ''),
                "product_machine": item.get('product_machine', ''),
                "part": item.get('part', 'a')
            })
        
        system_prompt = """You are a CPE expert processing vendor/product name extraction. Extract clean, human-readable names that align with machine identifiers.

CRITICAL RULES:
1. Extract vendor and product names from the TITLE
2. Vendor and product names must start and end with same characters as machine identifiers (case-insensitive)
3. Remove version numbers, edition info, and target platform info from product names
4. Product names should not include "for WordPress", "for Windows", etc.
5. Preserve proper capitalization and spacing

OUTPUT: JSON array [{"id": int, "vendor_name": "string", "product_name": "string"}]"""

        user_content = f"Extract vendor and product names from these CPE entries:\n\n{json.dumps(batch_input, indent=2)}"
        
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": 2000,
            "temperature": 0.0
        }
        
        try:
            def make_request():
                response = requests.post(self.base_url, headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                return response.json()
            
            result = await asyncio.to_thread(make_request)
            content = result["choices"][0]["message"]["content"]
            
            if content.startswith('```json'):
                content = content[7:-3]
            elif content.startswith('```'):
                content = content[3:-3]
            
            extracted_data = json.loads(content)
            
            results = []
            for item in extracted_data:
                if isinstance(item, dict) and item.get('id', -1) < len(items):
                    results.append({
                        'vendor_name': item.get('vendor_name', '').strip(),
                        'product_name': item.get('product_name', '').strip()
                    })
                else:
                    results.append({'vendor_name': '', 'product_name': ''})
            
            while len(results) < len(items):
                results.append({'vendor_name': '', 'product_name': ''})
            
            return results[:len(items)]
            
        except Exception as e:
            logger.error(f"OpenAI batch extraction failed: {e}")
            return [{'vendor_name': '', 'product_name': ''} for _ in items]
    
    async def correct_extraction(self, cpe: str, title: str, vendor_machine: str, 
                               product_machine: str, part: str = "a", target_sw: str = "*") -> Dict[str, str]:
        items = [{
            'cpe': cpe,
            'title': title,
            'vendor_machine': vendor_machine,
            'product_machine': product_machine,
            'part': part
        }]
        
        results = await self.extract_vendor_product_batch(items)
        if results:
            return results[0]
        else:
            return {"vendor_name": "", "product_name": ""}