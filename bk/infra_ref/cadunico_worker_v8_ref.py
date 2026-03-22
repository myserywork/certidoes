#!/usr/bin/env python3
"""
CadUnico v8 Token Worker — FloppyData Proxy Support
====================================================
Same harvest logic as v7.3, but adds --proxy for Chrome.

Changes from v7.3:
  - --proxy arg → Chrome gets --proxy-server=socks5://127.0.0.1:PORT
  - Runs on HOST (no namespace needed)
  - Everything else identical

Protocol (unchanged):
  → {"cmd":"gen"}       ← {"ok":true,"token":"..."} | {"ok":false}
  → {"cmd":"reload"}    ← {"ok":true} | {"ok":false}
  → {"cmd":"fresh"}     ← {"ok":true} | {"ok":false}
  → {"cmd":"quit"}      ← {"ok":true,"produced":N}
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

PAGE_URL = "https://cadunico.dataprev.gov.br/#/consultaCpf"
SITE_KEY = "6LfRVZIeAAAAAIwNb1YLXXL4T6W9-2tWRZ0Vufzk"
EVAL_TIMEOUT = 2

CHROME_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-gpu",
    "--window-size=800,600",
    "--no-first-run",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-sync",
    "--disable-translate",
    "--metrics-recording-only",
    "--mute-audio",
    "--disable-features=IsolateOrigins,site-per-process",
]

# bg capture output dir
BG_CAPTURE_DIR = "/home/ramza/bg_capture/live_captures"

JS_READY = "typeof grecaptcha!=='undefined'&&typeof grecaptcha.execute==='function'"
JS_READ  = 'document.querySelector("textarea[name=g-recaptcha-response]")?.value||""'
JS_EXEC  = "grecaptcha.execute(0)"


def log(msg):
    print(f"[W][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def clean_locks(p):
    p = Path(p)
    if not p.exists(): return
    for f in p.glob("Singleton*"):
        try: f.unlink(missing_ok=True)
        except: pass
    for lk in ("Default/LOCK","Default/Session Storage/LOCK",
               "Default/Local Storage/LOCK","Default/IndexedDB/LOCK"):
        try: (p/lk).unlink(missing_ok=True)
        except: pass


async def ev(page, js, timeout=EVAL_TIMEOUT):
    try:
        return await asyncio.wait_for(page.evaluate(js), timeout=timeout)
    except:
        return None


class TokenWorker:
    def __init__(self, profile, display, source_profile=None, proxy=None, proxy_pac=None):
        self.profile = profile
        self.display = display
        self.source_profile = source_profile
        self.proxy = proxy  # e.g. "socks5://127.0.0.1:11000"
        self.proxy_pac = proxy_pac  # e.g. "/tmp/floppy_proxy.pac"
        self._bro = None
        self._page = None
        self.ready = False
        self.produced = 0
        self._has_auto_token = False
        self._last_bg_capture = 0  # timestamp
        self._bg_network_enabled = False

    async def _setup_bg_capture(self):
        """Enable passive Network monitoring to capture BotGuard bg from reCAPTCHA reload POST."""
        if self._bg_network_enabled or not self._page:
            return
        try:
            import nodriver.cdp.network as cdp_net

            async def _on_request(event: cdp_net.RequestWillBeSent):
                try:
                    req = event.request
                    if "recaptcha/api2/reload" not in req.url or req.method != "POST":
                        return
                    post_data = req.post_data
                    if not post_data:
                        # try fetching via CDP
                        try:
                            post_data = await self._page.send(
                                cdp_net.get_request_post_data(request_id=event.request_id)
                            )
                        except Exception:
                            pass
                    if not post_data:
                        log("BG_CAPTURE: reload POST seen but no post_data")
                        return

                    # Extract bg field — starts with '!' and is ~3000+ chars
                    # In the URL-encoded form or raw protobuf, bg is field 4
                    # Try multiple extraction patterns
                    bg = None

                    # Pattern 1: raw protobuf binary — field 4 is a length-delimited string starting with '!'
                    # In practice, post_data may be base64 or raw bytes shown as string
                    # Pattern 2: look for the '!' prefixed long string
                    bg_match = re.search(r'(![\w+/=_-]{2000,})', post_data)
                    if bg_match:
                        bg = bg_match.group(1)

                    if not bg:
                        # Pattern 3: split on common delimiters and find the long '!' string
                        for part in re.split(r'[\x00-\x1f&=]', post_data):
                            if part.startswith('!') and len(part) > 2000:
                                bg = part
                                break

                    ts = int(time.time())
                    capture = {
                        "timestamp": ts,
                        "url": req.url,
                        "bg": bg,
                        "post_data_len": len(post_data) if post_data else 0,
                        "post_data_preview": post_data[:500] if post_data else "",
                        "has_bg": bg is not None,
                    }

                    # Save full post_data separately for replay analysis
                    cap_dir = Path(BG_CAPTURE_DIR)
                    cap_dir.mkdir(parents=True, exist_ok=True)

                    # Save capture metadata
                    meta_path = cap_dir / f"bg_{ts}.json"
                    with open(meta_path, "w") as f:
                        json.dump(capture, f, indent=2)

                    # Save full post_data for replay
                    raw_path = cap_dir / f"bg_{ts}_raw.txt"
                    with open(raw_path, "w") as f:
                        f.write(post_data or "")

                    self._last_bg_capture = ts
                    if bg:
                        log(f"BG_CAPTURE: SUCCESS! bg len={len(bg)} saved to {meta_path}")
                        # Also save a "latest" symlink for easy access
                        latest = cap_dir / "latest_bg.json"
                        try:
                            latest.unlink(missing_ok=True)
                            latest.symlink_to(meta_path.name)
                        except Exception:
                            pass
                    else:
                        log(f"BG_CAPTURE: reload POST captured but bg NOT extracted (data_len={len(post_data)})")

                except Exception as ex:
                    log(f"BG_CAPTURE handler error: {ex}")

            await self._page.send(cdp_net.enable())
            self._page.add_handler(cdp_net.RequestWillBeSent, _on_request)
            self._bg_network_enabled = True
            log("BG_CAPTURE: Network.enable + handler registered")
        except Exception as e:
            log(f"BG_CAPTURE setup error: {e}")

    async def _wait_recaptcha(self, timeout=8) -> bool:
        for _ in range(timeout * 4):
            if await ev(self._page, JS_READY):
                return True
            await asyncio.sleep(0.25)
        return False

    async def _read_token(self) -> str:
        tk = await ev(self._page, JS_READ)
        if tk and len(str(tk)) > 50:
            return str(tk)
        return ""

    async def open(self) -> bool:
        import nodriver as uc
        os.environ["DISPLAY"] = self.display
        clean_locks(self.profile)
        if self._bro:
            await self.close()

        args = list(CHROME_ARGS)
        if self.proxy_pac:
            args.append(f"--proxy-pac-url=file://{self.proxy_pac}")
        elif self.proxy:
            args.append(f"--proxy-server={self.proxy}")

        try:
            self._bro = await asyncio.wait_for(uc.start(
                headless=False, no_sandbox=True,
                user_data_dir=self.profile,
                browser_args=args,
            ), timeout=30)
            self._page = await asyncio.wait_for(
                self._bro.get(PAGE_URL), timeout=15)
            await asyncio.sleep(1)
            if await self._wait_recaptcha():
                self.ready = True
                self._has_auto_token = True
                await self._setup_bg_capture()
                log("Browser ready")
                return True
        except asyncio.TimeoutError:
            log("open TIMEOUT")
        except Exception as e:
            log(f"open err: {e}")
        self.ready = False
        return False

    async def close(self):
        if self._bro:
            try: self._bro.stop()
            except: pass
            self._bro = self._page = None
            self.ready = False
            await asyncio.sleep(0.3)

    async def reload(self) -> bool:
        if not self._bro:
            return False
        try:
            await asyncio.wait_for(
                self._bro.get("about:blank"), timeout=3)
            await asyncio.sleep(0.3)
            self._page = await asyncio.wait_for(
                self._bro.get(PAGE_URL), timeout=12)
            await asyncio.sleep(1)
            if await self._wait_recaptcha():
                self.ready = True
                self._has_auto_token = True
                self._bg_network_enabled = False  # new page, re-enable
                await self._setup_bg_capture()
                return True
        except asyncio.TimeoutError:
            log("reload TIMEOUT")
        except Exception as e:
            log(f"reload err: {e}")
        self.ready = False
        return False

    async def fresh_profile(self) -> bool:
        await self.close()
        if self.source_profile and Path(self.source_profile).exists():
            try:
                p = Path(self.profile)
                if p.exists():
                    shutil.rmtree(p, ignore_errors=True)
                subprocess.run(["cp","-a",self.source_profile,self.profile],
                              capture_output=True, timeout=15)
                clean_locks(self.profile)
                log("Fresh profile cloned")
            except Exception as e:
                log(f"Fresh clone err: {e}")
        return await self.open()

    async def gen_token(self) -> str:
        if not self._page or not self.ready:
            return ""

        try:
            # Step 1: try reading existing auto-token
            tk = await self._read_token()
            if tk:
                self.produced += 1
                self._has_auto_token = False
                log(f"Auto-token harvested ({len(tk)})")
                return tk

            # Step 2: execute + poll 4s
            await ev(self._page, JS_EXEC)
            for _ in range(16):
                await asyncio.sleep(0.25)
                tk = await self._read_token()
                if tk:
                    self.produced += 1
                    log(f"Execute-token OK ({len(tk)})")
                    return tk

            log("Token gen FAIL (no auto, execute timeout)")
        except Exception as e:
            log(f"gen err: {e}")
        return ""


def respond(data):
    print(json.dumps(data), flush=True)


async def main_loop(profile, display, source_profile=None, proxy=None, proxy_pac=None):
    w = TokenWorker(profile, display, source_profile, proxy, proxy_pac)

    if not await w.open():
        await asyncio.sleep(2)
        if not await w.open():
            respond({"ok": False, "error": "browser_open_failed"})
            return

    respond({"ok": True, "status": "ready"})

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=120)
        except asyncio.TimeoutError:
            log("stdin timeout 120s -- quitting")
            break
        if not line:
            break

        try:
            msg = json.loads(line.decode().strip())
        except:
            continue

        cmd = msg.get("cmd", "")

        if cmd == "gen":
            tk = await w.gen_token()
            if tk:
                respond({"ok": True, "token": tk})
            else:
                respond({"ok": False, "error": "token_fail"})

        elif cmd == "reload":
            ok = await w.reload()
            if not ok:
                log("reload FAIL -> restart")
                await w.close()
                ok = await w.open()
            respond({"ok": ok})

        elif cmd == "fresh":
            ok = await w.fresh_profile()
            respond({"ok": ok, "produced": w.produced})

        elif cmd == "quit":
            respond({"ok": True, "produced": w.produced})
            break

        else:
            respond({"ok": False, "error": f"unknown cmd: {cmd}"})

    await w.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--display", default=":99")
    p.add_argument("--source-profile", default=None)
    p.add_argument("--proxy", default=None,
                   help="SOCKS5 proxy for Chrome, e.g. socks5://127.0.0.1:11000")
    p.add_argument("--proxy-pac", default=None,
                   help="PAC file path for Chrome, e.g. /tmp/floppy_proxy.pac")
    a = p.parse_args()
    asyncio.run(main_loop(a.profile, a.display, a.source_profile, a.proxy, a.proxy_pac))
