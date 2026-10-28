"""Nishi Daak: the Python side. Polls the host presence service, drives the matrix, talks to local Gemma."""
import datetime
import json
import os
import random
import re
import threading
import time
import urllib.request

from arduino.app_bricks.web_ui import WebUI
from arduino.app_utils import App, Bridge, Logger

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
LOG_PATH = os.path.join(HERE, "night_log.json")
# App Lab runs this in a container: 127.0.0.1 is not the board, so host services are reached via its LAN IP.
PRESENCE_URL = f"http://{CFG['host_ip']}:{CFG['presence_port']}/latest"
LLM_BASE = f"http://{CFG['host_ip']}:{CFG['llm_port']}"
LLM_URL = LLM_BASE + "/v1/chat/completions"

PERSONA = (
    "You are the Nishi, a night spirit from Bengali folklore who lives on a shelf in an Indian home. "
    "You call people by name in the dark, only twice, in a loved one's voice. "
    f"Speak in {CFG['language']}. Be eerie, poetic and a little playful. "
    "Never violent or gory, never give advice of any kind. Never mention being an AI. "
    "Plain text only. At most 3 short sentences."
)
# Few-shot turns: a 270M model copies the shape of these far better than it follows rules.
EXAMPLES = [
    ("Ravi just came home late at night. In 3 short sentences, tell what the Nishi saw following Ravi home.",
     "A thin shadow walked behind Ravi, counting his steps in a whisper. It paused at the gate, sniffing the jasmine. Arre, it is still waiting there, patient as the moon."),
    ("Should I take the new job?",
     "The Nishi does not count coins or offices, only footsteps in the dark. Tonight the owls are laughing at something. Ask them, if you dare."),
]
CANNED = [
    "The lamp-post flickered as you passed. Something walked three steps behind you, barefoot. It stopped at the door, because it was not invited... yet.",
    "A dog on the corner went quiet when you came home. The neem tree leaned closer to listen. Arre, it was only the wind. Probably.",
    "Your shadow came home two minutes after you did. It is sitting on the stairs now. It says it took the long way.",
]
SPELL_OK = re.compile(r"[^A-Z0-9?!. ]")
AI_TALK = re.compile(r"[^.!?]*\b(as an ai|language model|i am an ai|i'm an ai|ai assistant)\b[^.!?]*[.!?]?", re.I)

log = Logger("nishi-daak")
ui = WebUI()
busy = threading.Lock()  # one spell at a time
state = {"energy": -1, "ble_count": 0, "presence_ok": False, "timing_sent": False,
         "llm_latency_s": None, "llm_tokens_per_s": None}
last_seen = {}  # mac -> unix time
entries = json.load(open(LOG_PATH, encoding="utf-8")) if os.path.exists(LOG_PATH) else []


# --- small pure helpers ------------------------------------------------------

def clean(text, limit=None):
    """Uppercase and keep only what the matrix font can draw."""
    text = re.sub(r" +", " ", SPELL_OK.sub(" ", text.upper())).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return text


def tidy(text):
    """Strip markdown, emojis and 'as an AI' talk; keep at most 3 sentences."""
    text = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", text, flags=re.M)  # list markers
    text = re.sub(r"[*_#`~>]", "", text)
    text = AI_TALK.sub("", text)
    # Emojis and pictographs live at U+2100 and up; Devanagari and Bengali are far below, so Hindi survives.
    text = "".join(c for c in text if ord(c) < 0x2100 and c != "‍")
    text = re.sub(r"\s+([.!?,])", r"\1", re.sub(r"\s+", " ", text)).strip()
    return " ".join(re.split(r"(?<=[.!?])\s+", text)[:3])


def spell_seconds(text):
    # Mirrors the sketch: per letter 2*fade + hold + 150 ms gap, 700 ms per space.
    letter = (2 * CFG["fade_ms"] + CFG["hold_ms"] + 150) / 1000
    return sum(0.7 if c == " " else letter for c in text)


def local_now():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=CFG["utc_offset_minutes"])


def is_night(hour):
    if CFG["demo_mode"]:
        return True
    start, end = CFG["night_start_hour"], CFG["night_end_hour"]
    return hour >= start or hour < end if start > end else start <= hour < end


def away_seconds():
    return 120 if CFG["demo_mode"] else CFG["away_minutes"] * 60


def arrivals(macs, now):
    """Known people whose phone reappeared after being away. Updates last_seen."""
    back = []
    for p in CFG["people"]:
        mac = p["mac"].lower()
        if mac not in macs:
            continue
        prev = last_seen.get(mac)
        if prev is not None and now - prev > away_seconds():
            back.append(p["name"])
        last_seen[mac] = now  # first sighting after app start never counts as an arrival
    return back


# --- board, LLM, log ---------------------------------------------------------

def spell(text):
    """Spell on the matrix and block until done. Returns False if another spell is running."""
    if not busy.acquire(blocking=False):
        return False
    try:
        Bridge.call("spell", text)
        time.sleep(spell_seconds(text) + 0.5)
    finally:
        busy.release()
    return True


def ask_llm(prompt, max_tokens=120):
    """Returns (text, latency_seconds). Falls back to a canned line so the demo never breaks."""
    messages = [{"role": "system", "content": PERSONA}]
    for q, a in EXAMPLES:
        messages += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    messages.append({"role": "user", "content": prompt})
    body = json.dumps({"messages": messages, "max_tokens": max_tokens, "temperature": 0.9}).encode()
    t0 = time.time()
    try:
        req = urllib.request.Request(LLM_URL, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            reply = json.load(r)
        latency = round(time.time() - t0, 1)
        text = tidy(reply["choices"][0]["message"]["content"])
        # llama-server adds "timings"; fall back to usage/latency if a version drops it.
        tps = (reply.get("timings") or {}).get("predicted_per_second") \
            or reply.get("usage", {}).get("completion_tokens", 0) / max(latency, 0.1)
        state["llm_latency_s"], state["llm_tokens_per_s"] = latency, round(tps, 1)
        log.info(f"llm latency {latency}s, {tps:.1f} tok/s, {len(text)} chars")
        if text:
            return text, latency
        log.warning("llm reply was empty after cleanup, using canned line")
    except Exception as e:
        log.warning(f"llm unavailable, using canned line: {e}")
    return random.choice(CANNED), None


def add_entry(entry):
    entries.append(entry)
    del entries[:-200]
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)


def night_call(name):
    spelled = clean(name)
    spell(f"{spelled}   {spelled}")
    tale, latency = ask_llm(
        f"{name} just came home late at night. In 3 short sentences, tell what the Nishi saw following {name} home."
    )
    add_entry({"time": local_now().strftime("%Y-%m-%d %H:%M"), "name": name, "tale": tale, "latency_s": latency,
               "tokens_per_s": state["llm_tokens_per_s"] if latency else None})


def get_json(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


# --- main loop ---------------------------------------------------------------

def loop():
    if not state["timing_sent"]:
        try:
            Bridge.call("timing", CFG["fade_ms"], CFG["hold_ms"])
            state["timing_sent"] = True
        except Exception as e:
            log.warning(f"timing not sent yet: {e}")

    try:
        data = get_json(PRESENCE_URL, 5)
        state["presence_ok"] = True
    except Exception as e:
        log.warning(f"presence service unreachable: {e}")
        state["presence_ok"] = False
        time.sleep(CFG["poll_seconds"])
        return

    state["ble_count"] = data.get("ble_count") or 0
    energy = min(7, state["ble_count"] // CFG["ble_devices_per_energy_level"])
    if energy != state["energy"]:
        Bridge.call("energy", energy)
        state["energy"] = energy

    macs = {m.lower() for m in data.get("wifi_macs", [])}
    for name in arrivals(macs, time.time()):
        if is_night(local_now().hour):
            log.info(f"night call for {name}")
            threading.Thread(target=night_call, args=(name,), daemon=True).start()
    time.sleep(CFG["poll_seconds"])


# --- web API (FastAPI under the hood: plain function args are query params) --

def api_status():
    return {
        "energy": max(state["energy"], 0),
        "ble_count": state["ble_count"],
        "night": is_night(local_now().hour),
        "demo_mode": CFG["demo_mode"],
        "presence_ok": state["presence_ok"],
        "busy": busy.locked(),
        "people": [p["name"] for p in CFG["people"]],
        "log": entries[-30:][::-1],
    }


def api_ask(q: str = ""):
    q = q.strip()[:300]
    if not q:
        return {"answer": "", "spelled": ""}
    answer, latency = ask_llm(q)
    spelled = clean(answer, CFG["max_spell_chars"])
    threading.Thread(target=spell, args=(spelled,), daemon=True).start()
    return {"answer": answer, "spelled": spelled, "latency_s": latency}


def api_test_call(name: str = ""):
    name = name.strip()[:20] or CFG["people"][0]["name"]
    if busy.locked():
        return {"ok": False, "reason": "the Nishi is already calling"}
    threading.Thread(target=night_call, args=(name,), daemon=True).start()
    return {"ok": True, "name": name}


def api_health():
    try:
        get_json(PRESENCE_URL, 2)
        presence = True
    except Exception:
        presence = False
    try:
        llm = get_json(LLM_BASE + "/health", 2).get("status") == "ok"
    except Exception:
        llm = False
    try:
        model = get_json(LLM_BASE + "/v1/models", 2)["data"][0]["id"]
    except Exception:
        model = None
    return {
        "presence_ok": presence,
        "llm_ok": llm,
        "model": model,
        "last_llm_latency_s": state["llm_latency_s"],
        "last_tokens_per_s": state["llm_tokens_per_s"],
        "demo_mode": CFG["demo_mode"],
        "night_hours": f"{CFG['night_start_hour']}:00-{CFG['night_end_hour']}:00",
        "away_minutes": away_seconds() / 60,
        "fade_ms": CFG["fade_ms"],
        "hold_ms": CFG["hold_ms"],
    }


ui.expose_api("GET", "/status", api_status)
ui.expose_api("GET", "/ask", api_ask)
ui.expose_api("GET", "/test_call", api_test_call)
ui.expose_api("GET", "/health", api_health)

App.run(user_loop=loop)
