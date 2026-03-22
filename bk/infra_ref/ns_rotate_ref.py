"""
ns_rotate - Biblioteca Python para requests via namespaces com auto-rotacao.

Uso basico:
    from ns_rotate import NSSession
    
    s = NSSession()
    r = s.get("https://api.exemplo.com/dados")
    print(r.status_code, r.text)

Uso avancado:
    s = NSSession(
        prefer="br",           # priorizar servidores BR
        max_rotations=10,      # max rotacoes por request
        namespaces=["ns_t0","ns_t1","ns_t2","ns_t3","ns_t4"],
    )
    
    # Headers customizados
    s.headers.update({"Authorization": "Bearer xxx"})
    
    # Request com retry automatico
    r = s.get("https://site.com/api", timeout=10)
    
    # Forcar namespace
    r = s.get("https://site.com", ns="ns_t2")
    
    # Sem rotacao
    r = s.get("https://site.com", auto_rotate=False)
"""

import subprocess
import json
import random
import time
import os
import logging
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("ns_rotate")

POOL_FILE = "/home/ramza/mullvad_wg/server_pool_full.json"
KEYS_DIR = "/home/ramza/mullvad_wg/keys"
MAPPING_FILE = "/home/ramza/mullvad_wg/ns_mapping.json"
STATE_FILE = "/home/ramza/mullvad_wg/rotation_state.json"
ROTATE_SCRIPT = "/home/ramza/mullvad_wg/rotate.sh"

BLOCK_CODES = {400, 401, 403, 407, 429, 451, 503}
BLOCK_PATTERNS = [
    "cloudflare", "captcha", "rate limit", "too many request",
    "forbidden", "access denied", "blocked", "challenge-platform",
    "cf-browser-verification", "just a moment", "ray id",
]


@dataclass
class NSResponse:
    """Resposta de um request via namespace."""
    status_code: int = 0
    text: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    url: str = ""
    ns_used: str = ""
    rotations: int = 0
    ok: bool = False
    elapsed: float = 0.0
    
    def json(self):
        return json.loads(self.text)
    
    def raise_for_status(self):
        if not self.ok:
            raise Exception(f"HTTP {self.status_code} via {self.ns_used}: {self.text[:200]}")


class NSSession:
    """Session HTTP que executa via network namespaces com auto-rotacao."""
    
    def __init__(
        self,
        prefer: str = "br",
        max_rotations: int = 10,
        namespaces: Optional[List[str]] = None,
        timeout: int = 15,
    ):
        self.prefer = prefer
        self.max_rotations = max_rotations
        self.namespaces = namespaces or ["ns_t0", "ns_t1", "ns_t2", "ns_t3", "ns_t4"]
        self.timeout = timeout
        self.headers: Dict[str, str] = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        self.cookies: Dict[str, str] = {}
        self._ns_idx = 0
        self._pool = self._load_pool()
        self._ua_pool = [
            "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        ]
    
    def _load_pool(self) -> List[Dict]:
        try:
            with open(POOL_FILE) as f:
                return json.load(f)
        except:
            return []
    
    def _next_ns(self) -> str:
        ns = self.namespaces[self._ns_idx % len(self.namespaces)]
        self._ns_idx += 1
        return ns
    
    def _rotate_ua(self):
        self.headers["User-Agent"] = random.choice(self._ua_pool)
    
    def _is_blocked(self, status_code: int, body: str) -> bool:
        if status_code in BLOCK_CODES:
            return True
        body_lower = body.lower()
        return any(p in body_lower for p in BLOCK_PATTERNS)
    
    def _rotate_server(self, ns: str):
        """Rotaciona servidor WG de um namespace. Prioriza BR."""
        filters = [self.prefer, "", None]  # br -> qualquer
        for filt in filters:
            if filt is None:
                break
            try:
                cmd = [ROTATE_SCRIPT, "rotate", ns, filt] if filt else [ROTATE_SCRIPT, "rotate", ns]
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=15
                )
                if "OK" in result.stdout:
                    logger.info(f"Rotacionado {ns} (filtro={filt}): {result.stdout.strip()}")
                    return True
            except Exception as e:
                logger.warning(f"Erro rotacionando {ns}: {e}")
        return False
    
    def _build_curl_cmd(
        self,
        method: str,
        url: str,
        headers: Optional[Dict] = None,
        data: Optional[str] = None,
        json_data: Optional[Any] = None,
        timeout: Optional[int] = None,
    ) -> List[str]:
        cmd = ["curl", "-s", "-S", "--max-time", str(timeout or self.timeout)]
        cmd += ["-w", "\n__NS_META__%{http_code}|%{url_effective}"]
        cmd += ["-X", method.upper()]
        
        # Headers
        all_headers = {**self.headers, **(headers or {})}
        if json_data is not None:
            all_headers["Content-Type"] = "application/json"
        for k, v in all_headers.items():
            cmd += ["-H", f"{k}: {v}"]
        
        # Cookies
        if self.cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            cmd += ["-H", f"Cookie: {cookie_str}"]
        
        # Body
        if json_data is not None:
            cmd += ["-d", json.dumps(json_data)]
        elif data is not None:
            cmd += ["-d", data]
        
        # Seguir redirects
        cmd += ["-L", "--max-redirs", "5"]
        
        # Include response headers
        cmd += ["-D", "/dev/stderr"]
        
        cmd.append(url)
        return cmd
    
    def _exec_in_ns(self, ns: str, cmd: List[str]) -> tuple:
        """Executa comando dentro do namespace. Retorna (exit_code, stdout, stderr)."""
        full_cmd = ["sudo", "ip", "netns", "exec", ns] + cmd
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=(self.timeout + 5),
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return 28, "", "timeout"
        except Exception as e:
            return 1, "", str(e)
    
    def request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict] = None,
        data: Optional[str] = None,
        json_data: Optional[Any] = None,
        timeout: Optional[int] = None,
        ns: Optional[str] = None,
        auto_rotate: bool = True,
    ) -> NSResponse:
        """Faz HTTP request via namespace com auto-rotacao."""
        
        current_ns = ns or self._next_ns()
        rotations = 0
        tried_ns = set()
        t0 = time.time()
        
        while True:
            self._rotate_ua()
            curl_cmd = self._build_curl_cmd(method, url, headers, data, json_data, timeout)
            
            exit_code, stdout, stderr = self._exec_in_ns(current_ns, curl_cmd)
            
            # Parsear meta
            status_code = 0
            effective_url = url
            body = stdout
            
            if "__NS_META__" in stdout:
                parts = stdout.rsplit("\n__NS_META__", 1)
                body = parts[0]
                meta = parts[1].strip()
                try:
                    code_str, eff_url = meta.split("|", 1)
                    status_code = int(code_str)
                    effective_url = eff_url
                except:
                    pass
            
            # Parsear response headers do stderr
            resp_headers = {}
            for line in stderr.split("\n"):
                if ": " in line:
                    k, v = line.split(": ", 1)
                    resp_headers[k.strip()] = v.strip()
            
            # Checar bloqueio
            blocked = self._is_blocked(status_code, body)
            
            if blocked and auto_rotate and rotations < self.max_rotations:
                rotations += 1
                tried_ns.add(current_ns)
                
                logger.info(
                    f"[ns_rotate] BLOQUEIO {status_code} em {current_ns} "
                    f"- rotacao {rotations}/{self.max_rotations}"
                )
                
                # Round-robin pelos NS disponiveis
                if ns:
                    # NS forcado - rotacionar servidor
                    self._rotate_server(current_ns)
                else:
                    # Proximo NS
                    current_ns = self._next_ns()
                    # Se ja passou por todos, rotacionar servidores
                    if len(tried_ns) >= len(self.namespaces):
                        logger.info(f"[ns_rotate] Todos NS tentados, rotacionando servidores...")
                        self._rotate_server(current_ns)
                        tried_ns.clear()
                
                time.sleep(1 + random.random())
                continue
            
            # Retornar resposta
            elapsed = time.time() - t0
            return NSResponse(
                status_code=status_code,
                text=body,
                headers=resp_headers,
                url=effective_url,
                ns_used=current_ns,
                rotations=rotations,
                ok=(200 <= status_code < 400),
                elapsed=elapsed,
            )
    
    def get(self, url: str, **kwargs) -> NSResponse:
        return self.request("GET", url, **kwargs)
    
    def post(self, url: str, **kwargs) -> NSResponse:
        return self.request("POST", url, **kwargs)
    
    def put(self, url: str, **kwargs) -> NSResponse:
        return self.request("PUT", url, **kwargs)
    
    def delete(self, url: str, **kwargs) -> NSResponse:
        return self.request("DELETE", url, **kwargs)
    
    def patch(self, url: str, **kwargs) -> NSResponse:
        return self.request("PATCH", url, **kwargs)
    
    def status(self) -> Dict:
        """Retorna status de todos os namespaces."""
        result = {}
        for ns in self.namespaces:
            exit_code, stdout, _ = self._exec_in_ns(
                ns, ["curl", "-s", "--max-time", "5", "https://ifconfig.me"]
            )
            result[ns] = {
                "ip": stdout.strip() if exit_code == 0 else "OFFLINE",
                "ok": exit_code == 0,
            }
        return result


# ============================================================
# Conveniencia: funcoes standalone
# ============================================================
_default_session = None

def _get_session() -> NSSession:
    global _default_session
    if _default_session is None:
        _default_session = NSSession()
    return _default_session

def ns_get(url: str, **kwargs) -> NSResponse:
    """GET rapido via namespace com auto-rotacao."""
    return _get_session().get(url, **kwargs)

def ns_post(url: str, **kwargs) -> NSResponse:
    """POST rapido via namespace com auto-rotacao."""
    return _get_session().post(url, **kwargs)

def ns_request(method: str, url: str, **kwargs) -> NSResponse:
    """Request generico via namespace."""
    return _get_session().request(method, url, **kwargs)

def ns_status() -> Dict:
    """Status de todos os namespaces."""
    return _get_session().status()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        s = NSSession()
        for ns, info in s.status().items():
            print(f"  {ns}: {info['ip']}")
    elif len(sys.argv) > 1 and sys.argv[1] == "test":
        url = sys.argv[2] if len(sys.argv) > 2 else "https://httpbin.org/ip"
        s = NSSession()
        r = s.get(url)
        print(f"NS: {r.ns_used} | HTTP {r.status_code} | Rotacoes: {r.rotations} | {r.elapsed:.1f}s")
        print(r.text[:500])
    else:
        print("Uso: python3 ns_rotate.py {status|test [url]}")
        print()
        print("Como lib:")
        print("  from ns_rotate import NSSession, ns_get")
        print("  r = ns_get('https://api.exemplo.com')")
        print("  print(r.status_code, r.text)")
