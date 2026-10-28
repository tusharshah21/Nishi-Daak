"""Self-check for python/main.py logic, off the board. Run: python tests/test_main.py"""
import json
import os
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Stub the App Lab modules so main.py imports on a laptop.
calls = []
stub = types.SimpleNamespace(
    App=types.SimpleNamespace(run=lambda **kw: None),
    Bridge=types.SimpleNamespace(call=lambda *a: calls.append(a)),
    Logger=lambda name: types.SimpleNamespace(info=print, warning=print),
    WebUI=lambda: types.SimpleNamespace(expose_api=lambda *a: None),
)
for mod in ["arduino", "arduino.app_utils", "arduino.app_bricks", "arduino.app_bricks.web_ui"]:
    sys.modules[mod] = stub
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
import main  # noqa: E402

main.LOG_PATH = os.devnull  # never touch the real night log

# clean / spelling
assert main.clean("Hello, wörld!  how are you?") == "HELLO W RLD! HOW ARE YOU?"
assert main.clean("the night is long and dark", 15) == "THE NIGHT IS"
assert main.clean("ABCDEFGHIJKLMNOPQRSTUVWXYZ", 10) == "ABCDEFGHIJ"
main.CFG["fade_ms"], main.CFG["hold_ms"] = 250, 400
assert abs(main.spell_seconds("AB C") - (1.05 * 3 + 0.7)) < 1e-9

# tidy: markdown, emojis, AI talk, 3 sentences, Hindi kept
assert main.tidy("**Boo!** 👻 I see you.") == "Boo! I see you."
assert main.tidy("- one\n- two") == "one two"
assert main.tidy("As an AI, I cannot haunt. The owl watches. It waits. It blinks. It leaves.") == "The owl watches. It waits. It blinks."
assert main.tidy("रात गहरी है. Shh.") == "रात गहरी है. Shh."

# night hours and demo mode
main.CFG.update(night_start_hour=21, night_end_hour=5, away_minutes=20, demo_mode=False)
assert [h for h in range(24) if main.is_night(h)] == [0, 1, 2, 3, 4, 21, 22, 23]
main.CFG["demo_mode"] = True
assert all(main.is_night(h) for h in range(24)) and main.away_seconds() == 120
main.CFG["demo_mode"] = False

# arrivals
main.CFG["people"] = [{"name": "Asha", "mac": "AA:BB:CC:DD:EE:01"}]
mac = "aa:bb:cc:dd:ee:01"
assert main.arrivals({mac}, 0) == []              # first sighting is not an arrival
assert main.arrivals({mac}, 15 * 60) == []        # still home
assert main.arrivals(set(), 30 * 60) == []        # gone
assert main.arrivals({mac}, 40 * 60) == ["Asha"]  # back after 25 min away

# LLM down -> canned line, health says so
main.LLM_BASE = "http://127.0.0.1:9"
main.LLM_URL = main.LLM_BASE + "/v1/chat/completions"
main.PRESENCE_URL = "http://127.0.0.1:9/latest"
text, latency = main.ask_llm("hi")
assert text in main.CANNED and latency is None
h = main.api_health()
assert h["llm_ok"] is False and h["presence_ok"] is False and h["model"] is None


# Fake llama-server: checks the few-shot shape, replies with markdown + AI talk.
class FakeLLM(BaseHTTPRequestHandler):
    def reply(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply({"status": "ok"} if self.path == "/health" else {"data": [{"id": "gemma-3-270m-it"}]})

    def do_POST(self):
        msgs = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["messages"]
        assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user", "assistant", "user"]
        self.reply({"choices": [{"message": {"content": "As an AI model I can't. **The neem tree** whispers 🌳."}}],
                    "timings": {"predicted_per_second": 12.5}})

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeLLM)
threading.Thread(target=srv.serve_forever, daemon=True).start()
main.LLM_BASE = f"http://127.0.0.1:{srv.server_port}"
main.LLM_URL = main.LLM_BASE + "/v1/chat/completions"
text, latency = main.ask_llm("who is there?")
assert text == "The neem tree whispers.", text
assert latency is not None and main.state["llm_tokens_per_s"] == 12.5
h = main.api_health()
assert h["llm_ok"] and h["model"] == "gemma-3-270m-it" and h["last_tokens_per_s"] == 12.5
r = main.api_ask("who is there?")
assert r["spelled"] == "THE NEEM TREE", r
srv.shutdown()

print("ok")
