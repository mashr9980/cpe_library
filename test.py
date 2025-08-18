# azure_oai_check_v3.py
import os, json, argparse, logging, requests, sys
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s | %(levelname)-8s | %(message)s")
log = logging.getLogger("azure-oai-check")

def redact(s): return s[:4]+"..."+s[-4:] if s and len(s)>8 else "***"

def call(endpoint, key, payload, tag):
    headers = {"Content-Type":"application/json","api-key":key}
    log.info(f"[{tag}] POST {endpoint}")
    log.debug(f"[{tag}] Payload: {json.dumps(payload, ensure_ascii=False)}")
    r = requests.post(endpoint, headers=headers, data=json.dumps(payload), timeout=60)
    log.info(f"[{tag}] HTTP {r.status_code}")
    log.debug(f"[{tag}] Raw: {r.text}")
    r.raise_for_status()
    j = r.json()
    choice = (j.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content")
    fr = choice.get("finish_reason")
    log.info(f"[{tag}] finish_reason={fr} model={j.get('model')} usage={j.get('usage')}")
    log.info(f"[{tag}] content={repr(content)}")
    return content, j

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--key", required=True)
    args = ap.parse_args()

    log.info("Endpoint: %s", args.endpoint)
    log.info("API key : %s", redact(args.key))

    p1 = {
        "messages":[
            {"role":"system","content":"You are a minimal echo test. Reply with exactly: OK"},
            {"role":"user","content":"OK"}
        ],
        "response_format":{"type":"text"},
        "max_completion_tokens": 64,
        "seed": 1
    }
    try:
        c1,_ = call(args.endpoint, args.key, p1, "probe-text")
    except Exception as e:
        log.error("Probe 1 failed: %s", e); c1=None

    p2 = {
        "messages":[
            {"role":"system","content":"Return strict JSON only with keys a and b. No extra text."},
            {"role":"user","content":"Output exactly this JSON: {\"a\":\"ping\",\"b\":\"pong\"}"}
        ],
        "response_format":{"type":"json_object"},
        "max_completion_tokens": 128,
        "seed": 1
    }
    try:
        c2,_ = call(args.endpoint, args.key, p2, "probe-json")
    except Exception as e:
        log.error("Probe 2 failed: %s", e); c2=None

    p3 = {
        "messages":[
            {"role":"system","content":"Say READY only."},
            {"role":"user","content":"READY"}
        ],
        "response_format":{"type":"text"},
        "max_completion_tokens": 256,
        "seed": 1
    }
    try:
        c3,_ = call(args.endpoint, args.key, p3, "probe-text-wide")
    except Exception as e:
        log.error("Probe 3 failed: %s", e); c3=None

    ok = any([c1, c2, c3])
    logging.info("Success flags: text=%s json=%s text-wide=%s", bool(c1), bool(c2), bool(c3))
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
