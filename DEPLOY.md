# PEDRO PROJECT — Deploy Docker

Guia completo para subir o sistema em qualquer maquina.

---

## Arquitetura

```
┌──────────────────────────────────────────────────────────┐
│                    Qualquer Maquina                       │
│                                                          │
│  ┌─────────────┐     ┌──────────────────────────────┐   │
│  │  pedro-api   │     │  pedro-worker                │   │
│  │  (FastAPI)   │     │  Chrome + Node + Whisper     │   │
│  │  porta 8000  │     │  Xvfb + VPN (opcional)       │   │
│  │  ~230MB      │     │  ~19GB                       │   │
│  └──────┬───────┘     └──────┬───────────────────────┘   │
│         │                    │                           │
│         └────────┬───────────┘                           │
│                  │                                       │
│         ┌────────▼──────────┐                            │
│         │   Redis Cloud      │                            │
│         │   (fila + cache)   │                            │
│         └───────────────────┘                            │
└──────────────────────────────────────────────────────────┘
```

**Todos os workers de todas as maquinas conectam no mesmo Redis.**
Escalar = subir mais containers worker.

---

## Requisitos

| Requisito | API | Worker GPU | Worker sem GPU |
|-----------|-----|-----------|----------------|
| Docker | sim | sim | sim |
| NVIDIA Driver | nao | sim | nao |
| nvidia-container-toolkit | nao | sim | nao |
| RAM minima | 512MB | 4GB | 2GB |
| GPU | nao | NVIDIA (CUDA) | nao |

---

## Setup Rapido (maquina com GPU)

```bash
# 1. Clonar projeto
git clone <repo> pedro-project
cd pedro-project

# 2. Criar .env
cp .env.example .env
# Editar MAX_CHROME conforme RAM da maquina

# 3. Subir tudo
docker compose up -d

# 4. Acessar
# Dashboard: http://localhost:8000/dashboard
# Swagger:   http://localhost:8000/docs
```

Ou com setup automatico:
```bash
bash setup.sh
```

---

## Setup por Cenario

### Maquina principal (API + Worker)
```bash
docker compose up -d
# Sobe: api (porta 8000) + worker-gpu
```

### Maquina extra com GPU (so worker)
```bash
# Nao precisa da API — so o worker conectando no mesmo Redis
cp .env.example .env
nano .env   # ajustar MAX_CHROME e WORKER_ID

docker compose up -d worker-gpu
```

### Maquina sem GPU (so certidoes sem CAPTCHA)
```bash
docker compose --profile nogpu up -d worker-nogpu
```

### Worker com VPN Mullvad
```bash
# 1. Colocar config WireGuard na pasta docker/vpn/
mkdir -p docker/vpn
cp /caminho/wg0.conf docker/vpn/

# 2. Subir
docker compose --profile vpn up -d worker-vpn
```

### Escalar workers na mesma maquina
```bash
# 3 workers GPU simultaneos
docker compose up -d --scale worker-gpu=3
```

---

## Configuracao (.env)

```bash
# Redis (MESMO para todas as maquinas)
REDIS_URL=redis://default:SENHA@HOST:PORTA

# Chrome simultaneos (ajustar pela RAM)
#   32GB  → MAX_CHROME=6
#   64GB  → MAX_CHROME=12
#   128GB → MAX_CHROME=25
#   256GB → MAX_CHROME=50
MAX_CHROME=6

# Nome do worker (unico por maquina)
WORKER_ID=worker-srv1

# Porta API (so na maquina da API)
API_PORT=8000
```

---

## VPN (WireGuard/Mullvad)

Para rodar com VPN dentro do container:

```bash
# 1. Gerar config na conta Mullvad:
#    https://mullvad.net/en/account/wireguard-config

# 2. Salvar em docker/vpn/wg0.conf
mkdir -p docker/vpn
cat > docker/vpn/wg0.conf << 'EOF'
[Interface]
PrivateKey = SUA_PRIVATE_KEY
Address = 10.x.x.x/32
DNS = 10.64.0.1

[Peer]
PublicKey = PUBLIC_KEY_MULLVAD
AllowedIPs = 0.0.0.0/0
Endpoint = SERVER:PORT
EOF

# 3. Subir worker-vpn
docker compose --profile vpn up -d worker-vpn
```

Multiplas configs VPN (varios IPs):
```bash
docker/vpn/
├── wg0.conf   # Sao Paulo 1
├── wg1.conf   # Sao Paulo 2
└── wg2.conf   # Fortaleza
```

O entrypoint sobe TODAS as interfaces automaticamente.

---

## Comandos Uteis

```bash
# Ver status
docker compose ps

# Ver logs em tempo real
docker compose logs -f worker-gpu

# Reiniciar worker
docker compose restart worker-gpu

# Parar tudo
docker compose down

# Parar e remover volumes
docker compose down -v

# Ver uso de recursos
docker stats

# Entrar no container
docker compose exec worker-gpu bash

# Rebuild apos mudanca no codigo
docker compose build --no-cache worker-gpu
docker compose up -d worker-gpu
```

---

## Deploy no Cluster (7 maquinas)

### Maquina 1: Dual Xeon + 256GB + RTX 3090
```bash
# .env
REDIS_URL=redis://...
MAX_CHROME=50
WORKER_ID=worker-dual1-3090

docker compose up -d api worker-gpu
```

### Maquina 2: Dual Xeon + 128GB + RTX 2060
```bash
MAX_CHROME=25
WORKER_ID=worker-dual2-2060
docker compose up -d worker-gpu
```

### Maquina 3-4: Single Xeon + 64GB + GTX 1660
```bash
MAX_CHROME=12
WORKER_ID=worker-xeon3
docker compose up -d worker-gpu
```

### Maquina 5: Ryzen 3900x + 64GB + GTX 1660
```bash
MAX_CHROME=12
WORKER_ID=worker-ryzen
docker compose up -d worker-gpu
```

### Maquina 6: i7 14th + 32GB + RTX 4080
```bash
MAX_CHROME=6
WORKER_ID=worker-i7
docker compose up -d worker-gpu
```

### Maquina 7: Ryzen 3600x + RX 570 (sem CUDA)
```bash
MAX_CHROME=8
WORKER_ID=worker-nogpu
docker compose --profile nogpu up -d worker-nogpu
```

**Total: ~125 Chrome simultaneos, ~18.000 jobs/dia**

---

## Endpoints da API

```
GET  /dashboard                        Dashboard visual
GET  /health                           Health check
POST /api/v1/job                       Criar job (CPF ou CNPJ)
GET  /api/v1/job/{id}                  Status do job
GET  /api/v1/jobs                      Listar jobs
DELETE /api/v1/job/{id}                Deletar job
GET  /api/v1/queue                     Fila + workers
GET  /api/v1/download/{job}/{cert}     Baixar PDF
GET  /api/v1/logs/recent               Logs
GET  /docs                             Swagger UI
```

---

## Troubleshooting

### Worker nao conecta no Redis
```bash
docker compose exec worker-gpu python3 -c "
import redis
r = redis.from_url('$REDIS_URL')
r.ping()
print('OK')
"
```

### Chrome crashando (OOM)
Reduzir MAX_CHROME no .env e reiniciar:
```bash
docker compose restart worker-gpu
```

### GPU nao detectada no container
```bash
# Verificar nvidia-container-toolkit
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

### Ver qual certidao esta travando
```bash
docker compose exec worker-gpu cat /app/logs/certidoes.log | tail -20
```

### Limpar tudo e recomecar
```bash
docker compose down -v
docker system prune -af
docker compose up -d --build
```
