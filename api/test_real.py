#!/usr/bin/env python3
"""
Teste REAL de todos os endpoints da API de Certidoes.
Dados reais de Goias para teste.

Uso:
    python3 api/test_real.py                    # testar todos
    python3 api/test_real.py tcu mpf stf        # testar apenas esses
"""
import sys
import time
import json
import requests

API = "http://localhost:8000"

# ═══════════════════════════════════════════════════════════
# DADOS REAIS DE TESTE - GOIAS
# ═══════════════════════════════════════════════════════════
# Pessoa 1: JAIME FERREIRA DE OLIVEIRA NETO - CPF 27290000625
# Pessoa 2: KARYNE ITABAIANA DE OLIVEIRA - CPF 02397147173
# Pessoa 3: ROSANA NAVES ITABAINA DE OLIVEIRA - CPF 34761896191
# CNPJ de teste: 26546054000140

CPF_JAIME = "27290000625"
NOME_JAIME = "JAIME FERREIRA DE OLIVEIRA NETO"
MAE_JAIME = "JORGETA TAHAN OLIVEIRA"
NASC_JAIME = "21/11/1958"

CPF_KARYNE = "02397147173"
NOME_KARYNE = "KARYNE ITABAIANA DE OLIVEIRA"
MAE_KARYNE = "ROSANA NAVES ITABAIANA"
NASC_KARYNE = "08/03/1989"

CNPJ_TESTE = "26546054000140"

TESTES = [
    # ─── Scripts 1-9 (Selenium) ────────────────────────────
    {
        "id": "receita-pj",
        "nome": "Receita Federal PJ",
        "body": {"cnpj": CNPJ_TESTE},
        "timeout": 60,
    },
    {
        "id": "receita-pf",
        "nome": "Receita Federal PF",
        "body": {"cpf": CPF_JAIME, "dt_nascimento": NASC_JAIME},
        "timeout": 60,
    },
    {
        "id": "stj-pf",
        "nome": "STJ Pessoa Fisica",
        "body": {"cpf": CPF_JAIME},
        "timeout": 60,
    },
    {
        "id": "stj-pj",
        "nome": "STJ Pessoa Juridica",
        "body": {"cnpj": CNPJ_TESTE},
        "timeout": 60,
    },
    {
        "id": "tjgo-civil",
        "nome": "TJGO Civel PF",
        "body": {"nome": NOME_KARYNE, "cpf": CPF_KARYNE, "nm_mae": MAE_KARYNE, "dt_nascimento": NASC_KARYNE},
        "timeout": 60,
    },
    {
        "id": "tjgo-processos",
        "nome": "TJGO Processos PJ",
        "body": {"cpf_cnpj": CNPJ_TESTE},
        "timeout": 60,
    },
    {
        "id": "tjgo-criminal",
        "nome": "TJGO Criminal PF",
        "body": {"nome": NOME_KARYNE, "cpf": CPF_KARYNE, "nm_mae": MAE_KARYNE, "dt_nascimento": NASC_KARYNE},
        "timeout": 60,
    },
    {
        "id": "trf1",
        "nome": "TRF1 Criminal CNPJ",
        "body": {"tp_certidao": "criminal", "tipo_cpf_cnpj": "cnpj", "cpf_cnpj": CNPJ_TESTE},
        "timeout": 60,
    },
    {
        "id": "trt18",
        "nome": "TRT18 Goias",
        "body": {"cpf_cnpj": CPF_JAIME, "tipo": "andamento"},
        "timeout": 60,
    },

    # ─── Scripts 11-18 (Puppeteer + solvers) ───────────────
    {
        "id": "tcu",
        "nome": "TCU Nada Consta",
        "body": {"cpf": CPF_JAIME},
        "timeout": 90,
    },
    {
        "id": "mpf",
        "nome": "MPF Turnstile",
        "body": {"cpf": CPF_JAIME},
        "timeout": 90,
    },
    {
        "id": "ibama",
        "nome": "IBAMA Negativa",
        "body": {"cpf": CPF_JAIME},
        "timeout": 90,
    },
    {
        "id": "tst-cndt",
        "nome": "TST CNDT",
        "body": {"cpf": CPF_JAIME},
        "timeout": 90,
    },
    {
        "id": "mpgo",
        "nome": "MPGO",
        "body": {"cpf": CPF_JAIME},
        "timeout": 90,
    },
    # ─── Esses sao mais lentos (solvers pesados) ───────────
    {
        "id": "cpf-receita",
        "nome": "CPF Receita (hCaptcha)",
        "body": {"cpf": CPF_JAIME, "data_nascimento": NASC_JAIME},
        "timeout": 120,
    },
    {
        "id": "stf",
        "nome": "STF Distribuicao",
        "body": {"cpf": CPF_JAIME, "tipo": "distribuicao"},
        "timeout": 150,
    },
]

# Protesto pulado (requer login/senha real)
SKIP = {"protesto"}


def test_endpoint(test: dict) -> dict:
    tid = test["id"]
    url = f"{API}/api/v1/certidao/{tid}"
    timeout = test["timeout"]

    start = time.time()
    try:
        r = requests.post(url, json=test["body"], timeout=timeout)
        elapsed = time.time() - start
        data = r.json()
        return {
            "id": tid,
            "nome": test["nome"],
            "http_status": r.status_code,
            "status": data.get("status", "?"),
            "link": data.get("link"),
            "tempo": f"{elapsed:.1f}s",
            "detalhes": {k: v for k, v in data.items()
                         if k not in ("status", "link", "resultado") and v},
            "erro": data.get("mensagem") if data.get("status") == "erro" else None,
        }
    except requests.Timeout:
        elapsed = time.time() - start
        return {"id": tid, "nome": test["nome"], "http_status": 0, "status": "timeout", "tempo": f"{elapsed:.0f}s"}
    except Exception as e:
        elapsed = time.time() - start
        return {"id": tid, "nome": test["nome"], "http_status": 0, "status": "excecao", "tempo": f"{elapsed:.0f}s", "erro": str(e)}


def main():
    filtro = set(sys.argv[1:]) if len(sys.argv) > 1 else None

    # Health check
    try:
        r = requests.get(f"{API}/health", timeout=5)
        assert r.json()["status"] == "ok"
    except Exception:
        print("ERRO: API nao esta rodando em localhost:8000")
        sys.exit(1)

    testes_para_rodar = []
    for t in TESTES:
        if t["id"] in SKIP:
            continue
        if filtro and t["id"] not in filtro:
            continue
        testes_para_rodar.append(t)

    print("=" * 70)
    print(f"  TESTE REAL - {len(testes_para_rodar)} ENDPOINTS")
    print(f"  Dados: JAIME (CPF {CPF_JAIME}) + KARYNE (CPF {CPF_KARYNE})")
    print(f"  CNPJ: {CNPJ_TESTE}")
    print("=" * 70)
    print()

    resultados = []
    for i, t in enumerate(testes_para_rodar, 1):
        print(f"[{i}/{len(testes_para_rodar)}] {t['nome']:30s} ({t['id']})")
        print(f"     Body: {json.dumps(t['body'])}")
        sys.stdout.flush()

        result = test_endpoint(t)
        resultados.append(result)

        icon = "OK" if result["status"] == "sucesso" else "FALHA"
        link_str = "SIM" if result.get("link") else "NAO"
        print(f"     -> {icon} | HTTP {result['http_status']} | {result.get('tempo', '?')} | link={link_str}")
        if result.get("erro"):
            print(f"     -> Erro: {str(result['erro'])[:150]}")
        if result.get("detalhes"):
            for k, v in result["detalhes"].items():
                if k not in ("mensagem",):
                    print(f"     -> {k}: {str(v)[:80]}")
        print()

    # Resumo
    print("=" * 70)
    print("  RESUMO FINAL")
    print("=" * 70)
    print()
    print(f"  {'#':3s} {'Endpoint':20s} {'Status':8s} {'HTTP':5s} {'Tempo':8s} {'Link':5s}")
    print(f"  {'---':3s} {'--------------------':20s} {'--------':8s} {'-----':5s} {'--------':8s} {'-----':5s}")

    ok = fail = 0
    for i, r in enumerate(resultados, 1):
        s = r["status"]
        link = "SIM" if r.get("link") else "NAO"
        icon = "OK" if s == "sucesso" else "FAIL"
        if s == "sucesso":
            ok += 1
        else:
            fail += 1
        print(f"  {i:<3d} {r['id']:20s} {icon:8s} {r['http_status']:<5d} {r.get('tempo','?'):8s} {link:5s}")

    print()
    print(f"  RESULTADO: {ok} sucesso / {fail} falha / {len(resultados)} total")
    print("=" * 70)

    with open("api/test_real_results.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)
    print(f"  Salvo em: api/test_real_results.json")

    return fail


if __name__ == "__main__":
    sys.exit(main())
