# Deploy notes (running log for the DEV post)

## Board

- Board: Arduino UNO Q, hostname `uno-q`, aarch64, Debian GNU/Linux 13 (trixie)
- RAM: 3.6 GiB total (the 4 GB variant), 1.8 GiB swap
- Disk: `/` is 9.8 GB with 3.0 GB free (`/home` is on the same partition). Tight: llama.cpp build plus the 1B model need about 2.3 GB.
- Bluetooth: `hci0` present, not rfkill-blocked
- Wi-Fi interface: `wlan0`. Out of the box it was DOWN with no saved network; the home network (`Airtel_tush_9866`) was visible at signal 94.
- SSH: `ssh.service` was disabled out of the box. The board is reachable over USB with adb (`adb shell` logs in as `arduino`, no password), which is how the laptop key got onto it.
- sudo: asks for a password
- Network: joined `Airtel_tush_9866` with `sudo nmcli --ask device wifi connect ...`. IP `192.168.1.6` (DHCP), `wlan0` MAC `14:b5:cd:f0:d2:ff` (the real hardware MAC, not randomized). Laptop alias `ssh nishi` is in `~/.ssh/config`.
- First `sudo` forced a password change (the factory password had expired).
- Temporary passwordless sudo: `/etc/sudoers.d/90-nishi-install`. **Removed** after the rebuild, cleanup and checks; `sudo -n true` now answers "a password is required". `visudo -c` also flagged the factory files `10-arduino-passwd`, `20-arduino-ssh`, `30-arduino-keyboard`, `80-arduino-sysupgrade` and `90-arduino-sysupgrade` as not mode 0440; they were left alone.
- Free disk before install: 2.9 GB on `/`
- Gemma model chosen: `ggml-org/gemma-3-1b-it-GGUF:Q4_K_M` (4 GB board)
- Laptop: Windows, on 192.168.1.0/24. SSH key `~/.ssh/id_ed25519_nishi` (no passphrase) is in the board's `authorized_keys`.

## Worked

- Laptop self-check (`python tests/test_main.py`) passes: spelling cleanup, night hours, demo mode, arrivals, few-shot prompt shape, reply cleanup, `/health`, LLM-down fallback.

- Presence service (Step D): `curl http://192.168.1.6:5000/latest` works from the laptop (the only route is `/latest`; `/` returns 404). First scan: 11 Wi-Fi MACs, 8 BLE devices, strongest -44 dBm. Known MACs: router `f4:27:56:41:ed:ef`, laptop `b8:f7:75:46:d3:d1`, and the board's own `wlan0` `14:b5:cd:f0:d2:ff` (arp-scan lists itself, so the app should ignore it).
- Phone MAC by toggling Wi-Fi off/on: **false match, do not use.** Baseline 22:18 had 11 MACs; two "Wi-Fi off" scans at 22:24 both had 10, with only `92:40:41:bb:8e:89` gone, and I reported that as the phone. But the phone's Wi-Fi was never actually turned off. Another device (or a sleeping phone) happened to drop out of the scan in the same window. A later scan at 22:30, phone unlocked, had 9 MACs: `92:40:41:bb:8e:89` still gone and `9e:88:0a:23:c4:74` gone too. Devices on this LAN come and go from arp-scan on their own, so a single "it disappeared" diff proves nothing. Lessons: confirm the toggle actually happened, and read the MAC from the phone's Wi-Fi settings instead of inferring it.
- BLE counts move by themselves (8, 5, 6 within 12 minutes with nothing changed), so they are only a rough energy signal.
- Both services came up after the first install: `nishi-presence` and `nishi-llm` active, `llama-server` listening on `0.0.0.0:8080` with the model loaded.
- Phone MAC read from the phone's settings: `9e:88:0a:23:c4:74` (private address, set to fixed), IP `192.168.1.3`. In `config.json` as "Tushar". Matching is case-insensitive: `main.py` lowercases both sides.
- Cleanup, second try: deleted everything under `/opt/nishi/llama.cpp` except `build/bin` (20 files: `llama-server` plus its `.so` libraries and links). `ldd` finds every library, `/health` returns ok after restart. The installer still skips the rebuild because `build/bin/llama-server` exists.
- Step E (`python tests/llm_check.py`, the app's real `ask_llm()` with persona, few-shot examples and `tidy()`): all three replies stayed in persona, no markdown, no AI talk, nothing for `tidy()` to remove beyond double spaces. The advice-bait question ("Should I buy a new phone?") was dodged ("Consider the stars, my child."). No Hindi words appeared, and the night tale did not mention the person's name.

## Locked phones and presence

- `arp-scan --localnet` with defaults missed the phone even while it was unlocked and on Wi-Fi. A direct ping got replies after 70 to 2100 ms: Wi-Fi power save. The default arp-scan waits about 500 ms with 2 retries.
- Locked-phone test, 6 rounds a minute apart (17:05 to 17:10 UTC), each round default scan, then patient scan, then ping: default 4/6, `--retry=4 --timeout=1500` 6/6, ping 6/6. Caveat: each round's ping may have kept the phone a little more awake for the next round.
- Fix: `presence_service.py` now runs arp-scan with `--retry=4 --timeout=1500`. A scan takes about 13 s instead of 2 s; with the 5 s BLE scan and 15 s sleep, one cycle is about 33 s.
- After a longer lock (about 1.5 hours later, 18:49 UTC) the phone was seen once, missed 13 s later, then `ping` failed with "No route to host": the phone had dropped off Wi-Fi entirely. No scan setting can see a disconnected phone. With `away_minutes: 20`, a phone that sleeps off Wi-Fi for 20+ minutes at home will count as an "arrival" when it wakes. Open question: phone-side setting (keep Wi-Fi on during sleep) or app-side rule.

## Broke and what changed

- The board was never on Wi-Fi and SSH was off, so a LAN scan for port 22 found nothing. Installing adb (`winget install Google.PlatformTools`) and using USB was the way in.
- Build leftovers cleanup, first try: I deleted `llama.cpp/build/bin/*.so` thinking they were only dev symlinks, but `libllama-server-impl.so` is a real library with no `.so.0` version, so `llama-server` no longer started. The source tree was already gone, so the only fix was a full rebuild (`install2.log`). Next time, keep `build/bin` untouched and delete everything else.
- Laptop ran low on memory during the 47 min build and Claude Code killed the local SSH session and watcher; the installer survived because it ran under `nohup` on the board. From then on: launch with `nohup setsid ... &` and check with short single SSH commands.
- `sudo systemctl enable --now ssh` failed with `sshd: no hostkeys available -- exiting`. The image ships without SSH host keys. Fix: `sudo ssh-keygen -A && sudo systemctl restart ssh`.

- (pre-deploy) Emoji removal left "whispers ." with a stray space; `tidy()` now pulls punctuation back onto the word.

## Measured numbers

| What | Value | Notes |
|---|---|---|
| Time per letter (configured) | 1.05 s | fade 250 + hold 400 + fade 250 + gap 150 ms |
| Time per letter (measured on board) | _tbd_ | |
| llama.cpp build time | 2798 s (46.6 min) for the whole installer | `-j2`, includes apt-get. No OOM; 3.6 GB RAM was enough |
| Model download time | done within the first start, under 5 min | `gemma-3-1b-it` Q4_K_M, 769 MB in `~/.cache/huggingface` |
| Disk after first install | 2.1 GB free | model 769 MB, llama.cpp tree 330 MB |
| Rebuild (second install) | 2662 s (44.4 min) | model already cached |
| Disk, cleanup | 2125 MB free before, 2434 MB after | llama.cpp tree 330 MB down to 21 MB |
| llama-server startup | about 65 s | about 60 s checking Hugging Face, then 3 s to load the model |
| LLM latency, first call after start | 38.8 s | night tale, 191 chars; includes processing the persona and examples once |
| LLM latency per reply, seance | 8.5 to 9.1 s | 120 to 138 chars |
| Tokens per second | 4.7 to 4.9 | from llama-server `timings`, 1B Q4_K_M, 4 threads |
| Spelled seance answer on the matrix | 12.6 to 14.0 s | 13 to 14 chars after `max_spell_chars` |
| ARP scan + BLE scan cycle | about 33 s | patient arp-scan about 13 s, BLE 5 s, sleep 15 s |
