from flask import Flask, request, make_response
import re
import json
from datetime import datetime, timedelta
import os

app = Flask(__name__)

@app.route('/ping', methods=['GET', 'HEAD'])
def health_check():
    return make_response("Ready", 200)

def parse_content(body_text):
    keywords = ["flat", "number", "beside", "suburb", "type", "rent", "rooms", "available", "viewing", "from", "until", "agency", "person", "mobile", "comments"]
    found_tokens = []
    for kw in keywords:
        for match in re.finditer(rf'\b{kw}\b', body_text, re.IGNORECASE):
            found_tokens.append({'key': kw.lower(), 'start': match.start(), 'end': match.end()})
    found_tokens.sort(key=lambda x: x['start'])
    res_data = {k: "" for k in keywords}
    for i in range(len(found_tokens)):
        current = found_tokens[i]
        v_start = current['end']
        v_end = found_tokens[i+1]['start'] if i + 1 < len(found_tokens) else len(body_text)
        res_data[current['key']] = body_text[v_start:v_end].strip()
    return res_data

def format_address(tokens):
    unit, num = tokens.get('flat', ''), tokens.get('number', '')
    rep = {r'\bone\b':'1', r'\btwo\b':'2', r'\bthree\b':'3', r'\bfour\b':'4', r'\bfive\b':'5', r'\bsix\b':'6', r'\bseven\b':'7', r'\beight\b':'8', r'\bnine\b':'9', r'\bzero\b':'0', r'\bto\b':'2', r'\bfor\b':'4', r'\bate\b':'8'}
    for p, r in rep.items():
        unit = re.sub(p, r, unit, flags=re.I)
        num = re.sub(p, r, num, flags=re.I)
    unit, num = unit.replace(" ", "").upper(), num.replace(" ", "").upper()
    num = re.sub(r'\s+dash\s+', '-', num, flags=re.I)
    prefix = f"U{unit}/{num}" if unit else num
    beside = re.sub(r'^the\s+kingsway', 'Kingsway', tokens.get('beside', ''), flags=re.I)
    full = f"{prefix} {beside} {tokens.get('suburb', '')}"
    subs = {r'\broad\b':'Rd.', r'\bstreet\b':'St.', r'\bcresent\b':'Cres.', r'\bplace\b':'Pl.', r'\bclose\b':'Cl.', r'\bavenue\b':'Ave.', r'\blane\b':'Ln.', r'\bhighway\b':'Hwy.', r'\bway\b':'Wy.', r'\brow\b':'Rw.'}
    for p, r in subs.items(): full = re.sub(p, r, full, flags=re.I)
    return re.sub(r'\s+', ' ', full).strip().title()

def extract_viewing_date(v_str, anchor_date):
    if not v_str: return None
    v_str = v_str.lower()
    d_m = re.search(r'(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?', v_str)
    if d_m:
        d, m = int(d_m.group(1)), int(d_m.group(2))
        y = int(d_m.group(3)) if d_m.group(3) else anchor_date.year
        if y < 100: y += 2000
        return datetime(y, m, d).date()
    months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
    abs_m = re.search(r'(\d+)(?:st|nd|rd|th)?\s*(?:of\s*)?([a-z]{3,})', v_str)
    if abs_m and abs_m.group(2)[:3] in months:
        return datetime(anchor_date.year, months[abs_m.group(2)[:3]], int(abs_m.group(1))).date()
    if any(w in v_str for w in ["today", "this morning", "this afternoon"]): return anchor_date
    if "tomorrow" in v_str: return anchor_date + timedelta(days=1)
    d_map = {"mon":0, "tue":1, "wed":2, "thu":3, "fri":4, "sat":5, "sun":6}
    rel_m = re.search(r'(this|next)?\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)', v_str)
    if rel_m:
        target = d_map[rel_m.group(2)[:3]]
        diff = (target - anchor_date.weekday()) % 7
        if diff == 0: diff = 7
        return anchor_date + timedelta(days=diff)
    return None

@app.route('/process', methods=['POST'])
def process():
    # 1. Cautious JSON Loading
    try:
        req_data = request.get_json(force=True)
        if not req_data:
            return make_response(json.dumps([]), 200)
        raw_text = req_data.get('text', '')
    except Exception:
        return make_response(json.dumps([]), 200)

    # 2. Cleanup
    raw_text = str(raw_text).replace('\xa0', ' ').replace('\u202f', ' ').strip()
    segments = [s.strip() for s in raw_text.split('|') if s.strip()]
    
    bkd_list = []
    fnd_list = []

    for seg in segments:
        try:
            src_m = re.search(r'Source:\s*(\S+)', seg, re.I)
            st_m = re.search(r'Status:\s*(\d{4}-\d{2}-\d{2})', seg, re.I)
            a_m = re.search(r'Anchor:\s*([\d-T:+]+)', seg, re.I)
            c_m = re.search(r'Content:\s*(.*)', seg, re.I | re.S)

            if all([src_m, st_m, a_m, c_m]):
                src_type = src_m.group(1)
                status_dt = datetime.strptime(st_m.group(1), '%Y-%m-%d').date()
                
                # REPLACEMENT: Safer date parsing for older Python versions
                anchor_str = a_m.group(1).split('+')[0].split('Z')[0] 
                anchor_dt = datetime.strptime(anchor_str[:10], '%Y-%m-%d').date()
                
                toks = parse_content(c_m.group(1).strip())
                v_date = extract_viewing_date(toks.get('viewing', ''), anchor_dt)
                
                flag = "UNKNOWN"
                if v_date:
                    if v_date < status_dt: flag = "PAST"
                    elif v_date == status_dt: flag = "TODAY"
                    else: flag = "FUTURE"
                
                obj = {"anchor": a_m.group(1), "address": format_address(toks), "tokens": toks, "dayflag": flag}
                
                if "2Booked" in src_type:
                    bkd_list.append(obj)
                else:
                    fnd_list.append(obj)
        except:
            continue

    # 3. Aggressive Comparison logic
    results = []
    b_groups = {}
    for n in bkd_list:
        b_groups.setdefault(n['address'], []).append(n)
        
    f_groups = {}
    for n in fnd_list:
        f_groups.setdefault(n['address'], []).append(n)

    for addr, group in b_groups.items():
        if all(n['dayflag'] == "PAST" for n in group):
            f_matches = f_groups.get(addr, [])
            valid_f = []
            if len(f_matches) == 1:
                valid_f = f_matches
            elif len(f_matches) > 1:
                valid_f = [n for n in f_matches if "must book" in n['tokens'].get('viewing', '').lower()]
            
            results.append({
                "bkd_anchors": [n['anchor'] for n in group],
                "fnd_anchors": [n['anchor'] for n in valid_f] if valid_f else []
            })

    return make_response(json.dumps(results), 200, {"Content-Type": "application/json"})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
