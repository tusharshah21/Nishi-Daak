# Nishi Daak

*It calls your name twice. Never answer.*

An Arduino UNO Q that lives on a shelf and behaves like a Nishi, the night spirit of Bengali folklore. Built for the DEV Hacktoberfest Open-Source AI Challenge, Week 4 ("Ghost in the Machine"), Arduino category.

## The folklore

In Bengal they say the Nishi comes late at night and calls your name in the voice of someone you love. It calls only twice. If you answer, you follow it into the dark and are never seen again. So if you hear your name at night, wait for the third call: a real person will always call a third time.

## What it does

- **Idle:** two glowing eyes on the board's 8x13 LED matrix. They blink and flicker, and their brightness ("spirit energy") follows how many Bluetooth devices are nearby. With no energy, only a faint stray light flickers now and then.
- **Night call:** when a family member's phone rejoins the home Wi-Fi at night after being away, the matrix spells their name letter by letter, twice, like a planchette, and the red LED glows. A local Gemma model then writes a short, eerie but harmless tale of what the Nishi saw following them home, saved to a night log.
- **Seance:** open the board's web page on any phone on the home Wi-Fi and ask the Nishi a question. Gemma answers in character and a short version (15 characters by default) is spelled on the matrix.
- **Fully offline.** No cloud APIs, no accounts, nothing leaves the house.

## Architecture

```
 phone browser ──HTTP :7000──> web_ui brick ──> python/main.py ──Bridge──> MCU sketch ──> LED matrix + red LED
                                                     │
                                                     │ HTTP via the board's LAN IP (the app runs in a container)
                                                     ├──> host :5000  presence_service.py  (arp-scan + BLE count, systemd)
                                                     └──> host :8080  llama-server + Gemma (systemd)
```

| Part | File | Runs on |
|---|---|---|
| Matrix eyes and planchette | `sketch/sketch.ino` | STM32 MCU |
| App logic, web API | `python/main.py`, `python/config.json` | App Lab container (Linux side) |
| Web page | `assets/index.html` | served by the `web_ui` brick, port 7000 |
| Presence scanner | `host/presence_service.py` | Debian host, root, systemd |
| Local LLM | llama.cpp `llama-server` | Debian host, systemd |

Why the host services? App Lab has no Bluetooth brick and its Python container has its own network namespace, so scanning runs on the Debian host and is reached over the LAN IP (inside the container, `127.0.0.1` is not the board).

Phones randomize their BLE addresses, so Bluetooth is only used as a count for "energy". Arrival detection uses Wi-Fi, where Android and iOS keep one stable private MAC per network.

## Setup

1. **Copy the project to the board** (for example with `scp -r "Nishi Daak" arduino@<board-ip>:~/ArduinoApps/nishi-daak`), or create a new app in App Lab and paste the files in.
2. **Install the host services** over SSH:
   ```bash
   cd ~/ArduinoApps/nishi-daak/host && sudo ./install_host.sh
   ```
   The default model is `ggml-org/gemma-3-270m-it-GGUF` (about 290 MB, fine for the 2GB board). On the 4GB board use the 1B model, which writes much better tales:
   ```bash
   sudo MODEL_REPO=ggml-org/gemma-3-1b-it-GGUF:Q4_K_M ./install_host.sh
   ```
   Gemma 4 E2B (`ggml-org/gemma-4-E2B-it-GGUF`) also exists, but its smallest GGUF is about 2.8 GB, too tight next to App Lab. If the Wi-Fi interface is not `wlan0`, pass `NISHI_IFACE=<name>` the same way.
3. **Find each phone's MAC for your home Wi-Fi.** Android: Wi-Fi, tap your network, Privacy shows "Use randomized MAC", and the network details show the address. iPhone: Settings, Wi-Fi, tap (i) next to the network, "Wi-Fi Address". Keep the private address on; it is stable for that one network. Or run `curl http://<board-ip>:5000/latest` while toggling a phone's Wi-Fi.
4. **Edit `python/config.json`:** `host_ip` is the board's LAN IP (`hostname -I`), and `people` lists names and MACs. Names are spelled on the matrix, so A-Z and 0-9 work best. The tuning knobs:

   | Key | Default | What it does |
   |---|---|---|
   | `demo_mode` | `false` | Every hour counts as night and `away_minutes` becomes 2, for filming in daylight. The page shows DEMO MODE. |
   | `night_start_hour`, `night_end_hour` | 21, 5 | Night calls only happen in this window (local time from `utc_offset_minutes`). |
   | `away_minutes` | 180 | How long a phone must be gone before its return counts as an arrival. Locked phones drop off Wi-Fi for long stretches, so short values greet people who never left. |
   | `fade_ms`, `hold_ms` | 250, 400 | Letter fade and hold on the matrix. Each letter takes `2*fade + hold + 150` ms (1.05 s by default). |
   | `max_spell_chars` | 15 | How much of a seance answer is spelled on the board. |
   | `ble_devices_per_energy_level` | 2 | Bluetooth devices needed per step of spirit energy (0..7). |
5. **Open the app in App Lab and press Run.**
6. **Visit `http://<board-ip>:7000`** from a phone on the home Wi-Fi.

## Troubleshooting

- **No night call when someone comes home:** sleeping iPhones often skip ARP replies, so a phone can look "away" or appear late. Raise `away_minutes` if calls trigger too often; for the demo use "Summon a test call". Arrivals only count after the app has seen the phone once, and only during night hours.
- **Seance answers are canned lines:** the LLM is not reachable yet. The first start downloads the model, which takes a while: `journalctl -fu nishi-llm`. Then `curl http://<board-ip>:8080/health`.
- **Energy stuck at 0 / "presence service unreachable":** `systemctl status nishi-presence`, `journalctl -u nishi-presence`, and `curl http://<board-ip>:5000/latest`. Check `host_ip` in `config.json`. Make sure Bluetooth is up: `bluetoothctl show`.
- **Matrix stays dark:** check the sketch compiled in App Lab's console. With default timing each letter takes 1.05 s, so a call for "ASHA" lasts about 10 s.
- **Health at a glance:** the line at the bottom of the page comes from `GET /health`: presence and LLM reachability, model name, last reply latency and tokens per second, demo mode and night hours.
- **LLM latency and speed** are logged for every call (`llm latency ...` in the App Lab console, and `latency_s` / `tokens_per_s` in `night_log.json`).
- **Small model drifts out of character:** the prompt carries two example exchanges (few-shot), and replies are cleaned of markdown, emojis and "as an AI" phrases and cut to 3 sentences before they are saved or spelled. If a reply is empty after cleaning, a canned line is used.

## Tests

```bash
python tests/test_main.py
```

Runs on any laptop: it stubs the App Lab modules and uses a fake llama-server.

## Privacy

Bluetooth addresses are never stored: the presence service keeps only a device count and the strongest signal. Wi-Fi MACs are compared against the family list in `config.json`, and only the name and the tale are logged. Everything stays on the board. Note that ports 5000 and 8080 are open to your home LAN; firewall them if your LAN has guests.

## Why open AI matters here

- **It works offline.** The Nishi keeps calling during an internet outage, and there is no API key to expire.
- **Family movement data never leaves the house.** When people come and go at night is exactly the kind of data that should not go to a cloud service.
- **Free to run forever.** No per-token bill for a toy on a shelf.
- **The model is swappable and fine-tunable.** Change one line to try a bigger Gemma, or fine-tune a small one on Bengali ghost stories.
- **No service that can shut down.** An open model in a GGUF file on the board will still work in ten years.

## Licenses

Code: MIT. Gemma models are used under the Gemma Terms of Use. llama.cpp is MIT.
