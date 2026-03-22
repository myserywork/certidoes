# PEDRO PROJECT — Schema Redis

## Como o cliente integra

O cliente principal pode interagir com o sistema de 2 formas:
1. **Via API HTTP** (POST /api/v1/job, GET /api/v1/job/{id})
2. **Direto no Redis** (LPUSH na fila, GET do resultado)

A forma 2 é mais rápida e não depende da API estar rodando — só do Worker.

---

## Redis Keys

### Fila de Jobs
```
Key:    pedro:queue:jobs
Type:   LIST (FIFO)
Valor:  job_id (string, ex: "b1be383d")

# Cliente publica:
LPUSH pedro:queue:jobs "b1be383d"

# Worker consome:
BRPOP pedro:queue:jobs 0
```

### Job
```
Key:    pedro:job:{job_id}
Type:   STRING (JSON)
TTL:    3 dias

Exemplo:
{
  "job_id": "b1be383d",
  "status": "na_fila" | "processando" | "concluido",
  "tipo": "cpf" | "cnpj",
  "documento": "27290000625",
  "params": {
    "cpf": "27290000625",
    "nome": "JAIME FERREIRA DE OLIVEIRA NETO",
    "nm_mae": "JORGETA TAHAN OLIVEIRA",
    "dt_nascimento": "21/11/1958"
  },
  "criado_em": "2026-03-19T19:30:32.123456",
  "atualizado_em": "2026-03-19T19:32:45.123456",
  "iniciado_em": "2026-03-19T19:30:33.123456",
  "finalizado_em": "2026-03-19T19:32:45.123456",
  "worker_id": "worker-41394",
  "total": 12,
  "concluidas": 12,
  "sucesso": 9,
  "falha": 3,
  "parecer": {
    "resumo": "9 de 12 certidoes emitidas com sucesso",
    "situacao": "regular_com_ressalvas",
    "detalhes": ["TCU: nada consta", "MPF: certidao negativa", ...]
  },
  "certidoes": {
    "stj-pf": {
      "nome": "STJ Pessoa Fisica",
      "status": "sucesso" | "erro" | "falha" | "pendente" | "executando" | "na_fila",
      "inicio": "2026-03-19T19:30:33.123456",
      "fim": "2026-03-19T19:30:54.123456",
      "resultado": {
        "status": "sucesso",
        "link": "http://tmpfiles.org/29700865/cert.pdf",
        "link_local": "/api/v1/download/b1be383d/stj-pf",
        "arquivo": "downloads/b1be383d/stj-pf.pdf",
        ...campos extras do extrator...
      }
    },
    "tcu": { ... },
    "mpf": { ... },
    ...
  }
}
```

### Cache de Certidoes
```
Key:    pedro:cache:{cpf|cnpj}:{documento}:{cert_id}
Type:   STRING (JSON)
TTL:    24 horas (configuravel)

Exemplo:
  pedro:cache:cpf:27290000625:tcu -> { resultado da certidao TCU }
  pedro:cache:cnpj:26546054000140:mpf -> { resultado da certidao MPF }

Quando um job pede uma certidao que ja esta em cache:
  - Worker pula a execucao
  - Usa o resultado do cache
  - Marca como "cache" no status
```

### Workers Ativos
```
Key:    pedro:workers:active
Type:   SET
Valor:  worker_id (string)
```

---

## Fluxo do Cliente

### 1. Criar Job (direto no Redis)

```python
import redis, json, uuid

r = redis.from_url("redis://default:...@redis-host:port")

# Montar job
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
    "criado_em": "2026-03-19T20:00:00",
    "atualizado_em": "2026-03-19T20:00:00",
    "total": 0,       # worker preenche
    "concluidas": 0,
    "sucesso": 0,
    "falha": 0,
    "certidoes": {}    # worker preenche
}

# Salvar e publicar
r.setex(f"pedro:job:{job_id}", 86400*3, json.dumps(job))
r.lpush("pedro:queue:jobs", job_id)

print(f"Job criado: {job_id}")
```

### 2. Consultar Status (polling)

```python
import time

while True:
    raw = r.get(f"pedro:job:{job_id}")
    if not raw:
        print("Job nao encontrado")
        break

    job = json.loads(raw)
    print(f"Status: {job['status']} | {job['concluidas']}/{job['total']}")

    if job["status"] == "concluido":
        # Iterar resultados
        for cert_id, cert in job["certidoes"].items():
            s = cert["status"]
            link = cert.get("resultado", {}).get("link", "") if cert.get("resultado") else ""
            print(f"  {cert_id}: {s} {link}")
        break

    time.sleep(10)  # poll a cada 10s
```

### 3. Ou via API HTTP

```bash
# Criar job
curl -X POST http://localhost:8000/api/v1/job \
  -H "Content-Type: application/json" \
  -d '{"cpf": "27290000625", "nome": "JAIME", "nm_mae": "MARIA", "dt_nascimento": "01/01/1990"}'

# Consultar
curl http://localhost:8000/api/v1/job/{job_id}

# Baixar PDF
curl http://localhost:8000/api/v1/download/{job_id}/{cert_id} -o certidao.pdf

# Fila
curl http://localhost:8000/api/v1/queue
```

---

## Certidoes Disponiveis

### Para CPF (ate 12)
| ID | Nome | Dados extras |
|----|------|-------------|
| stj-pf | STJ Pessoa Fisica | - |
| tcu | TCU Nada Consta | - |
| mpf | MPF Certidao Negativa | - |
| trt18 | TRT18 Goias | - |
| ibama | IBAMA Negativa | - |
| tst-cndt | TST CNDT | - |
| mpgo | MPGO | - |
| tjgo-processos | TJGO Processos | - |
| receita-pf | Receita Federal PF | dt_nascimento |
| tjgo-civil | TJGO Civel | nome, nm_mae, dt_nascimento |
| tjgo-criminal | TJGO Criminal | nome, nm_mae, dt_nascimento |
| trf1-cpf | TRF1 Criminal+Civil | - |

### Para CNPJ (ate 10)
| ID | Nome |
|----|------|
| receita-pj | Receita Federal PJ |
| stj-pj | STJ Pessoa Juridica |
| tcu | TCU Nada Consta |
| mpf | MPF Certidao Negativa |
| trt18 | TRT18 Goias |
| ibama | IBAMA Negativa |
| tst-cndt | TST CNDT |
| mpgo | MPGO |
| tjgo-processos | TJGO Processos |
| trf1-cnpj | TRF1 Criminal |

---

## Status possiveis

### Job
- `na_fila` — publicado, aguardando worker
- `processando` — worker executando certidoes
- `concluido` — todas as certidoes terminaram (sucesso ou falha)

### Certidao dentro do job
- `pendente` — ainda nao iniciou
- `na_fila` — aguardando slot no semaforo (max Chrome simultaneos)
- `executando` — Chrome/solver rodando
- `sucesso` — certidao emitida
- `erro` — falha na execucao
- `falha` — extrator retornou sem resultado
- `cache` — resultado veio do cache (nao executou)
