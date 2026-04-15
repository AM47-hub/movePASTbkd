from flask import Flask, request, make_response
import re, json, os
from datetime import datetime, timedelta

app = Flask(__name__)

@app.route('/ping', methods=['GET', 'HEAD'])
def health_check():
    return "Ready"

def fast_parse(text):
    # One-pass scanning instead of looping regex
    keywords = ["flat", "number", "beside", "suburb", "type", "rent", "rooms", "available", "viewing", "from", "until", "agency", "person", "mobile", "comments"]
    # Find all occurrences of keywords in one go
    pattern = re.compile(r'\b(' + '|'.join(keywords) + r')\b', re.I)
    matches = list(pattern.finditer(text))
    
    data = {k: "" for k in keywords}
    for i in range(len(matches)):
        start = matches[i].end()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        data[matches[i].group(1).lower()] = text[start:end].strip()
    return data

def quick_addr(t):
    u, n = t.get('flat',''), t.get('number','')
    # Simple digit replacement
    d = {'one':'1','two':'2','three':'3','four':'4','five':'5','six':'6','seven':'7','eight':'8','nine':'9','zero':'0','to':'2','for':'4','ate':'8'}
    for k, v in d.items():
        u = re.sub(rf'\b{k}\b', v, u, flags=re.I)
        n = re.sub(rf'\b{k}\b', v, n, flags=re.I)
    u, n = u.replace(" ","").upper(), n.replace(" ","").upper()
    pre = f"U{u}/{n}" if u else n
    # Standardize street and suburb
    full = f"{pre} {t.get('beside','')} {t.get('suburb','')}"
    full = re.sub(r'\s+', ' ', full).strip().title()
    # Basic abbreviations
    subs = {'Road':'Rd.','Street':'St.','Cresent':'Cres.','Place':'Pl.','Avenue':'Ave.','Lane':'Ln.','Highway':'Hwy.','Way':'Wy.'}
    for k, v in subs.items(): full = full.replace(k, v)
    return full

@app.route('/process', methods=['POST'])
def process():
    try:
        payload = request.get_json(force=True)
        raw = str(payload.get('text', '')).replace('\xa0', ' ').strip()
        
        # Initial check: did we even get text?
        if not raw: 
            return make_response(json.dumps({"debug_error": "No text received in payload"}), 200)
        
        segments = [s.strip() for s in raw.split('|') if 'Content:' in s]
        bkd_map, fnd_map = {}, {}
        skipped_blocks = []

        for seg in segments:
            try:
                content_split = seg.split('Content:', 1)
                if len(content_split) < 2:
                    skipped_blocks.append("Split failed: No 'Content:' marker found")
                    continue
                
                meta, body = content_split[0], content_split[1]
                
                # Use flexible regex for metadata
                src_match = re.search(r'Source:\s*(\S+)', meta, re.I)
                st_match = re.search(r'Status:\s*(\d{4}-\d{2}-\d{2})', meta, re.I)
                anc_match = re.search(r'Anchor:\s*([\d-T:+]+)', meta, re.I)

                if not all([src_match, st_match, anc_match]):
                    skipped_blocks.append(f"Meta missing: Src={bool(src_match)}, St={bool(st_match)}, Anc={bool(anc_match)}")
                    continue

                src = src_match.group(1)
                st_dt = datetime.strptime(st_match.group(1), '%Y-%m-%d').date()
                anc = anc_match.group(1)
                anc_dt = datetime.strptime(anc[:10], '%Y-%m-%d').date()

                toks = fast_parse(body)
                addr = quick_addr(toks)
                
                v_str = toks.get('viewing', '').lower()
                v_date = None
                dm = re.search(r'(\d{1,2})[/-](\d{1,2})', v_str)
                if dm: v_date = datetime(anc_dt.year, int(dm.group(2)), int(dm.group(1))).date()
                elif "tomorrow" in v_str: v_date = anc_dt + timedelta(days=1)
                elif "today" in v_str: v_date = anc_dt

                flag = "PAST" if v_date and v_date < st_dt else "FUTURE" if v_date else "UNKNOWN"
                
                entry = {"anchor": anc, "flag": flag, "addr_generated": addr, "v_date": str(v_date)}
                
                if "2Booked" in src:
                    bkd_map.setdefault(addr, []).append(entry)
                else:
                    fnd_map.setdefault(addr, []).append(entry)
            except Exception as e:
                skipped_blocks.append(f"Logic Error: {str(e)}")
                continue

        # THE DEBUG REPORT
        debug_report = {
            "summary": {
                "total_segments_found": len(segments),
                "booked_count": len(bkd_map),
                "found_count": len(fnd_map),
                "errors_encountered": len(skipped_blocks)
            },
            "addresses_in_booked": list(bkd_map.keys()),
            "addresses_in_found": list(fnd_map.keys()),
            "error_log": skipped_blocks[:5] # Show first 5 errors
        }

        return make_response(json.dumps(debug_report), 200, {"Content-Type": "application/json"})

    except Exception as e:
        return make_response(json.dumps({"fatal_crash": str(e)}), 200)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
