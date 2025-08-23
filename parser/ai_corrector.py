import json
import logging
import requests
import asyncio
from typing import Dict

logger = logging.getLogger(__name__)

class OpenAICorrector:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.openai.com/v1/chat/completions"
        
    async def correct_extraction(self, cpe: str, title: str, vendor_machine: str, 
                               product_machine: str, part: str = "a", target_sw: str = "*") -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        schema = {
            "type": "object",
            "properties": {
                "vendor_name": {"type": "string", "minLength": 1},
                "product_name": {"type": "string", "minLength": 1},
                "reason": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1}
            },
            "required": ["vendor_name", "product_name"],
            "additionalProperties": False
        }
        
        fewshot_messages = [
            {
                "role": "system",
                "content": "You are a strict normalizer for CPE 2.3 records. Your job: given a CPE string, title, and machine vendor/product, output canonical human-readable vendor and product names that match NVD conventions.\n\nRules:\n1) Vendor (human):\n   - Derive the canonical organization brand (no legal suffixes like Inc., LLC, Ltd unless core brand; no \"Project\", \"Team\", \"Foundation\", \"innovations\", \"group\").\n   - Prefer the name as it appears in the TITLE if it clearly maps to the machine vendor.\n   - Use brand-accurate casing (e.g., \"JetBrains\", \"NoScript\", \"DataSpell\", \"HP\", \"Cisco\", \"Microsoft\", \"Tableau\", \"Maxthon\", \"Atlassian\", \"AWSM\").\n   - Must stay semantically aligned to vendor_machine tokens. Do not switch vendors.\n\n2) Product (human):\n   - Must correspond to product_machine. Do not change products across families.\n   - Remove version/build/update/edition/platform words (numbers, rc/beta/alpha, Pro/Enterprise/Lite/Community, 32-bit/x64/ARM64, for/on <platform>).\n   - Keep \"Firmware\" ONLY when product_machine contains \"firmware\" or the title clearly denotes firmware.\n   - Keep brand/product capitalization from common usage (e.g., \"Windows 10 1709\", \"Confluence\", \"Jitsi Meet\", \"Betheme\", \"Embed Any Document\", \"DataSpell\", \"Tableau Server\").\n   - Do NOT include target platform words like WordPress/Android/Node.js/Confluence in the product (those belong to target_sw).\n\n3) Special mappings & notes:\n   - If machine vendor looks like a domain/concatenation (e.g., tableausoftware) but the title brand is clearly \"Tableau\", use \"Tableau\".\n   - If title contains longer legal names (e.g., \"Tableau Software\"), prefer the short brand form (\"Tableau\").\n   - Acronyms stay uppercase (HP, IBM, AWS).\n\n4) Validation:\n   - Output must stay consistent with vendor_machine/product_machine tokens (don't swap to different brands).\n   - Never return empty strings.\n\nReturn clean JSON following the schema with short reasons and a confidence score (0–1)."
            },
            {
                "role": "user",
                "content": "Input:\nCPE: cpe:2.3:a:awsm:embed_any_document:2.3.1:*:*:*:*:wordpress:*:*\nTitle: awsm innovations Embed Any Document 2.3.1 for WordPress\nvendor_machine: awsm\nproduct_machine: embed_any_document\npart: a\ntarget_sw: wordpress"
            },
            {
                "role": "assistant",
                "content": "{\"vendor_name\":\"AWSM\",\"product_name\":\"Embed Any Document\",\"reason\":\"Title shows brand \\\"awsm innovations\\\" but canonical brand is AWSM; product is the plugin name without WordPress/version.\",\"confidence\":0.94}"
            },
            {
                "role": "user",
                "content": "Input:\nCPE: cpe:2.3:o:intel:nuc_11_pro_kit_nuc11tnhi30z_firmware:tntgl357.0059:*:*:*:*:*:*:*\nTitle: Intel NUC 11 Pro Kit NUC11TNHI30Z Firmware TNTGL357.0059\nvendor_machine: intel\nproduct_machine: nuc_11_pro_kit_nuc11tnhi30z_firmware\npart: o\ntarget_sw: *"
            },
            {
                "role": "assistant",
                "content": "{\"vendor_name\":\"Intel\",\"product_name\":\"NUC 11 Pro Kit NUC11TNHI30Z Firmware\",\"reason\":\"Machine product includes firmware; keep Firmware in human product; remove version/update.\",\"confidence\":0.96}"
            },
            {
                "role": "user",
                "content": "Input:\nCPE: cpe:2.3:a:tableausoftware:tableau_server:8.1.1:*:*:*:*:*:*:*\nTitle: Tableau Software Tableau Server 8.1.1\nvendor_machine: tableausoftware\nproduct_machine: tableau_server\npart: a\ntarget_sw: *"
            },
            {
                "role": "assistant",
                "content": "{\"vendor_name\":\"Tableau\",\"product_name\":\"Tableau Server\",\"reason\":\"Normalize vendor to the brand \\\"Tableau\\\"; product is \\\"Tableau Server\\\" without version.\",\"confidence\":0.93}"
            },
            {
                "role": "user",
                "content": f"Input:\nCPE: {cpe}\nTitle: {title}\nvendor_machine: {vendor_machine}\nproduct_machine: {product_machine}\npart: {part}\ntarget_sw: {target_sw}"
            }
        ]
        
        payload = {
            "model": "gpt-5",
            "messages": fewshot_messages,
            "response_format": {"type": "json_schema", "json_schema": {"name": "extraction", "schema": schema}},
            "max_tokens": 200,
            "temperature": 0.0
        }
        
        try:
            def make_request():
                response = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
                response.raise_for_status()
                return response.json()
            
            result = await asyncio.to_thread(make_request)
            content = result["choices"][0]["message"]["content"]
            data = json.loads(content)
            
            return {
                "vendor_name": data.get("vendor_name", "").strip(),
                "product_name": data.get("product_name", "").strip()
            }
        except Exception as e:
            logger.error(f"OpenAI correction failed: {e}")
            return {"vendor_name": "", "product_name": ""}