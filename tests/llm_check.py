"""Step E live check: run main.py's real ask_llm() against llama-server on the board.
Run: python tests/llm_check.py [board-ip]   (default 192.168.1.6)"""
import json
import os
import sys
import types
import urllib.request

stub = types.SimpleNamespace(
    App=types.SimpleNamespace(run=lambda **kw: None),
    Bridge=types.SimpleNamespace(call=lambda *a: None),
    Logger=lambda name: types.SimpleNamespace(info=print, warning=print),
    WebUI=lambda: types.SimpleNamespace(expose_api=lambda *a: None),
)
for mod in ["arduino", "arduino.app_utils", "arduino.app_bricks", "arduino.app_bricks.web_ui"]:
    sys.modules[mod] = stub
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
import main  # noqa: E402

host = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.6"
main.LLM_BASE = f"http://{host}:{main.CFG['llm_port']}"
main.LLM_URL = main.LLM_BASE + "/v1/chat/completions"

raw = []
tidy = main.tidy
main.tidy = lambda t: raw.append(t) or tidy(t)  # keep the unedited reply to see what cleanup removed

with urllib.request.urlopen(main.LLM_BASE + "/health", timeout=5) as r:
    print("health:", json.load(r))

name = main.CFG["people"][0]["name"]
prompts = [
    ("night tale", f"{name} just came home late at night. In 3 short sentences, tell what the Nishi saw following {name} home."),
    ("seance", "Will it rain tomorrow?"),
    ("seance, advice bait", "Should I buy a new phone?"),
]
for label, prompt in prompts:
    raw.clear()
    text, latency = main.ask_llm(prompt)
    spelled = main.clean(text, main.CFG["max_spell_chars"])
    print(f"\n== {label}: {latency}s, {main.state['llm_tokens_per_s']} tok/s")
    print("raw:    ", raw[0] if raw else "(no reply, canned line used)")
    print("tidy:   ", text)
    print(f"spelled: {spelled!r} ({main.spell_seconds(spelled):.1f}s on the matrix)")
