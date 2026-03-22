#!/usr/bin/env python3
"""
Serviço interno de resolução de reCAPTCHA - estilo 2captcha
Pool de browsers com Xvfb, pré-resolve tokens e serve via API HTTP

Uso:
  python3 captcha_service.py [--workers 3] [--port 5555] [--pool-size 10]

API:
  GET /token                          → token captcha pronto
  GET /consulta/{cpf}/{data_nasc}     → consulta CadÚnico completa
  GET /status                         → stats do serviço
  GET /health                         → health check
"""
import os, sys, time, json, threading, queue, signal
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor
import httpx

# Config
SITEKEY = "6LfRVZIeAAAAAIwNb1YLXXL4T6W9-2tWRZ0Vufzk"
API_BASE = "https://cadunico.dataprev.gov.br/transacional/api"
VERSAO = "1.36.00"
NUM_WORKERS = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 3
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 5555
POOL_SIZE = int(sys.argv[sys.argv.index("--pool-size") + 1]) if "--pool-size" in sys.argv else 10
TOKEN_TTL = 110  # tokens válidos por ~2min, descartamos em 110s

# Credenciais/perfis (nao usar /tmp para estado de CadUnico)
CRED_DIR = Path("/home/ramza/credenciais_cadunico")
CRED_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_BASE = CRED_DIR / "uc_profiles"
PROFILE_BASE.mkdir(parents=True, exist_ok=True)

# Garantir Xvfb
if not os.environ.get('DISPLAY'):
    os.system("Xvfb :99 -screen 0 1920x1080x24 &>/dev/null &")
    time.sleep(1)
    os.environ['DISPLAY'] = ':99'

# Pool de tokens resolvidos
token_pool = queue.Queue(maxsize=POOL_SIZE * 2)
stats = {
    "tokens_gerados": 0,
    "tokens_servidos": 0,
    "tokens_expirados": 0,
    "consultas": 0,
    "consultas_ok": 0,
    "consultas_erro": 0,
    "erros_captcha": 0,
    "inicio": time.time(),
    "workers_ativos": 0,
}
lock = threading.Lock()
running = True


def criar_driver(worker_id):
    """Cria browser undetected para resolver captchas"""
    import undetected_chromedriver as uc
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_argument(f"--user-data-dir={PROFILE_BASE / f'captcha_worker_{worker_id}'}")
    driver = uc.Chrome(options=options, version_main=144)
    driver.get("https://cadunico.dataprev.gov.br")
    time.sleep(3)
    return driver


def resolver_captcha(driver):
    """Resolve um captcha e retorna token"""
    token = driver.execute_script("""
        return new Promise((resolve, reject) => {
            if (window.grecaptcha && window.grecaptcha.execute) {
                grecaptcha.execute('""" + SITEKEY + """', {action: 'consulta'})
                    .then(resolve).catch(reject);
            } else {
                let s = document.createElement('script');
                s.src = 'https://www.google.com/recaptcha/api.js?render=""" + SITEKEY + """';
                s.onload = () => {
                    grecaptcha.ready(() => {
                        grecaptcha.execute('""" + SITEKEY + """', {action: 'consulta'})
                            .then(resolve).catch(reject);
                    });
                };
                document.head.appendChild(s);
            }
            setTimeout(() => reject('timeout'), 25000);
        });
    """)
    return token


def worker_loop(worker_id):
    """Loop de worker que pré-resolve captchas continuamente"""
    global running
    driver = None
    restarts = 0

    with lock:
        stats["workers_ativos"] += 1

    print(f"[Worker {worker_id}] Iniciando...")

    while running:
        try:
            if driver is None:
                driver = criar_driver(worker_id)
                print(f"[Worker {worker_id}] Browser pronto (restart #{restarts})")

            # Só resolver se pool não está cheio
            if token_pool.qsize() < POOL_SIZE:
                t0 = time.time()
                token = resolver_captcha(driver)
                elapsed = time.time() - t0

                token_pool.put({
                    "token": token,
                    "timestamp": time.time(),
                    "worker": worker_id,
                    "elapsed": round(elapsed, 2),
                })

                with lock:
                    stats["tokens_gerados"] += 1

                print(f"[Worker {worker_id}] Token #{stats['tokens_gerados']} em {elapsed:.1f}s (pool: {token_pool.qsize()})")
            else:
                time.sleep(1)

        except Exception as e:
            print(f"[Worker {worker_id}] Erro: {e}")
            with lock:
                stats["erros_captcha"] += 1

            if driver:
                try:
                    driver.quit()
                except:
                    pass
                driver = None
                restarts += 1
                time.sleep(2)

    if driver:
        try:
            driver.quit()
        except:
            pass

    with lock:
        stats["workers_ativos"] -= 1
    print(f"[Worker {worker_id}] Encerrado")


def get_token():
    """Pega token válido do pool, descartando expirados"""
    while not token_pool.empty():
        item = token_pool.get_nowait()
        age = time.time() - item["timestamp"]
        if age < TOKEN_TTL:
            with lock:
                stats["tokens_servidos"] += 1
            return item
        else:
            with lock:
                stats["tokens_expirados"] += 1

    # Pool vazio - resolver na hora
    return None


def consultar_cpf(cpf, data_nascimento):
    """Consulta CPF usando token do pool"""
    item = get_token()

    if item is None:
        return {"status": 503, "error": "Sem tokens disponíveis, aguarde pool encher"}

    r = httpx.get(
        f"{API_BASE}/transacional-api/v1/pessoa/{cpf}/cadunico",
        params={
            "dataNascimento": data_nascimento,
            "captchaResponse": item["token"],
        },
        headers={
            "CnasVersao": VERSAO,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=15,
    )

    with lock:
        stats["consultas"] += 1
        if r.status_code == 200:
            stats["consultas_ok"] += 1
        else:
            stats["consultas_erro"] += 1

    try:
        data = r.json()
    except:
        data = r.text

    return {"status": r.status_code, "data": data, "token_age": round(time.time() - item["timestamp"], 1)}


class CaptchaHandler(BaseHTTPRequestHandler):
    """Handler HTTP para servir tokens e consultas"""

    def log_message(self, format, *args):
        pass  # Silenciar logs HTTP

    def respond(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        # GET /token
        if path == "/token":
            item = get_token()
            if item:
                self.respond(200, item)
            else:
                self.respond(503, {"error": "Pool vazio", "pool_size": token_pool.qsize()})

        # GET /consulta/{cpf}/{data_nasc}
        elif path.startswith("/consulta/"):
            parts = path.split("/")
            if len(parts) >= 4:
                cpf = parts[2].replace(".", "").replace("-", "")
                dn = parts[3]
                result = consultar_cpf(cpf, dn)
                self.respond(result.get("status", 200), result)
            else:
                self.respond(400, {"error": "Uso: /consulta/{cpf}/{DD-MM-AAAA}"})

        # GET /status
        elif path == "/status":
            uptime = time.time() - stats["inicio"]
            rate = stats["tokens_gerados"] / (uptime / 3600) if uptime > 0 else 0
            self.respond(200, {
                **stats,
                "pool_size": token_pool.qsize(),
                "uptime_h": round(uptime / 3600, 2),
                "tokens_por_hora": round(rate),
                "projecao_dia": round(rate * 24),
            })

        # GET /health
        elif path == "/health":
            self.respond(200, {"status": "UP", "pool": token_pool.qsize(), "workers": stats["workers_ativos"]})

        else:
            self.respond(404, {"error": "Endpoints: /token, /consulta/{cpf}/{dn}, /status, /health"})


def main():
    global running

    print(f"""
╔══════════════════════════════════════════╗
║   CAPTCHA SERVICE - CadÚnico GOD MODE   ║
║                                          ║
║   Workers:    {NUM_WORKERS:<26}║
║   Pool size:  {POOL_SIZE:<26}║
║   Porta:      {PORT:<26}║
║   TTL token:  {TOKEN_TTL}s{' ' * 23}║
╚══════════════════════════════════════════╝
    """)

    # Iniciar workers
    for i in range(NUM_WORKERS):
        t = threading.Thread(target=worker_loop, args=(i,), daemon=True)
        t.start()
        time.sleep(2)  # Escalonar início

    # Servidor HTTP
    server = HTTPServer(("0.0.0.0", PORT), CaptchaHandler)
    print(f"\n[Server] Escutando em http://0.0.0.0:{PORT}")
    print(f"[Server] Endpoints:")
    print(f"  GET http://localhost:{PORT}/token")
    print(f"  GET http://localhost:{PORT}/consulta/{{cpf}}/{{DD-MM-AAAA}}")
    print(f"  GET http://localhost:{PORT}/status")
    print(f"  GET http://localhost:{PORT}/health")
    print(f"\n[Server] Ctrl+C para parar\n")

    def shutdown(sig, frame):
        global running
        print("\n[Server] Encerrando...")
        running = False
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server.serve_forever()
    except:
        pass

    print("[Server] Encerrado")


if __name__ == "__main__":
    main()
