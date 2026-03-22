# PEDRO PROJECT — Certidoes Automatizadas
# Documentacao Completa do Sistema

---

## VISAO GERAL

Sistema de emissao automatizada de certidoes de 17 sites governamentais brasileiros.
CAPTCHAs resolvidos 100% localmente (Whisper GPU + CLIP + stealth browser).
Zero dependencia de APIs externas como 2captcha.

### Arquitetura Atual

```
                    ┌─────────────────────┐
                    │   Cliente / Dashboard│
                    │  (HTTP ou Redis)     │
                    └────────┬────────────┘
                             │
                    POST /api/v1/job {cpf/cnpj}
                             │
                    ┌────────▼────────────┐
                    │   API (FastAPI)      │
                    │   porta 8000        │
                    │   - cria job        │
                    │   - salva no Redis  │
                    │   - publica na fila │
                    └────────┬────────────┘
                             │
                    LPUSH pedro:queue:jobs
                             │
                    ┌────────▼────────────┐
                    │      Redis Cloud     │
                    │  - fila de jobs     │
                    │  - status em tempo  │
                    │    real             │
                    │  - cache 24h       │
                    │  - parecer         │
                    └────────┬────────────┘
                             │
                    BRPOP (bloqueia ate ter job)
                             │
                    ┌────────▼────────────┐
                    │   Worker (processo)  │
                    │   - consome fila    │
                    │   - executa N       │
                    │     certidoes em    │
                    │     paralelo        │
                    │   - semaforo Chrome │
                    │   - timeout 2min    │
                    │   - auto-cleanup    │
                    └────────┬────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
        ┌─────▼───┐   ┌─────▼───┐   ┌─────▼───┐
        │Chrome 1 │   │Chrome 2 │   │Chrome N │
        │Selenium │   │Puppeteer│   │ ...     │
        │ou Node  │   │+Whisper │   │         │
        └─────────┘   └─────────┘   └─────────┘
              │              │              │
        ┌─────▼──────────────▼──────────────▼───┐
        │         VPN Mullvad (5 namespaces)     │
        │   ns_t0  ns_t1  ns_t2  ns_t3  ns_t4   │
        │   Rotacao automatica em bloqueio       │
        └───────────────────────────────────────┘
```

---

## COMO RODAR

### Prerequisitos

| Software | Versao | Para que |
|----------|--------|----------|
| WSL2 Ubuntu | 22.04 | Ambiente Linux |
| Python | 3.10+ | API + Worker + scripts |
| Node.js | 18+ | Puppeteer/stealth solvers |
| Google Chrome | 146+ | Browser headless |
| chromedriver | mesma do Chrome | Selenium (scripts 1-9) |
| ffmpeg | qualquer | Conversao audio AAC/WAV |
| Xvfb | qualquer | Display virtual |
| CUDA + GPU NVIDIA | compute 7.0+ | Whisper + CLIP |

### Bibliotecas Python

```bash
pip install fastapi uvicorn pydantic redis requests
pip install flask whisper openai-whisper torch transformers Pillow
pip install undetected-chromedriver selenium
```

### Bibliotecas Node.js

```bash
npm install puppeteer-extra puppeteer-extra-plugin-stealth puppeteer
```

### Iniciar tudo (forma rapida)

```bash
# Dentro do WSL2:
cd /mnt/c/Users/workstation/Desktop/PEDRO_PROJECT/PEDRO_PROJECT
bash start_api_wsl.sh
```

Isso faz:
1. Inicia Xvfb (display :121)
2. Sobe VPN Mullvad (5 namespaces)
3. Inicia API na porta 8000
4. Inicia Worker

### Iniciar separadamente

```bash
# Terminal 1: API
python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# Terminal 2: Worker
python3 -m api.worker --max-chrome 5 --id worker-main

# Terminal 3: Worker extra (opcional)
python3 -m api.worker --max-chrome 3 --id worker-2
```

---

## ENDPOINTS DA API

Base: `http://localhost:8000`

### Dashboard
```
GET /dashboard              Tela visual de debug (HTML)
```

### Jobs (principal)
```
POST   /api/v1/job          Criar job (CPF ou CNPJ -> todas as certidoes)
GET    /api/v1/job/{id}     Consultar status + resultados parciais
GET    /api/v1/jobs         Listar jobs recentes
DELETE /api/v1/job/{id}     Deletar job
GET    /api/v1/queue        Status da fila + workers ativos
```

### Download de PDFs
```
GET /api/v1/download/{job_id}/{cert_id}   Baixar PDF local
```

### Logs
```
GET /api/v1/logs/recent?arquivo=pedro&linhas=80   Logs recentes
    arquivo: pedro | jobs | certidoes | erros
```

### Certidoes individuais (opcional)
```
POST /api/v1/certidao/receita-pj     Receita Federal PJ
POST /api/v1/certidao/receita-pf     Receita Federal PF
POST /api/v1/certidao/stj-pf        STJ Pessoa Fisica
POST /api/v1/certidao/stj-pj        STJ Pessoa Juridica
POST /api/v1/certidao/tjgo-civil     TJGO Civel PF
POST /api/v1/certidao/tjgo-processos TJGO Processos
POST /api/v1/certidao/tjgo-criminal  TJGO Criminal PF
POST /api/v1/certidao/trf1           TRF1
POST /api/v1/certidao/tcu            TCU
POST /api/v1/certidao/cpf-receita    CPF Receita (situacao cadastral)
POST /api/v1/certidao/mpf            MPF
POST /api/v1/certidao/stf            STF
POST /api/v1/certidao/trt18          TRT18 Goias
POST /api/v1/certidao/ibama          IBAMA
POST /api/v1/certidao/tst-cndt       TST CNDT
POST /api/v1/certidao/mpgo           MPGO
```

Swagger completo: `http://localhost:8000/docs`

---

## FLUXO DE UM JOB

### 1. Criar job

```bash
curl -X POST http://localhost:8000/api/v1/job \
  -H "Content-Type: application/json" \
  -d '{
    "cpf": "27290000625",
    "nome": "JAIME FERREIRA DE OLIVEIRA NETO",
    "nm_mae": "JORGETA TAHAN OLIVEIRA",
    "dt_nascimento": "21/11/1958"
  }'
```

Resposta:
```json
{
  "job_id": "b1be383d",
  "status": "na_fila",
  "total": 12,
  "certidoes": ["stj-pf","tcu","mpf","trt18","ibama","tst-cndt","mpgo",
                "tjgo-processos","receita-pf","tjgo-civil","tjgo-criminal","trf1-cpf"]
}
```

### 2. Consultar progresso

```bash
curl http://localhost:8000/api/v1/job/b1be383d
```

Resposta (em andamento):
```json
{
  "job_id": "b1be383d",
  "status": "processando",
  "total": 12,
  "concluidas": 5,
  "sucesso": 4,
  "falha": 1,
  "certidoes": {
    "stj-pf": {
      "status": "sucesso",
      "inicio": "2026-03-19T20:30:33",
      "fim": "2026-03-19T20:30:54",
      "resultado": {
        "status": "sucesso",
        "link": "http://tmpfiles.org/.../cert.pdf",
        "link_local": "/api/v1/download/b1be383d/stj-pf"
      }
    },
    "tcu": {"status": "executando", "inicio": "2026-03-19T20:30:35"},
    "mpf": {"status": "na_fila"},
    ...
  }
}
```

### 3. Resultado final (com parecer)

Quando todas terminam, o job fica `concluido` e ganha um `parecer`:

```json
{
  "status": "concluido",
  "parecer": {
    "resumo": "9 de 12 certidoes emitidas com sucesso",
    "situacao": "regular_com_ressalvas",
    "sucesso": 9,
    "falha": 3,
    "alertas": [],
    "detalhes": [
      "STJ Pessoa Fisica: emitida (PDF)",
      "TCU (Tribunal de Contas): NADA CONSTA",
      "MPF (Ministerio Publico Federal): emitida (PDF)",
      "TRT18 (Trabalho GO): FALHA - Chrome session timeout",
      ...
    ]
  }
}
```

### 4. Baixar PDFs

```bash
curl http://localhost:8000/api/v1/download/b1be383d/stj-pf -o certidao_stj.pdf
curl http://localhost:8000/api/v1/download/b1be383d/mpf -o certidao_mpf.pdf
```

---

## CRIAR JOB PARA CNPJ

```bash
curl -X POST http://localhost:8000/api/v1/job \
  -H "Content-Type: application/json" \
  -d '{"cnpj": "26546054000140"}'
```

Executa 10 certidoes: receita-pj, stj-pj, tcu, mpf, trt18, ibama, tst-cndt, mpgo, tjgo-processos, trf1-cnpj

---

## INTEGRACAO VIA REDIS (sem API)

O cliente pode publicar jobs direto no Redis:

```python
import redis, json, uuid
from datetime import datetime

r = redis.from_url("redis://default:SENHA@HOST:PORTA")

job_id = str(uuid.uuid4())[:8]
job = {
    "job_id": job_id,
    "status": "na_fila",
    "tipo": "cpf",
    "documento": "27290000625",
    "params": {
        "cpf": "27290000625",
        "nome": "JAIME FERREIRA DE OLIVEIRA NETO",
        "nm_mae": "JORGETA TAHAN OLIVEIRA",
        "dt_nascimento": "21/11/1958"
    },
    "criado_em": datetime.now().isoformat(),
    "atualizado_em": datetime.now().isoformat(),
    "total": 0,
    "concluidas": 0,
    "sucesso": 0,
    "falha": 0,
    "certidoes": {}
}

r.setex(f"pedro:job:{job_id}", 86400*3, json.dumps(job))
r.lpush("pedro:queue:jobs", job_id)
```

O worker preenche as certidoes automaticamente e executa.

Consultar resultado:
```python
raw = r.get(f"pedro:job:{job_id}")
job = json.loads(raw)
print(job["status"])  # na_fila -> processando -> concluido
```

Schema completo: ver `api/REDIS_SCHEMA.md`

---

## CERTIDOES DISPONIVEIS

### Para CPF (ate 12)

| # | ID | Site | CAPTCHA | Dados extras |
|---|------|------|---------|-------------|
| 1 | receita-pf | Receita Federal PF | nenhum | dt_nascimento |
| 4 | stj-pf | STJ Pessoa Fisica | nenhum | - |
| 6 | tjgo-civil | TJGO Civel | nenhum | nome, nm_mae, dt_nascimento |
| 7 | tjgo-processos | TJGO Processos | nenhum | - |
| 8 | tjgo-criminal | TJGO Criminal | nenhum | nome, nm_mae, dt_nascimento |
| 9 | trf1-cpf | TRF1 Criminal+Civil | nenhum | - |
| 11 | tcu | TCU | reCAPTCHA v2 audio + Whisper base | - |
| 13 | mpf | MPF | Turnstile stealth (1-2s) | - |
| 15 | trt18 | TRT18 Goias | nenhum | - |
| 16 | ibama | IBAMA | reCAPTCHA Enterprise invisible | - |
| 17 | tst-cndt | TST CNDT | Audio PT-BR + Whisper medium | - |
| 18 | mpgo | MPGO | reCAPTCHA v2 stealth | - |

### Para CNPJ (ate 10)

| # | ID | Site | CAPTCHA |
|---|------|------|---------|
| 1 | receita-pj | Receita Federal PJ | nenhum |
| 5 | stj-pj | STJ Pessoa Juridica | nenhum |
| 7 | tjgo-processos | TJGO Processos | nenhum |
| 9 | trf1-cnpj | TRF1 Criminal | nenhum |
| 11 | tcu | TCU | reCAPTCHA v2 audio + Whisper |
| 13 | mpf | MPF | Turnstile stealth |
| 15 | trt18 | TRT18 Goias | nenhum |
| 16 | ibama | IBAMA | reCAPTCHA Enterprise |
| 17 | tst-cndt | TST CNDT | Audio PT-BR + Whisper |
| 18 | mpgo | MPGO | reCAPTCHA v2 stealth |

---

## CACHE

Certidoes com sucesso sao cacheadas no Redis por 24h.
Se o mesmo CPF/CNPJ for solicitado novamente, as certidoes cacheadas retornam instantaneamente (status `cache`) e so as que falharam sao re-executadas.

---

## VPN / ROTACAO DE IP

5 tuneis WireGuard via Mullvad (servidores Brasil):
```
ns_t0: 169.150.198.75  (Sao Paulo)
ns_t1: 169.150.198.88  (Sao Paulo)
ns_t2: 103.139.178.106 (Fortaleza)
ns_t3: 103.139.178.166 (Fortaleza)
ns_t4: 155.2.219.89    (Sao Paulo)
```

Scripts 11-18 usam rotacao automatica:
```
Bloqueio (403/429/Cloudflare)
  -> proximo namespace (ns_t0 -> ns_t1 -> ...)
  -> retry
  -> ate 10 tentativas
```

Scripts 1-9 rodam direto no host (sem VPN).

---

## LOGS

4 arquivos separados em `logs/`:

| Arquivo | Conteudo |
|---------|----------|
| `pedro.log` | Tudo (API + Worker + certidoes) |
| `jobs.log` | Lifecycle de jobs (criacao, inicio, conclusao) |
| `certidoes.log` | Cada certidao (inicio, tempo, resultado, link) |
| `erros.log` | Apenas warnings e erros |

Acessiveis via API:
```bash
curl "http://localhost:8000/api/v1/logs/recent?arquivo=certidoes&linhas=50"
```

Ou pelo dashboard (tabs Tudo/Jobs/Certidoes/Erros).

---

## PROTECOES DO WORKER

| Protecao | Descricao |
|----------|-----------|
| **Semaforo Chrome** | Max N Chrome simultaneos (default 5) |
| **Timeout por certidao** | 2 minutos, mata Chrome orfao |
| **Timeout por job** | 5 minutos total, forca conclusao |
| **Cleanup periodico** | A cada 60s, cancela jobs vazios e forca conclusao de travados >10min |
| **Jobs vazios** | Detectados e cancelados automaticamente |
| **Graceful shutdown** | SIGINT/SIGTERM libera recursos |

---

## ESTRUTURA DE ARQUIVOS

```
PEDRO_PROJECT/
├── 1-certidao_receita_pj.py      Scripts extratores (17 scripts ativos)
├── 2-certidao_receita_pf.py
├── ...
├── 18-certidao_MPGO.py
│
├── api/                           API + Worker + Jobs
│   ├── main.py                    FastAPI (endpoints HTTP + dashboard)
│   ├── worker.py                  Worker (consome fila Redis)
│   ├── jobs.py                    Gerenciamento de jobs no Redis
│   ├── dashboard.py               Dashboard HTML visual
│   ├── logger.py                  Logging centralizado (4 arquivos)
│   ├── models.py                  Pydantic models
│   ├── config.py                  Configuracoes
│   ├── utils.py                   Helpers compartilhados
│   ├── downloads/                 PDFs baixados localmente
│   ├── REDIS_SCHEMA.md            Schema Redis para integracao
│   ├── test_api.py                Testes mock (136 testes)
│   ├── test_real.py               Testes com dados reais
│   └── requirements.txt           Dependencias Python
│
├── infra/                         Solvers de CAPTCHA (JS + Python)
│   ├── recaptcha_audio_solver.js  reCAPTCHA v2 audio (TCU)
│   ├── recaptcha_enterprise_solver.js  reCAPTCHA Enterprise (IBAMA)
│   ├── aws_waf_audio_solver.js    AWS WAF audio (STF)
│   ├── stf_certidao_solver.js     STF completo (WAF + Enterprise + API)
│   ├── hcaptcha_visual_solver.js  hCaptcha visual (CPF Receita)
│   ├── mpf_stealth_solver.js      Turnstile stealth (MPF)
│   ├── tst_captcha_solver.js      TST custom audio
│   ├── mpgo_recaptcha_solver.js   MPGO reCAPTCHA stealth
│   ├── local_captcha_solver.py    Orchestrator reCAPTCHA -> Whisper
│   ├── aws_waf_solver.py          Orchestrator AWS WAF -> Whisper medium
│   ├── hcaptcha_solver.py         Orchestrator hCaptcha -> CLIP
│   └── tst_captcha_solver.py      Orchestrator TST -> Whisper + parser PT-BR
│
├── logs/                          Logs separados por tipo
│   ├── pedro.log
│   ├── jobs.log
│   ├── certidoes.log
│   └── erros.log
│
├── setup_vpn_wsl2.sh             Setup VPN Mullvad (5 namespaces)
├── rotate.sh                      Rotacao manual de VPN
├── start_api_wsl.sh              Inicia API + Worker no WSL2
├── TUTORIAL.md                    Este arquivo
│
└── bk/                            Backup de arquivos nao usados
    ├── docs_txt/                  Docs antigos por certidao
    ├── infra_ref/                 Scripts de referencia
    ├── scripts_debug/             Scripts de debug
    ├── scripts_teste/             Scripts de teste
    ├── shell_scripts_teste/       Shell scripts de teste
    ├── test_results/              Resultados de testes antigos
    └── vpn_configs_extra/         Configs VPN extras
```

---

## CONFIGURACAO DO WSL2

Arquivo `C:\Users\workstation\.wslconfig`:
```ini
[wsl2]
memory=24GB
swap=8GB
processors=10
```

Recursos da maquina:
- RAM: 32GB total, 24GB para WSL2
- GPU: NVIDIA RTX 4080 (Whisper + CLIP)
- Chrome simultaneos: ate 5 (configuravel via --max-chrome)

---

## TROUBLESHOOTING

### Worker morre (exit code 9)
OOM kill. Reduzir `--max-chrome` ou aumentar memoria no `.wslconfig`.

### Jobs ficam "na_fila" com 0/0
Job criado sem certidoes. O worker auto-cancela a cada 60s.
Se persistir, verificar se o worker esta rodando: `GET /api/v1/queue`

### Certidao fica "executando" por muito tempo
Timeout automatico de 2 minutos. Se passar, o cleanup do worker forca erro.

### Chrome orfao consumindo memoria
```bash
wsl -d Ubuntu-22.04 -- pkill -9 -f chrome
```

### VPN nao conecta
```bash
wsl -d Ubuntu-22.04 -- bash setup_vpn_wsl2.sh
wsl -d Ubuntu-22.04 -- bash rotate.sh status
```

### Logs nao aparecem
Verificar se a pasta `logs/` existe e tem permissao de escrita.
```bash
ls -la logs/
```
