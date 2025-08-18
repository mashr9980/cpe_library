# cpe_resolver_ai.py
import re, json
from dataclasses import dataclass
from typing import Optional, Tuple, List

ORG_SUFFIXES = [
    "Software Foundation","Foundation","Corporation","Corp.","Corp","Inc.","Inc","LLC","Ltd.","Ltd","Limited","AG","GmbH","Systems","Technologies","Tech","Labs","Studio","Studios","Group","Team","Company","Project"
]

def _tok(s: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9\.\-]+", (s or "").lower())

def _affinity(a: str, b: str) -> float:
    A, B = set(_tok(a)), set(_tok(b))
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)

def _literal_in_title(s: Optional[str], title: str) -> bool:
    if not s:
        return False
    return s.lower() in title.lower()

@dataclass
class LLMExtraction:
    vendor_text: Optional[str]
    product_text: Optional[str]
    vendor_span: Optional[Tuple[int,int]]
    product_span: Optional[Tuple[int,int]]

class CpeVendorProductResolver:
    def __init__(self, azure):
        self.azure = azure

    async def resolve(self, title: str, vendor_machine: str, product_machine: str) -> Tuple[str, str]:
        llm = await self._ask_llm(title, vendor_machine, product_machine)
        if llm:
            vendor = self._from_span_or_text(title, llm.vendor_span, llm.vendor_text)
            product = self._from_span_or_text(title, llm.product_span, llm.product_text)
        else:
            vendor = product = None
        vendor, product = self._postprocess(title, vendor, product, vendor_machine, product_machine, llm)
        return vendor.strip(), product.strip()

    async def _ask_llm(self, title: str, vm: str, pm: str) -> Optional[LLMExtraction]:
        """
        Ask the LLM to extract exact vendor/product substrings and [start,end) spans from TITLE.
        - Returns LLMExtraction(vendor_text, product_text, vendor_span, product_span) or None on failure.
        - Guarantees substrings (if present) are exact slices of TITLE and spans are corrected to match.
        """

        def _strip_code_fences(s: str) -> str:
            # Remove ```json ... ``` or ``` ... ``` wrappers if present.
            s = s.strip()
            if s.startswith("```"):
                s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
                s = re.sub(r"\s*```$", "", s)
            return s.strip()

        def _as_tuple_or_none(x):
            return tuple(x) if isinstance(x, list) and len(x) == 2 else None

        def _normalize_none(v):
            # Convert "null" strings to None if any, leave others as-is
            return None if v in ("null", None) else v

        def _first_occurrence_span(haystack: str, needle: str):
            """Return [start,end) of the first exact occurrence of needle in haystack, or None."""
            if needle is None:
                return None
            idx = haystack.find(needle)
            return (idx, idx + len(needle)) if idx != -1 else None

        def _span_matches_text(haystack: str, span, text: str) -> bool:
            if span is None or text is None:
                return False
            s, e = span
            if not (0 <= s <= e <= len(haystack)):
                return False
            return haystack[s:e] == text

        system = (
            "You extract EXACT vendor and product spans from a software/hardware TITLE. "
            "Output STRICT JSON with keys: vendor_text, product_text, vendor_span, product_span. "
            "Spans are [start,end) character offsets into TITLE, zero-based. "
            "Never add fields. Never include prose. Never include markdown. "
            "If a value is unknown, set that value to null."
        )

        user = f'''
            TITLE: {title}
            MACHINE_VENDOR: {vm}
            MACHINE_PRODUCT: {pm}

            INSTRUCTIONS:
            1) Return EXACT substrings from TITLE for both vendor_text and product_text. Preserve case and spacing from TITLE.
            2) Also return [start,end) character offsets for each in vendor_span and product_span. Offsets must map to the first exact occurrence of the returned text in TITLE. If you cannot determine one, set that one to null.
            3) Use MACHINE_VENDOR and MACHINE_PRODUCT only as HINTS to locate likely spans. Treat underscores as spaces and match case-insensitively, but ALWAYS return substrings that actually appear in TITLE.
            4) VENDOR selection:
            - Prefer the full organization/brand name as written in TITLE, including suffixes like "Inc.", "LLC", "Ltd" if present.
            - Patterns to recognize: 
                a) "Vendor Product"
                b) "Product by Vendor"
                c) "Vendor - Product" / "Vendor: Product" / "Vendor | Product"
                d) "Vendor's Product" (possessive: vendor is text before "'s").
            - If vendor tokens repeat, use the first full occurrence.
            - If vendor includes a parenthetical acronym, EXCLUDE the parentheses and their contents from vendor_text.
            5) PRODUCT selection (must be a CONTIGUOUS substring from TITLE):
            - Aim for the concrete product/feature/plugin/app name as written in TITLE.
            - Keep internal model codes/hyphenated tokens (e.g., "A5000", "XPS-13", "MX-100").
            - TRUNCATE BEFORE trailing non-name material, including (case-insensitive): 
                versions (e.g., "1.2.3", "v2", "version 4", "2024", "build 1234", "RC", "Beta", "Alpha"),
                edition/variant terms ("Pro", "Professional", "Lite", "Community", "Enterprise", "Ultimate", "Trial", "Free", "LTS"),
                platform/target qualifiers ("for WordPress", "for Windows", "on Linux", "for Chrome", "for Shopify"),
                architecture/bitness ("x64", "x86", "32-bit", "64-bit").
            - If such tokens appear, the product_text ends immediately before them.
            6) If vendor and product would be identical, choose the shorter realistic vendor_text and a longer, more descriptive product_text (e.g., include the next specific token).
            7) NEVER invent or normalize beyond what appears in TITLE. Output must be exact substrings of TITLE.
            8) Do not include leading/trailing whitespace in the extracted substrings.

            JSON only:
            {{
            "vendor_text": "... or null",
            "product_text": "... or null",
            "vendor_span": [start, end] or null,
            "product_span": [start, end] or null
            }}

            EXAMPLES (illustrative):
            - TITLE: "10web Photo Gallery 1.4.17 WordPress"
            -> vendor_text = "10web"; product_text = "Photo Gallery"
            - TITLE: "GS Plugins GS Pinterest portfolio 2.0.6 Pro Edition for WordPress"
            -> vendor_text = "GS Plugins"; product_text = "GS Pinterest portfolio"
            '''.strip()

        try:
            # Prefer JSON-mode if your Azure deployment supports it; otherwise it will be ignored harmlessly.
            resp = await self.azure.chat.completions.create(
                model="cpe-extractor",
                messages=[{"role": "system", "content": system},
                        {"role": "user", "content": user}],
                max_tokens=220,
                # response_format={"type": "json_object"}  # Uncomment if your Azure deployment supports JSON mode.
            )

            raw = resp.choices[0].message.content
            raw = _strip_code_fences(raw)

            # Strict JSON load
            data = json.loads(raw)

            vendor_text = _normalize_none(data.get("vendor_text"))
            product_text = _normalize_none(data.get("product_text"))
            vendor_span = _as_tuple_or_none(data.get("vendor_span"))
            product_span = _as_tuple_or_none(data.get("product_span"))

            # Normalize empty strings to None
            vendor_text = vendor_text if vendor_text not in ("", None) else None
            product_text = product_text if product_text not in ("", None) else None

            # Validate/correct spans so they always match TITLE slices
            if vendor_text is not None:
                if not _span_matches_text(title, vendor_span, vendor_text):
                    vendor_span = _first_occurrence_span(title, vendor_text)
            else:
                vendor_span = None

            if product_text is not None:
                if not _span_matches_text(title, product_span, product_text):
                    product_span = _first_occurrence_span(title, product_text)
            else:
                product_span = None

            # Final guard: if spans still invalid or text not found, null them
            if vendor_span is not None and not _span_matches_text(title, vendor_span, vendor_text):
                vendor_span = None
            if product_span is not None and not _span_matches_text(title, product_span, product_text):
                product_span = None

            def _span_tuple(x):
                return tuple(x) if isinstance(x, tuple) and len(x) == 2 else None

            return LLMExtraction(
                vendor_text=vendor_text,
                product_text=product_text,
                vendor_span=_span_tuple(vendor_span),
                product_span=_span_tuple(product_span),
            )

        except Exception:
            return None

    @staticmethod
    def _from_span_or_text(title: str, span: Optional[Tuple[int,int]], text: Optional[str]) -> Optional[str]:
        if span:
            a,b = span
            if 0 <= a < b <= len(title):
                return title[a:b]
        return text

    @staticmethod
    def _strip_vendor_parenthetical_acronym(s: Optional[str]) -> Optional[str]:
        if not s:
            return s
        return re.sub(r"\s*\([A-Za-z0-9\-\._]+\)\s*$", "", s).strip()

    @staticmethod
    def _expand_vendor_suffix_if_present(title: str, vendor: Optional[str]) -> Optional[str]:
        if not vendor:
            return vendor
        i = title.lower().find(vendor.lower())
        if i < 0:
            return vendor
        j = i + len(vendor)
        tail = title[j:]
        for suf in sorted(ORG_SUFFIXES, key=len, reverse=True):
            m = re.match(r"\s+" + re.escape(suf) + r"\b", tail)
            if m:
                return title[i:j + m.end()].strip()
        return vendor

    @staticmethod
    def _keep_product_model_codes(product: Optional[str]) -> Optional[str]:
        if not product:
            return product
        p = re.sub(r"\s+(?:v|version)\s*\d[\w\.\(\)\-]*$", "", product, flags=re.I)
        p = re.sub(r"\s+[0-9]+\.[0-9][\w\.\-]*$", "", p)
        p = re.sub(r"\s+(?:build|beta|alpha|rc)\b.*$", "", p, flags=re.I)
        return p.strip()

    @staticmethod
    def _humanize_from_machine_in_title(title: str, machine: str) -> Optional[str]:
        if not machine:
            return None
        toks = [re.escape(t) for t in re.split(r"[_\-]", machine) if t]
        if not toks:
            return None
        pattern = r"\b" + r"(?:[\s\-/]*?)".join(toks) + r"\b"
        m = re.search(pattern, title, flags=re.I)
        return m.group(0) if m else None

    @staticmethod
    def _vendor_from_prefix_before_product(title: str, product_span: Optional[Tuple[int,int]]) -> Optional[str]:
        if not product_span:
            return None
        start = product_span[0]
        if start <= 0:
            return None
        candidate = title[:start].strip()
        candidate = re.sub(r"[\-\u2013:]+$", "", candidate).strip()
        candidate = re.sub(r"\s{2,}", " ", candidate)
        return candidate or None

    @staticmethod
    def _prefer_different(vendor: Optional[str], product: Optional[str], vm: str, pm: str) -> Tuple[Optional[str], Optional[str]]:
        if vendor and product and vendor.strip().lower() == product.strip().lower() and set(_tok(vm)) != set(_tok(pm)):
            parts = vendor.split()
            vendor2 = parts[0] if parts else vendor
            return vendor2, product
        return vendor, product

    def _postprocess(self, title: str, vendor: Optional[str], product: Optional[str], vm: str, pm: str, llm: Optional[LLMExtraction]) -> Tuple[str, str]:
        vendor = self._strip_vendor_parenthetical_acronym(vendor)
        vendor = self._expand_vendor_suffix_if_present(title, vendor)
        product = self._keep_product_model_codes(product)
        if not _literal_in_title(vendor, title) and llm and llm.product_span:
            v2 = self._vendor_from_prefix_before_product(title, llm.product_span)
            if v2:
                vendor = v2
        if (not vendor or _affinity(vendor, vm) < 0.15) and _literal_in_title(vendor, title):
            pass
        elif not vendor or _affinity(vendor, vm) < 0.15:
            v3 = self._humanize_from_machine_in_title(title, vm)
            if v3:
                vendor = v3
        if (not product or _affinity(product, pm) < 0.15) and _literal_in_title(product, title):
            pass
        elif not product or _affinity(product, pm) < 0.15:
            p2 = self._humanize_from_machine_in_title(title, pm)
            if p2:
                product = p2
        vendor, product = self._prefer_different(vendor, product, vm, pm)
        vendor = (vendor or vm).strip()
        product = (product or pm).strip()
        return vendor, product
