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
        
        if not raw: 
            return make_response(json.dumps([]), 200)
        
        segments = [s.strip() for s in raw.split('|') if 'Content:' in s]
        bkd_map, fnd_map = {}, {}

        for seg in segments:
            try:
                content_split = seg.split('Content:', 1)
                if len(content_split) < 2: continue
                
                meta, body = content_split[0], content_split[1]
                
                src_match = re.search(r'Source:\s*(\S+)', meta, re.I)
                st_match = re.search(r'Status:\s*(\d{4}-\d{2}-\d{2})', meta, re.I)
                # FIXED REGEX: The hyphen is now at the start [-...] to avoid range errors
                anc_match = re.search(r'Anchor:\s*([\d\-T:+]+)', meta, re.I)

                # Extract clean date strings from the metadata dictionary 'd' or matches
                st_str = d.get('status', '').strip()
                anc_raw = d.get('anchor', '').strip()
                
                # FIX: Split the Anchor at 'T' to isolate the YYYY-MM-DD
                anc_clean = anc_raw.split('T')[0]

                # Convert to Python date objects safely
                st_dt = datetime.strptime(st_str, '%Y-%m-%d').date()
                anc_dt = datetime.strptime(anc_clean, '%Y-%m-%d').date()
                
                if not all([src_match, st_match, anc_match]):
                    continue

                src = src_match.group(1)
                st_dt = datetime.strptime(st_match.group(1), '%Y-%m-%d').date()
                anc = anc_match.group(1)
                # Ensure we only take the YYYY-MM-DD part for the anchor date
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
                
                entry = {"anchor": anc, "flag": flag, "must": "must book" in v_str}
                
                if "2Booked" in src:
                    bkd_map.setdefault(addr, []).append(entry)
                else:
                    fnd_map.setdefault(addr, []).append(entry)
            except:
                continue

        results = []
        for addr, b_list in bkd_map.items():
            if all(b['flag'] == "PAST" for b in b_list):
                f_list = fnd_map.get(addr, [])
                if f_list:
                    match_f = [f for f in f_list if f['must']] if len(f_list) > 1 else f_list
                    results.append({
                        "bkd_anchors": [b['anchor'] for b in b_list],
                        "fnd_anchors": [f['anchor'] for f in match_f]
                    })

        return make_response(json.dumps(results), 200, {"Content-Type": "application/json"})

    except Exception as e:
        return make_response(json.dumps([{"fatal_crash": str(e)}]), 200)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
