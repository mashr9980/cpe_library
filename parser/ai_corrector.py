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
        
        system_prompt = """You are a CPE expert processing 1.4M+ records. Extract vendor/product names with PERFECT machine identifier alignment.

CRITICAL ALIGNMENT RULES:
1. EXACT CHARACTER MAPPING:
   - "fahadmahmood8" → "Fahadmahmood8" (preserve ALL characters including numbers)
   - "sphider-plus" → "Sphider-plus" (preserve hyphens and exact casing)  
   - "yaml-rust_project" → "Yaml-rust Project" (hyphens stay, underscores→spaces)
   - "hyper" → "Hyper" (capitalize but maintain length)

2. MANDATORY VALIDATION ALIGNMENT:
   - vendor_human[0].lower() MUST equal vendor_machine[0]
   - vendor_human[-1].lower() MUST equal vendor_machine[-1]
   - Same for products - THIS IS CRITICAL

3. INTELLIGENT VENDOR=PRODUCT HANDLING:
   When machines are identical ("hyper"/"hyper"):
   - Check title context for differentiation clues
   - Add minimal suffix that maintains end-character alignment
   - "hyper 0.12.34" → vendor="Hyper", product="Hyper HTTP" (both end with 'r')
   - "sphider-plus sphider-plus" → vendor="Sphider-plus", product="Sphider-plus Search" (both end with 's')

4. CONTEXT-AWARE SUFFIXES (only if alignment preserved):
   - HTTP libraries: "HTTP", "Client"  
   - Search tools: "Search", "Engine"
   - Frameworks: "Framework", "Library"
   - Platforms: "Platform", "System"
   - Only add if final character still aligns with machine

5. SMART EXAMPLES:
   - "Fahad Mahmood..." + machine="fahadmahmood8" → "Fahadmahmood8" (keep number for alignment)
   - "Sphider-plus Sphider-plus 1.0" + machines="sphider-plus"/"sphider-plus" → "Sphider-plus"/"Sphider-plus" (same since machines identical)
   - "hyper 0.12.34 for Rust" + machines="hyper"/"hyper" → "Hyper"/"Hyper" (simple case)
   - "Apache Software Foundation RocketMQ" + machines="apache"/"rocketmq" → "Apache"/"Rocketmq"

6. FALLBACK STRATEGY:
   - If unsure about suffix, keep vendor=product identical
   - Perfect alignment > differentiation
   - Never break character validation for naming

OUTPUT: JSON array [{"id": int, "vendor_name": "string", "product_name": "string"}]
GUARANTEE: 100% character alignment validation success."""

        user_content = f"Extract vendor and product names from these CPE entries according to standards:\n\n{json.dumps(batch_input, indent=2)}"
        
        payload = {
            "model": "gpt-5",
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