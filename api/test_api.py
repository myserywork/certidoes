#!/usr/bin/env python3
"""
Teste completo da API de Certidoes - COM DADOS REAIS.

Verifica:
  1. Estrutura e status da API
  2. Validacao de campos (rejeita body errado)
  3. Mock com dados reais (formato de resposta)
  4. Catalogo completo e consistente

Dados reais extraidos dos scripts .txt e test files do projeto.
NAO executa extratores reais (nao precisa de Chrome/Linux).
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.main import app, CERTIDOES_INFO
from fastapi.testclient import TestClient

client = TestClient(app, raise_server_exceptions=False)

PASS = 0
FAIL = 0


# ═══════════════════════════════════════════════════════════
# DADOS REAIS DE TESTE (extraidos dos .txt e test files)
# ═══════════════════════════════════════════════════════════

DADOS_REAIS = {
    "receita-pj": {
        "body": {"cnpj": "26546054000140"},
        "mock_retorno": {"link": "http://tmpfiles.org/999/cert_receita_pj.pdf", "tipo": "Negativa"},
    },
    "receita-pf": {
        "body": {"cpf": "99999999999", "dt_nascimento": "01/01/1900"},
        "mock_retorno": {"link": "http://tmpfiles.org/999/cert_receita_pf.pdf", "tipo": "Negativa"},
    },
    "protesto": {
        "body": {"cpf_cnpj": "72467355187", "usuario_login": "72467355187", "usuario_senha": "@Protesto.25"},
        "mock_retorno": {"link": "http://tmpfiles.org/999/protesto.pdf", "status": "Nao constam protestos nos cartorios participantes do Brasil"},
    },
    "stj-pf": {
        "body": {"cpf": "13683315725"},
        "mock_retorno": {"link": "http://tmpfiles.org/999/stj_pf.pdf"},
    },
    "stj-pj": {
        "body": {"cnpj": "26546054000140"},
        "mock_retorno": {"link": "http://tmpfiles.org/999/stj_pj.pdf"},
    },
    "tjgo-civil": {
        "body": {"nome": "THAINA SANTOS GONCALVES", "cpf": "13683315725", "nm_mae": "MARIA SANTOS", "dt_nascimento": "01/01/1990"},
        "mock_retorno": {"link": "http://tmpfiles.org/999/tjgo_civil.pdf"},
    },
    "tjgo-processos": {
        "body": {"cpf_cnpj": "04144748000119"},
        "mock_retorno": {"link": "http://tmpfiles.org/999/tjgo_proc.pdf"},
    },
    "tjgo-criminal": {
        "body": {"nome": "THAINA SANTOS GONCALVES", "cpf": "13683315725", "nm_mae": "MARIA SANTOS", "dt_nascimento": "01/01/1990"},
        "mock_retorno": {"link": "http://tmpfiles.org/999/tjgo_crim.pdf"},
    },
    "trf1": {
        "body": {"tp_certidao": "criminal", "tipo_cpf_cnpj": "cnpj", "cpf_cnpj": "26546054000140"},
        "mock_retorno": {"link": "http://tmpfiles.org/999/trf1.pdf"},
    },
    "tcu": {
        "body": {"cpf": "13683315725"},
        "mock_retorno": {
            "status": "sucesso",
            "tipo_certidao": "nada_consta",
            "nome": "THAINA SANTOS GONCALVES",
            "cpf_cnpj": "13683315725",
            "codigo_controle": "TCU-2026-001",
            "link": "http://tmpfiles.org/999/tcu.pdf",
        },
    },
    "cpf-receita": {
        "body": {"cpf": "13683315725", "data_nascimento": "01/01/1990"},
        "mock_retorno": {
            "status": "sucesso",
            "cpf": "136.833.157-25",
            "nome": "THAINA SANTOS GONCALVES",
            "situacao_cadastral": "REGULAR",
            "data_inscricao": "anterior a 01/11/1990",
            "link": "http://tmpfiles.org/999/cpf_receita.html",
        },
    },
    "mpf": {
        "body": {"cpf": "13683315725"},
        "mock_retorno": {
            "status": "sucesso",
            "metodo": "stealth_local",
            "nome": "THAINA SANTOS GONCALVES",
            "cpf_cnpj": "13683315725",
            "tipo_pessoa": "F",
            "hash": "9df5aafac3e8b4df67014f8523796d1e",
            "link": "http://tmpfiles.org/999/mpf.pdf",
            "download_url_direto": "https://aplicativos.mpf.mp.br/ouvidoria/rest/v1/publico/certidao/download/9df5aafac3e8b4df67014f8523796d1e",
            "mensagem": "Certidao emitida com sucesso",
        },
    },
    "stf": {
        "body": {"cpf": "13683315725", "tipo": "distribuicao"},
        "mock_retorno": {
            "status": "sucesso",
            "cpf_cnpj": "13683315725",
            "tipo_certidao": "distribuicao",
            "metodo": "local_audio_whisper",
            "gerada_online": True,
            "nome": "THAINA SANTOS GONCALVES",
            "link": "http://tmpfiles.org/999/stf.pdf",
            "pdf_size": 45320,
        },
    },
    "trt18": {
        "body": {"cpf_cnpj": "13683315725", "tipo": "andamento"},
        "mock_retorno": {"link": "http://tmpfiles.org/999/trt18.pdf", "status": "nada_consta", "tipo": "andamento"},
    },
    "ibama": {
        "body": {"cnpj": "00000000000191"},
        "mock_retorno": {
            "status": "sucesso",
            "tipo_certidao": "nada_consta",
            "cpf_cnpj": "00.000.000/0001-91",
            "link": "http://tmpfiles.org/999/ibama.pdf",
        },
    },
    "tst-cndt": {
        "body": {"cnpj": "33000167000101"},
        "mock_retorno": {
            "status": "sucesso",
            "tipo_certidao": "nada_consta",
            "nome": "BANCO DO BRASIL SA",
            "cpf_cnpj": "33000167000101",
            "numero_certidao": "20260319-0001",
            "data_emissao": "19/03/2026",
            "validade": "19/09/2026",
            "link": "http://tmpfiles.org/999/cndt.pdf",
            "metodo": "local_audio_whisper",
        },
    },
    "mpgo": {
        "body": {"cnpj": "33000167000101"},
        "mock_retorno": {
            "status": "sucesso",
            "tipo_certidao": "certidao_mpgo",
            "cpf_cnpj": "33000167000101",
            "link": "http://tmpfiles.org/999/mpgo.pdf",
            "pdf_size": 85528,
            "metodo": "local_audio_whisper",
        },
    },
}


def check(label: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK] {label}")
    else:
        FAIL += 1
        print(f"  [FALHA] {label} -- {detail}")


def main():
    global PASS, FAIL

    print("=" * 65)
    print("  TESTE COMPLETO - API DE CERTIDOES (dados reais mockados)")
    print("=" * 65)

    # ─── 1. Status endpoints ──────────────────────────────
    print("\n[1] ENDPOINTS DE STATUS\n")

    r = client.get("/")
    check("GET / -> 200", r.status_code == 200)

    r = client.get("/health")
    check("GET /health -> ok", r.json().get("status") == "ok")

    r = client.get("/api/v1/certidoes")
    data = r.json()
    check(f"GET /certidoes -> {data['total']} tipos", data["total"] == len(CERTIDOES_INFO))

    # Verificar que cada certidao tem exemplo com dados reais
    for info in data["certidoes"]:
        check(
            f"  {info['id']:20s} tem exemplo",
            bool(info.get("exemplo")),
        )

    # ─── 2. Validacao: body vazio -> 422 ──────────────────
    print("\n[2] VALIDACAO - Body vazio -> 422\n")

    for info in CERTIDOES_INFO:
        ep = info["endpoint"]
        r = client.post(ep, json={})
        check(f"  {info['id']:20s} vazio -> 422", r.status_code == 422, f"got {r.status_code}")

    # ─── 3. Validacao: campos errados -> 422 ──────────────
    print("\n[3] VALIDACAO - Campos errados -> 422\n")

    erros_tests = [
        ("receita-pj", {"cpf": "123"}, "cpf em vez de cnpj"),
        ("receita-pf", {"cpf": "123"}, "sem dt_nascimento"),
        ("protesto", {"cpf_cnpj": "123"}, "sem login/senha"),
        ("trf1", {"cpf_cnpj": "123"}, "sem tp_certidao"),
        ("cpf-receita", {"cpf": "123"}, "sem data_nascimento"),
        ("tjgo-civil", {"cpf": "123"}, "sem nome/mae/nascimento"),
        ("tcu", {}, "sem cpf nem cnpj"),
        ("mpf", {}, "sem cpf nem cnpj"),
        ("stf", {}, "sem cpf nem cnpj"),
        ("ibama", {}, "sem cpf nem cnpj"),
        ("tst-cndt", {}, "sem cpf nem cnpj"),
        ("mpgo", {}, "sem cpf nem cnpj"),
    ]
    for ep_id, body, desc in erros_tests:
        r = client.post(f"/api/v1/certidao/{ep_id}", json=body)
        check(f"  {ep_id:20s} {desc} -> 422", r.status_code == 422, f"got {r.status_code}")

    # ─── 4. Mock com dados reais -> 200 + formato correto ─
    print("\n[4] MOCK COM DADOS REAIS - Verifica formato de resposta\n")

    for cid, test_data in DADOS_REAIS.items():
        ep = f"/api/v1/certidao/{cid}"
        body = test_data["body"]
        mock_ret = test_data["mock_retorno"]

        # Scripts 1-9 e TRT18 usam _run_navegador
        scripts_navegador = {"receita-pj", "receita-pf", "protesto", "stj-pf", "stj-pj",
                             "tjgo-civil", "tjgo-processos", "tjgo-criminal", "trf1", "trt18"}

        if cid in scripts_navegador:
            # Garantir que mock_retorno tem status
            if "status" not in mock_ret:
                mock_ret_full = {"status": "sucesso", **mock_ret}
            else:
                mock_ret_full = mock_ret
            with patch("api.main._run_navegador", return_value=mock_ret_full):
                r = client.post(ep, json=body)
        else:
            # Scripts 11-18: mock _import_script
            mock_mod = MagicMock()
            # Descobrir qual funcao cada script usa
            func_map = {
                "tcu": "emitir_certidao_tcu",
                "cpf-receita": "consultar_cpf",
                "mpf": "emitir_certidao_mpf",
                "stf": "emitir_certidao_stf",
                "ibama": "emitir_certidao_ibama",
                "tst-cndt": "emitir_cndt",
                "mpgo": "emitir_certidao_mpgo",
            }
            func_name = func_map[cid]
            getattr(mock_mod, func_name).return_value = mock_ret
            with patch("api.main._import_script", return_value=mock_mod):
                r = client.post(ep, json=body)

        resp = r.json()

        check(f"  {cid:20s} -> 200", r.status_code == 200, f"got {r.status_code}: {resp}")
        check(f"  {cid:20s} -> status=sucesso", resp.get("status") == "sucesso", f"status={resp.get('status')}")
        check(f"  {cid:20s} -> tem link", resp.get("link") is not None, f"link={resp.get('link')}")

        # Verificar campos especificos por tipo
        if cid == "tcu":
            check(f"  {cid:20s} -> tem tipo_certidao", resp.get("tipo_certidao") is not None)
            check(f"  {cid:20s} -> tem nome", resp.get("nome") is not None)
        elif cid == "cpf-receita":
            check(f"  {cid:20s} -> tem situacao_cadastral", resp.get("situacao_cadastral") is not None)
            check(f"  {cid:20s} -> tem nome", resp.get("nome") is not None)
        elif cid == "mpf":
            check(f"  {cid:20s} -> tem nome", resp.get("nome") is not None)
            check(f"  {cid:20s} -> tem hash", resp.get("hash") is not None)
            check(f"  {cid:20s} -> tem metodo", resp.get("metodo") is not None)
        elif cid == "stf":
            check(f"  {cid:20s} -> tem tipo_certidao", resp.get("tipo_certidao") is not None)
            check(f"  {cid:20s} -> tem metodo", resp.get("metodo") is not None)
        elif cid == "tst-cndt":
            check(f"  {cid:20s} -> tem numero_certidao", resp.get("numero_certidao") is not None)
            check(f"  {cid:20s} -> tem validade", resp.get("validade") is not None)
        elif cid == "mpgo":
            check(f"  {cid:20s} -> tem pdf_size", resp.get("pdf_size") is not None)
        elif cid == "ibama":
            check(f"  {cid:20s} -> tem tipo_certidao", resp.get("tipo_certidao") is not None)
        elif cid == "protesto":
            check(f"  {cid:20s} -> tem status texto", "status" in resp)

    # ─── 5. Teste de erro padronizado ─────────────────────
    print("\n[5] FORMATO DE ERRO PADRAO\n")

    err = {"status": "erro", "mensagem": "Falha ao resolver reCAPTCHA (audio+Whisper)"}
    with patch("api.main._run_navegador", return_value=err):
        r = client.post("/api/v1/certidao/receita-pj", json={"cnpj": "26546054000140"})
        resp = r.json()
        check("Erro -> 500", r.status_code == 500)
        check("Erro -> status=erro", resp.get("status") == "erro")
        check("Erro -> tem mensagem", bool(resp.get("mensagem")))

    mock_mod = MagicMock()
    mock_mod.emitir_certidao_tcu.return_value = {"status": "erro", "mensagem": "ViewState nao encontrado"}
    with patch("api.main._import_script", return_value=mock_mod):
        r = client.post("/api/v1/certidao/tcu", json={"cpf": "13683315725"})
        resp = r.json()
        check("Erro TCU -> 500", r.status_code == 500)
        check("Erro TCU -> tem mensagem", bool(resp.get("mensagem")))

    # ─── 6. Dados do catalogo batem com DADOS_REAIS ───────
    print("\n[6] CATALOGO - Exemplos correspondem aos dados reais\n")

    for info in CERTIDOES_INFO:
        cid = info["id"]
        if cid in DADOS_REAIS:
            catalogo_exemplo = info.get("exemplo", {})
            test_body = DADOS_REAIS[cid]["body"]
            # Verificar que os campos do exemplo batem
            campos_ok = all(k in catalogo_exemplo for k in test_body)
            check(f"  {cid:20s} catalogo tem todos os campos", campos_ok,
                  f"catalogo={list(catalogo_exemplo.keys())} test={list(test_body.keys())}")

    # ─── Resumo ───────────────────────────────────────────
    print("\n" + "=" * 65)
    total = PASS + FAIL
    print(f"  RESULTADO: {PASS} passou / {FAIL} falhou / {total} total")
    if FAIL == 0:
        print("  TODOS OS TESTES PASSARAM!")
    else:
        print(f"  {FAIL} TESTE(S) FALHARAM")
    print("=" * 65)

    return FAIL


if __name__ == "__main__":
    sys.exit(main())
