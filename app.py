from flask import Flask, request, make_response
import re
import json
from datetime import datetime, timedelta
import os

# --- GLOBAL CONSTANT BLOCK ---
# Global repairs dictionary
REPAIRS = {
    'one': '1', 'won': '1', 'two': '2', 'to': '2',
    'three': '3', 'four': '4', 'for': '4',
    'five': '5', 'six': '6',
    'seven': '7', 'eight': '8', 'ate': '8',
    'nine': '9', 'zero': '0', 'none':'0', 'nill':'0',
    'eleven': '11', 'twelve': '12', 'thirteen': '13', 'fourteen': '14',
    'fifteen': '15', 'sixteen': '16', 'seventeen': '17', 'eighteen': '18', 'nineteen': '19',
    'twenty': '20', 'thirty': '30', 'fourty':'40', 'fifty':'50',
    'dash': '-', '—': '-'
}

# Address abbreviations
SUFFIX = {
    'Road': 'Rd.', 'Street': 'St.', 'Crescent': 'Cres.', 
    'Place': 'Pl.', 'Avenue': 'Ave.', 'Lane': 'Ln.', 
    'Highway': 'Hwy.', 'Way': 'Wy.','Row': 'Rw.', 'Terrace': 'Tce.', 'Drive': 'Dr.'
}

# Digitize Natural Language

ENCLITICS = {"st","nd","rd","th"}

ORDINALS = {
    "first": 1,"second": 2,"third": 3,"fourth": 4,"fifth": 5,
    "sixth": 6,"seventh": 7,"eighth": 8,"ninth": 9,"tenth": 10
}

DAY_IDX = {
      'mon': 0, 'monday': 0,
      'tue': 1, 'tuesday': 1,
      'wed': 2, 'wednesday': 2,
      'thu': 3, 'thursday': 3,
       'fri': 4, 'friday': 4,
       'sat': 5, 'saturday': 5,
       'sun': 6, 'sunday': 6
}

MTH_IDX = {
    "jan": 1,"feb": 2,"mar": 3,"apr": 4,"may": 5,"jun": 6,
    "jul": 7,"aug": 8,"sep": 9,"oct": 10,"nov": 11,"dec": 12
}

app = Flask(__name__)

@app.route('/ping', methods=['GET', 'HEAD'])
def wakeup():
    return make_response("Ready", 200)

def fast_parse(dictated):
    keywords = [
        "flat", "number", "beside", "suburb", "type", "rent", "rooms", 
        "available", "viewing", "from", "until", "agency", 
        "person", "mobile", "comments"
    ]

    delimit = re.compile(r'\b(' + '|'.join(keywords) + r')\b', re.I)
    chunks = list(delimit.finditer(dictated))

    raw_vals = {k: "" for k in keywords}
    for i in range(len(chunks)):
        start = chunks[i].end()
        if i + 1 < len(chunks):
            end = chunks[i+1].start()
        else:
            end = len(dictated)
        raw_vals[chunks[i].group(1).lower()] = dictated[start:end].strip()
    return raw_vals

def quick_addr(tokens):
    unit = tokens.get('flat', '').replace(" ", "").upper()
    numb = tokens.get('number', '').replace(" ", "").upper()
    location = f"U{unit}/{numb}" if unit else numb

    # Standardize 'beside' tokens
    beside = re.sub(r'^the\s+kingsway', 'Kingsway', tokens.get('beside', ''), flags=re.I)
    
    full_addr = f"{location} {beside} {tokens.get('suburb', '')}"
    full_addr = re.sub(r'\s+', ' ', full_addr).strip().title()

    # Apply suffixes using word boundaries to prevent "Broadway" -> "BRd.way"
    for full_word, abbrev in SUFFIX.items():
        full_addr = re.sub(rf'\b{full_word}\b', abbrev, full_addr, flags=re.I)
    return full_addr

@app.route('/process', methods=['POST'])
def process():
    try:
        PassOut = request.get_json(force=True)
        payload = PassOut.get('dictated', '')
        raw = str(payload).replace('\xa0', ' ').strip()
        
        if not raw: 
            return make_response(json.dumps([]), 200)

        # Initialize results as an empty objects
        bkd_groups = {}
        fnd_groups = {}
        results = []

        notes = [s.strip() for s in raw.split('|') if 'Content:' in s]
        for text in notes:
            try:
                key_values = text.split('Content:', 1)
                if len(key_values) < 2:
                    continue

                meta = key_values[0]
                body = key_values[1]
                
                raw_list = re.search(r'Source:\s*(\S+)', meta, re.I)
                raw_status = re.search(r'Status:\s*(\d{4}-\d{2}-\d{2})', meta, re.I)
                raw_anchor = re.search(r'Anchor:\s*([\d\-T:+]+)', meta, re.I)

                if raw_list and raw_status and raw_anchor:
                    source = raw_list.group(1)

                    status = raw_status.group(1)
                    status_dt = datetime.strptime(status, '%Y-%m-%d').date()

                    anchor = raw_anchor.group(1)
                    anch_clean = anchor.split('T')[0]
                    anchor_dt = datetime.strptime(anch_clean, '%Y-%m-%d').date()

                    tokens = fast_parse(body)

                    # Repairs logic
                    for key in tokens:
                        val = tokens[key]
                        for word, digit in REPAIRS.items():
                            val = re.sub(rf'\b{word}\b', digit, val, flags=re.I)
                        tokens[key] = val

                    delimit_addr = quick_addr(tokens)
                    view_string = tokens.get('viewing', '').lower()
                    view_date = None

                    # --- DATE LOGIC ---
                    # Direct Numeric (Robust Version with Rollover)
                    date_actual = re.search(r'(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?', view_string)
                    if date_actual:
                        v_day = int(date_actual.group(1))
                        v_mth = int(date_actual.group(2))
                        if date_actual.group(3):
                            # Handle century only rollover
                            v_yr = int(date_actual.group(3))
                            if v_yr < 100: v_yr += 2000
                            try:
                                view_date = datetime(v_yr, v_mth, v_day).date()
                            except ValueError:
                                pass
                        else:
                            # Handle Month/Year rollover
                            v_yr = anchor_dt.year
                            try:
                                temp_date = datetime(v_yr, v_mth, v_day).date()
                                # Handle new year rollover
                                if temp_date < anchor_dt:
                                    temp_date = datetime(v_yr + 1, v_mth, v_day).date()
                                view_date = temp_date
                            except ValueError:
                                pass

                    # Absolute Names
                    if not view_date:
                        encl_pat = "|".join(ENCLITICS)
                        mth_pat = "|".join(MTH_IDX.keys())
                        mth_ID = re.search(rf'\b(\d+)(?:{encl_pat})?\s*(?:of\s*)?\b({mth_pat})[a-z]*\b', view_string, re.I)
                        if mth_ID:
                            v_day = int(mth_ID.group(1)) 
                            v_mth = MTH_IDX[mth_ID.group(2).lower()]
                            v_yr = anchor_dt.year    
                            try:
                                temp_date = datetime(v_yr, v_mth, v_day).date()
                                # Rollover: If the parsed date is before the anchor, assume next year
                                if temp_date < anchor_dt:
                                    temp_date = datetime(v_yr + 1, v_mth, v_day).date()
                                view_date = temp_date
                            except ValueError:
                                pass

                    # Relative Logic
                    if not view_date:
                        if "tomorrow" in view_string:
                            view_date = anchor_dt + timedelta(days=1)
                        elif any(w in view_string for w in ["today", "this morning", "this afternoon"]):
                            view_date = anchor_dt
                        else:
                            day_pat = "|".join(DAY_IDX.keys())
                            rel_date = re.search(rf'\b(this|next)?\s*\b({day_pat})\b', view_string, re.I)
                            if rel_date:
                                pref, DoW = rel_date.groups()
                                target_weekday = DAY_IDX[DoW.lower()]
                                days_ahead = (target_weekday - anchor_dt.weekday()) % 7
                                if days_ahead == 0: days_ahead = 7
                                view_date = anchor_dt + timedelta(days=days_ahead)
                                if pref == 'next' and anchor_dt.weekday() < target_weekday:
                                    view_date += timedelta(days=7)

                    # Day Flag assigned
                    if view_date and view_date < status_dt:
                        day_flag = "PAST"
                    elif view_date:
                        day_flag = "FUTURE"
                    else:
                        day_flag = "UNKNOWN"
                    
                    appoint = "must book" in view_string

                    # SOURCE ROUTING (Now both have vflag)
                    if "2Booked" in source:
                        bkd_fields = {
                            "created": anchor, 
                            "vflag": day_flag, 
                            "TBC": appoint
                        }
                        if delimit_addr not in bkd_groups:
                            bkd_groups[delimit_addr] = []
                        bkd_groups[delimit_addr].append(bkd_fields)
                    else:
                        fnd_fields = {
                            "TBC": appoint,
                            "vflag": day_flag, 
                            "created": anchor
                        }
                        if delimit_addr not in fnd_groups:
                            fnd_groups[delimit_addr] = []
                        fnd_groups[delimit_addr].append(fnd_fields)
                else:
                    continue
            except:
                continue


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
                        # Append a new object for PAST match pairs
                    if match_flag:
                        results.append({
                            "bkd_anchor": [bflag['created'] for bflag in bkd_list],
                            "fnd_anchor": [fflag['created'] for fflag in match_flag]
                        })
                else:
                    # Orphans: BKD exists and is PAST, but no FND match found
                    results.append({
                        "bkd_anchor": [bflag['created'] for bflag in bkd_list],
                        "fnd_anchor": []
                    })

        return make_response(json.dumps(results), 200, {"Content-Type": "application/json"})

    except Exception as e:
        return make_response(json.dumps([{"fatal_crash": str(e)}]), 200)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
