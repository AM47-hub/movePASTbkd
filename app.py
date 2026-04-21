from flask import Flask, request, make_response
import re
import json
from datetime import datetime, timedelta
import os

app = Flask(__name__)

@app.route('/ping', methods=['GET', 'HEAD'])
def health_check():
    return make_response("Ready", 200)

def fast_parse(text):
    keywords = [
        "flat", "number", "beside", "suburb", "type", "rent", "rooms", 
        "available", "viewing", "from", "until", "agency", 
        "person", "mobile", "comments"
    ]
    delimit = re.compile(r'\b(' + '|'.join(keywords) + r')\b', re.I)
    chunks = list(delimit.finditer(text))

    raw_vals = {k: "" for k in keywords}
    for i in range(len(chunks)):
        start = chunks[i].end()
        if i + 1 < len(chunks):
            end = chunks[i+1].start()
        else:
            end = len(text)
        raw_vals[chunks[i].group(1).lower()] = text[start:end].strip()
    return raw_vals

def quick_addr(tokens):
    unit = tokens.get('flat', '')
    numb = tokens.get('number', '')
    
    unit = unit.replace(" ", "").upper()
    numb = numb.replace(" ", "").upper()

    if unit:
        location = f"U{unit}/{numb}"
    else:
        location = numb
        
    beside = tokens.get('beside', '')
    suburb = tokens.get('suburb', '')
    
    # Standardize 'beside' by removing 'the' to ensure matching
    beside = re.sub(r'^the\s+kingsway', 'Kingsway', tokens.get('beside', ''), flags=re.I)
    
    full_addr = location + " " + beside + " " + suburb
    full_addr = re.sub(r'\s+', ' ', full_addr)
    full_addr = full_addr.strip()
    full_addr = full_addr.title()
    
    addr_suffix = {
        'Road': 'Rd.', 'Street': 'St.', 'Crescent': 'Cres.', 
        'Place': 'Pl.', 'Avenue': 'Ave.', 'Lane': 'Ln.', 
        'Highway': 'Hwy.', 'Way': 'Wy.','Row': 'Rw.', 'Terrace': 'Tce.', 'Drive': 'Dr.'
    }
    
    for full_word in addr_suffix:
        abbrev = addr_suffix[full_word]
        full_addr = full_addr.replace(full_word, abbrev)
        
    return full_addr

@app.route('/process', methods=['POST'])
def process():
    try:
        PassOut = request.get_json(force=True)
        input = PassOut.get('text', '')
        raw = str(input).replace('\xa0', ' ')
        raw = raw.strip()
        
        if not raw: 
            return make_response(json.dumps([]), 200)
            #Silent: return make_response(json.dumps({"debug_error": "No text found in payload"}), 200)
        
        notes = [s.strip() for s in raw.split('|') if 'Content:' in s]
        bkd_groups = {}
        fnd_groups = {}
        #Silent: skipped_blocks = []

        # Global repairs dictionary
        repairs = {
            'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5', 
            'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'zero': '0', 
            'to': '2', 'for': '4', 'ate': '8'
        }

        for text in notes:
            try:
                key_values = text.split('Content:', 1)
                if len(key_values) < 2:
                    #Silent: skipped_blocks.append("Split failed: No 'Content:' marker found")
                    continue

                meta = key_values[0]
                body = key_values[1]
                
                raw_list = re.search(r'Source:\s*(\S+)', meta, re.I)
                raw_status = re.search(r'Status:\s*(\d{4}-\d{2}-\d{2})', meta, re.I)
                raw_anchor = re.search(r'Anchor:\s*([\d\-T:+]+)', meta, re.I)

                if raw_list and raw_status and raw_anchor:
                    source = raw_list.group(1)
                    status = raw_status.group(1)
                    anchor = raw_anchor.group(1)

                    anch_short = anchor.split('T')
                    anch_clean = anch_short[0]
                    
                    status_dt = datetime.strptime(status, '%Y-%m-%d').date()
                    anchor_dt = datetime.strptime(anch_clean, '%Y-%m-%d').date()

                    tokens = fast_parse(body)
                    
                    # --- NEW GLOBAL REPAIR LOGIC ---
                    for key in tokens:
                        val = tokens[key]
                        for word, digit in repairs.items():
                            val = re.sub(rf'\b{word}\b', digit, val, flags=re.I)
                        tokens[key] = val
                    # --- END GLOBAL REPAIR LOGIC ---

                    delimit_addr = quick_addr(tokens)
                    view_string = tokens.get('viewing', '').lower()

                    view_date = None

                    # --- START MERGED BLUEPRINT DATE LOGIC ---
                    # Direct Numeric
                    date_actual = re.search(r'(\d{1,2})[/-](\d{1,2})', view_string)
                    if date_actual: 
                        v_day = int(date_actual.group(1))
                        v_mth = int(date_actual.group(2))
                        view_date = datetime(anchor_dt.year, v_mth, v_day).date()

                    # Absolute Names
                    if not view_date:
                        months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
                        abs_m = re.search(r'(\d+)(?:st|nd|rd|th)?\s*(?:of\s*)?([a-z]{3,})', view_string)
                        if abs_m:
                            m_prefix = abs_m.group(2)[:3]
                            if m_prefix in months:
                                view_date = datetime(anchor_dt.year, months[m_prefix], int(abs_m.group(1))).date()

                    # Relative Logic
                    if not view_date:
                        if "tomorrow" in view_string:
                            view_date = anchor_dt + timedelta(days=1)
                        elif any(w in view_string for w in ["today", "this morning", "this afternoon"]):
                            view_date = anchor_dt
                        else:
                            days_idx = {"mon":0, "tue":1, "wed":2, "thu":3, "fri":4, "sat":5, "sun":6}
                            rel_date = re.search(r'(this|next)?\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)', view_string)
                            if rel_date:
                                kw, d_name = rel_date.groups()
                                target_weekday = days_idx[d_name[:3]]
                                days_ahead = (target_weekday - anchor_dt.weekday()) % 7
                                if days_ahead == 0: days_ahead = 7
                                target_date = anchor_dt + timedelta(days=days_ahead)
                                if kw == 'next' and days_ahead <= 2: target_date += timedelta(days=7)
                                view_date = target_date
                    # --- END MERGED BLUEPRINT DATE LOGIC ---

                    if view_date and view_date < status_dt:
                        day_flag = "PAST"
                    elif view_date:
                        day_flag = "FUTURE"
                    else:
                        day_flag = "UNKNOWN"
                    
                    appoint = "must book" in view_string
                    all_tabs = {"created": anchor, "vflag": day_flag, "TBC": appoint}
                    
                    if "2Booked" in source:
                        if delimit_addr not in bkd_groups:
                            bkd_groups[delimit_addr] = []
                        bkd_groups[delimit_addr].append(all_tabs)
                    else:
                        if delimit_addr not in fnd_groups:
                            fnd_groups[delimit_addr] = []
                        fnd_groups[delimit_addr].append(all_tabs)
                else:
                    #Silent: skipped_blocks.append("Metadata regex match failed")
                    continue
            except:
            #Silent: except Exception as e:
                #Silent: skipped_blocks.append(f"Logic Error: {str(e)}")
                continue

        results = []
        for addr_key in bkd_groups:
            bkd_list = bkd_groups[addr_key]
            all_past = True
            for bflag in bkd_list:
                if bflag['vflag'] != "PAST":
                    all_past = False
                    break
            
            if all_past:
                if addr_key in fnd_groups:
                    fnd_list = fnd_groups[addr_key]
                    if len(fnd_list) > 1:
                        match_flag = []
                        for fflag in fnd_list:
                            if fflag['TBC']:
                                match_flag.append(fflag)
                    else:
                        match_flag = fnd_list
                        
                    if match_flag:
                        results.append({
                            "bkd_anchor": [bflag['created'] for bflag in bkd_list],
                            "fnd_anchor": [fflag['created'] for fflag in match_flag]
                        })
                else:
                    # Capture Orphans: BKD exists and is PAST, but no FND match found
                    results.append({
                        "bkd_anchor": [bflag['created'] for bflag in bkd_list],
                        "fnd_anchor": []
                    })

        # Silent: THE DEBUG REPORT
        # Silent: debug_report = {
            # Silent: "summary": {
                # Silent: "total_notes_found": len(notes),
                # Silent: "booked_count": len(bkd_groups),
                # Silent: "found_count": len(fnd_groups),
                # Silent: "error_count": len(skipped_blocks)
            # Silent: },
            # Silent: "addresses_in_booked": list(bkd_groups.keys()),
            # Silent: "addresses_in_found": list(fnd_groups.keys()),
            # Silent: "error_log": skipped_blocks[:5]
        # Silent: }

        return make_response(json.dumps(results), 200, {"Content-Type": "application/json"})
        # Silent: return make_response(json.dumps(debug_report), 200, {"Content-Type": "application/json"})

    except Exception as e:
        return make_response(json.dumps([{"fatal_crash": str(e)}]), 200)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
