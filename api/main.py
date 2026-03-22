#!/usr/bin/env python3
"""
API Unificada de Certidoes - PEDRO PROJECT
Porta unica: 8000
Swagger UI: http://localhost:8000/docs

Todos os 17 extratores acessiveis via endpoints REST.
"""
import sys
import asyncio
import traceback
import importlib.util
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

# ─── Path do projeto ──────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from api.config import MAX_WORKERS, API_PORT
from api.models import (
    ReceitaPJRequest, ReceitaPFRequest, ProtestoRequest,
    STJPFRequest, STJPJRequest, TJGOPessoaFisicaRequest,
    TJGOProcessosRequest, TRF1Request,
    TCURequest, CPFReceitaRequest, MPFRequest, STFRequest,
    TRT18Request, IBAMARequest, TSTCNDTRequest, MPGORequest,
    CertidaoResponse,
)


# ─── Importador de scripts com nomes hifenizados ──────────

_script_cache = {}


def _import_script(filename: str):
    """
    Importa script pelo nome do arquivo (ex: '11-certidao_TCU').
    Nomes com hifen nao sao modulos Python validos, entao usamos importlib.util.
    Cache em dict proprio (nao sys.modules) para evitar conflitos.
    """
    if filename in _script_cache:
        return _script_cache[filename]

    filepath = PROJECT_ROOT / f"{filename}.py"
    if not filepath.exists():
        raise FileNotFoundError(f"Script nao encontrado: {filepath}")

    module_name = f"_certidao_{filename.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, str(filepath))
    mod = importlib.util.module_from_spec(spec)
    mod.__name__ = module_name
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    _script_cache[filename] = mod
    return mod


# ─── Thread pool e lifecycle ──────────────────────────────

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    executor.shutdown(wait=False)


# ─── App FastAPI ──────────────────────────────────────────

app = FastAPI(
    title="API de Certidoes - PEDRO PROJECT",
    description=(
        "API unificada para emissao automatizada de certidoes "
        "de 17 sites governamentais brasileiros.\n\n"
        "**Scripts 1-9:** Receita Federal, STJ, TJGO, TRF1 (Selenium)\n\n"
        "**Scripts 11-18:** TCU, CPF Receita, MPF, STF, TRT18, IBAMA, TST CNDT, MPGO "
        "(Puppeteer stealth + CAPTCHA local)"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


from api.logger import get_logger
from api.dashboard import router as dashboard_router
app.include_router(dashboard_router)

_api_log = get_logger("api")


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    _api_log.error(f"{request.method} {request.url.path} -> ERRO: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"status": "erro", "mensagem": str(exc)},
    )


# ─── Helpers ──────────────────────────────────────────────

async def run_in_thread(func, *args, **kwargs):
    """Executa funcao bloqueante em thread separada."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, lambda: func(*args, **kwargs))


def _sanitize_result(result: dict) -> dict:
    """Remove campos pesados da resposta (ex: HTML bruto)."""
    if not isinstance(result, dict):
        return {"status": "erro", "mensagem": "Retorno inesperado do extrator"}
    cleaned = {}
    for k, v in result.items():
        # Pula HTML bruto (campo 'resultado' com >500 chars)
        if k == "resultado" and isinstance(v, str) and len(v) > 500:
            continue
        # Pula caminhos locais do servidor
        if k == "pdf_local":
            continue
        cleaned[k] = v
    return cleaned


def _require_cpf_or_cnpj(cpf: str | None, cnpj: str | None) -> str:
    """Retorna CPF ou CNPJ, ou levanta 422."""
    v = cpf or cnpj
    if not v:
        raise HTTPException(status_code=422, detail="Informe cpf ou cnpj")
    return v


def _make_response(result: dict) -> JSONResponse:
    """Cria JSONResponse com status_code baseado no resultado."""
    result = _sanitize_result(result)
    status = result.get("status", "")

    # Scripts 1-9 podem retornar status com texto descritivo
    # (ex: "Nao constam protestos", "nada_consta")
    # Se tem link e status nao eh "erro"/"falha", considerar sucesso
    if status not in ("sucesso", "sucesso_sem_pdf", "parcial", "erro", "falha"):
        if result.get("link"):
            result["resultado"] = status
            result["status"] = "sucesso"
            status = "sucesso"

    if status in ("sucesso", "sucesso_sem_pdf", "parcial"):
        return JSONResponse(content=result, status_code=200)
    return JSONResponse(content=result, status_code=500)


# ─── Wrapper generico para scripts Selenium (1-9) ────────

def _run_navegador(script_name: str, args: tuple) -> dict:
    """
    Instancia Navegador do script, chama emitir_certidao(*args), fecha.
    Preserva TODOS os campos do retorno original.
    """
    mod = _import_script(script_name)
    bot = mod.Navegador(headless=False)
    try:
        resultado = bot.emitir_certidao(*args)
        bot.fechar()

        if not resultado:
            return {"status": "falha", "mensagem": "Certidao nao disponivel"}

        # Montar resposta mantendo todos os campos originais
        if isinstance(resultado, dict):
            resp = dict(resultado)
            # O campo "status" nos scripts 1-9 eh texto descritivo (ex: "Nao constam protestos")
            # Precisamos separar: "resultado" = texto original, "status" = sucesso/falha
            if "status" in resp and resp["status"] not in ("sucesso", "erro", "falha", "parcial"):
                resp["resultado"] = resp["status"]
                resp["status"] = "sucesso" if resp.get("link") else "falha"
            elif "status" not in resp:
                resp["status"] = "sucesso" if resp.get("link") else "falha"
            if not resp.get("link"):
                resp["status"] = "falha"
                resp.setdefault("mensagem", "PDF nao gerado")
        else:
            resp = {"status": "sucesso", "link": resultado}
        return resp
    except Exception as e:
        try:
            bot.fechar()
        except Exception:
            pass
        return {"status": "erro", "mensagem": str(e)}


# ═══════════════════════════════════════════════════════════
# ENDPOINTS - SCRIPTS 1-9 (Pedro / Selenium)
# ═══════════════════════════════════════════════════════════

# ─── 1. Receita Federal PJ ────────────────────────────────
@app.post(
    "/api/v1/certidao/receita-pj",
    response_model=CertidaoResponse,
    tags=["Receita Federal"],
    summary="Certidao Receita Federal PJ (CNPJ)",
    description="Emite certidao da Receita Federal para Pessoa Juridica.\n\n"
                "**Entrada:** CNPJ\n\n"
                "**Retorno:** link do PDF + tipo (Positiva/Negativa/etc)",
)
async def certidao_receita_pj(req: ReceitaPJRequest):
    result = await run_in_thread(_run_navegador, "1-certidao_receita_pj", (req.cnpj,))
    return _make_response(result)


# ─── 2. Receita Federal PF ────────────────────────────────
@app.post(
    "/api/v1/certidao/receita-pf",
    response_model=CertidaoResponse,
    tags=["Receita Federal"],
    summary="Certidao Receita Federal PF (CPF + Nascimento)",
    description="Emite certidao da Receita Federal para Pessoa Fisica.\n\n"
                "**Entrada:** CPF + data de nascimento\n\n"
                "**Retorno:** link do PDF + tipo",
)
async def certidao_receita_pf(req: ReceitaPFRequest):
    result = await run_in_thread(_run_navegador, "2-certidao_receita_pf", (req.cpf, req.dt_nascimento))
    return _make_response(result)


# ─── 3. Consulta Protesto ─────────────────────────────────
@app.post(
    "/api/v1/certidao/protesto",
    response_model=CertidaoResponse,
    tags=["Protesto"],
    summary="Consulta Protesto (requer login)",
    description="Consulta protestos em cartorios do Brasil.\n\n"
                "**Entrada:** CPF/CNPJ + login + senha do site pesquisaprotesto.com.br\n\n"
                "**Retorno:** link PDF + status (consta/nao consta protestos)",
)
async def certidao_protesto(req: ProtestoRequest):
    result = await run_in_thread(
        _run_navegador, "3-certidao_consulta_protesto",
        (req.cpf_cnpj, req.usuario_login, req.usuario_senha),
    )
    return _make_response(result)


# ─── 4. STJ Pessoa Fisica ─────────────────────────────────
@app.post(
    "/api/v1/certidao/stj-pf",
    response_model=CertidaoResponse,
    tags=["STJ"],
    summary="Certidao STJ Pessoa Fisica (CPF)",
    description="Emite certidao do Superior Tribunal de Justica para PF.\n\n"
                "**Entrada:** CPF\n\n"
                "**Retorno:** link do PDF",
)
async def certidao_stj_pf(req: STJPFRequest):
    result = await run_in_thread(_run_navegador, "4-certidao_STJ_pf", (req.cpf,))
    return _make_response(result)


# ─── 5. STJ Pessoa Juridica ───────────────────────────────
@app.post(
    "/api/v1/certidao/stj-pj",
    response_model=CertidaoResponse,
    tags=["STJ"],
    summary="Certidao STJ Pessoa Juridica (CNPJ)",
    description="Emite certidao do Superior Tribunal de Justica para PJ.\n\n"
                "**Entrada:** CNPJ\n\n"
                "**Retorno:** link do PDF",
)
async def certidao_stj_pj(req: STJPJRequest):
    result = await run_in_thread(_run_navegador, "5-certidao_STJ_pj", (req.cnpj,))
    return _make_response(result)


# ─── 6. TJGO Civel PF ─────────────────────────────────────
@app.post(
    "/api/v1/certidao/tjgo-civil",
    response_model=CertidaoResponse,
    tags=["TJGO"],
    summary="Certidao Civel TJGO PF",
    description="Emite certidao civel do TJGO para Pessoa Fisica.\n\n"
                "**Entrada:** nome + CPF + nome da mae + nascimento\n\n"
                "**Retorno:** link do PDF",
)
async def certidao_tjgo_civil(req: TJGOPessoaFisicaRequest):
    result = await run_in_thread(
        _run_navegador, "6-certidao_civil_tjgo_pf",
        (req.nome, req.cpf, req.nm_mae, req.dt_nascimento),
    )
    return _make_response(result)


# ─── 7. TJGO Processos PJ ─────────────────────────────────
@app.post(
    "/api/v1/certidao/tjgo-processos",
    response_model=CertidaoResponse,
    tags=["TJGO"],
    summary="Consulta Processos TJGO (CPF ou CNPJ)",
    description="Consulta processos no TJGO para PF ou PJ.\n\n"
                "**Entrada:** CPF ou CNPJ\n\n"
                "**Retorno:** link do PDF com resultado da busca",
)
async def certidao_tjgo_processos(req: TJGOProcessosRequest):
    result = await run_in_thread(_run_navegador, "7-consulta_processos_tjgo_pj", (req.cpf_cnpj,))
    return _make_response(result)


# ─── 8. TJGO Criminal PF ──────────────────────────────────
@app.post(
    "/api/v1/certidao/tjgo-criminal",
    response_model=CertidaoResponse,
    tags=["TJGO"],
    summary="Certidao Criminal TJGO PF",
    description="Emite certidao criminal do TJGO para Pessoa Fisica.\n\n"
                "**Entrada:** nome + CPF + nome da mae + nascimento\n\n"
                "**Retorno:** link do PDF",
)
async def certidao_tjgo_criminal(req: TJGOPessoaFisicaRequest):
    result = await run_in_thread(
        _run_navegador, "8-certidao_criminal_tjgo_pf",
        (req.nome, req.cpf, req.nm_mae, req.dt_nascimento),
    )
    return _make_response(result)


# ─── 9. TRF1 ──────────────────────────────────────────────
@app.post(
    "/api/v1/certidao/trf1",
    response_model=CertidaoResponse,
    tags=["TRF1"],
    summary="Certidao TRF1 (Civil / Criminal / Eleitoral)",
    description="Emite certidao do TRF1 (1a Regiao).\n\n"
                "**Entrada:** tipo certidao + cpf/cnpj + numero\n\n"
                "**tp_certidao:** civil | criminal | eleitoral\n\n"
                "**tipo_cpf_cnpj:** cpf | cnpj",
)
async def certidao_trf1(req: TRF1Request):
    result = await run_in_thread(
        _run_navegador, "9-certidao_TRF1_todos",
        (req.tp_certidao, req.tipo_cpf_cnpj, req.cpf_cnpj),
    )
    return _make_response(result)


# ═══════════════════════════════════════════════════════════
# ENDPOINTS - SCRIPTS 11-18 (Puppeteer stealth + solvers)
# ═══════════════════════════════════════════════════════════

# ─── 11. TCU ──────────────────────────────────────────────
@app.post(
    "/api/v1/certidao/tcu",
    response_model=CertidaoResponse,
    tags=["TCU"],
    summary="Certidao TCU - Nada Consta (CPF ou CNPJ)",
    description="Emite certidao de Nada Consta do TCU.\n\n"
                "**CAPTCHA:** reCAPTCHA v2 audio → Whisper base\n\n"
                "**Retorno:** tipo_certidao (nada_consta/consta) + nome + codigo_controle + link PDF",
)
async def certidao_tcu(req: TCURequest):
    cpf_cnpj = _require_cpf_or_cnpj(req.cpf, req.cnpj)

    def _execute():
        mod = _import_script("11-certidao_TCU")
        return mod.emitir_certidao_tcu(cpf_cnpj)

    result = await run_in_thread(_execute)
    return _make_response(result)


# ─── 12. CPF Receita (Situacao Cadastral) ──────────────────
@app.post(
    "/api/v1/certidao/cpf-receita",
    response_model=CertidaoResponse,
    tags=["Receita Federal"],
    summary="Consulta Situacao Cadastral CPF (hCaptcha + CLIP)",
    description="Consulta situacao cadastral do CPF na Receita Federal.\n\n"
                "**CAPTCHA:** hCaptcha visual → CLIP\n\n"
                "**Retorno:** nome + situacao_cadastral (REGULAR/SUSPENSA/etc) + data_inscricao",
)
async def certidao_cpf_receita(req: CPFReceitaRequest):
    def _execute():
        mod = _import_script("12-certidao_CPF_Receita")
        return mod.consultar_cpf(req.cpf, req.data_nascimento)

    result = await run_in_thread(_execute)
    return _make_response(result)


# ─── 13. MPF ──────────────────────────────────────────────
@app.post(
    "/api/v1/certidao/mpf",
    response_model=CertidaoResponse,
    tags=["MPF"],
    summary="Certidao Negativa MPF (Turnstile stealth)",
    description="Emite certidao negativa do Ministerio Publico Federal.\n\n"
                "**CAPTCHA:** Cloudflare Turnstile auto-solve\n\n"
                "**Retorno:** nome + hash certidao + link PDF",
)
async def certidao_mpf(req: MPFRequest):
    cpf_cnpj = _require_cpf_or_cnpj(req.cpf, req.cnpj)
    tipo_pessoa = "F" if req.cpf else "J"

    def _execute():
        mod = _import_script("13-certidao_MPF")
        return mod.emitir_certidao_mpf(cpf_cnpj, tipo_pessoa)

    result = await run_in_thread(_execute)
    return _make_response(result)


# ─── 14. STF ──────────────────────────────────────────────
@app.post(
    "/api/v1/certidao/stf",
    response_model=CertidaoResponse,
    tags=["STF"],
    summary="Certidao STF (AWS WAF + reCAPTCHA Enterprise)",
    description="Emite certidao do Supremo Tribunal Federal.\n\n"
                "**CAPTCHA:** AWS WAF audio (Whisper medium) + reCAPTCHA Enterprise\n\n"
                "**tipo:** distribuicao | antecedentes-criminais | fins-eleitorais | "
                "atuacao-de-advogado | objeto-e-pe\n\n"
                "**Retorno:** tipo_certidao + link PDF + protocolo",
)
async def certidao_stf(req: STFRequest):
    cpf_cnpj = _require_cpf_or_cnpj(req.cpf, req.cnpj)

    # Montar dict extra com campos obrigatorios da nova API do STF
    extra = {}
    if req.nome_mae:
        extra["nomeDaMae"] = req.nome_mae
    if req.rg:
        extra["rg"] = req.rg
    if req.orgao_expedidor:
        extra["orgaoExpedidor"] = req.orgao_expedidor
    if req.estado_civil:
        extra["estadoCivil"] = req.estado_civil

    def _execute():
        mod = _import_script("14-certidao_STF")
        return mod.emitir_certidao_stf(cpf_cnpj, tipo=req.tipo, nome=req.nome, extra=extra or None)

    result = await run_in_thread(_execute)
    return _make_response(result)


# ─── 15. TRT18 ────────────────────────────────────────────
@app.post(
    "/api/v1/certidao/trt18",
    response_model=CertidaoResponse,
    tags=["TRT18"],
    summary="Certidao TRT18 Goias (sem CAPTCHA)",
    description="Emite certidao do TRT da 18a Regiao (Goias).\n\n"
                "**CAPTCHA:** Nenhum\n\n"
                "**tipo:** andamento | arquivadas | objeto_pe\n\n"
                "**Retorno:** link PDF + resultado (nada_consta/consta)",
)
async def certidao_trt18(req: TRT18Request):
    result = await run_in_thread(
        _run_navegador, "15-certidao_TRT18", (req.cpf_cnpj, req.tipo),
    )
    return _make_response(result)


# ─── 16. IBAMA ────────────────────────────────────────────
@app.post(
    "/api/v1/certidao/ibama",
    response_model=CertidaoResponse,
    tags=["IBAMA"],
    summary="Certidao Negativa de Debito IBAMA (reCAPTCHA Enterprise)",
    description="Emite certidao negativa de debito ambiental do IBAMA.\n\n"
                "**CAPTCHA:** reCAPTCHA Enterprise invisible\n\n"
                "**Retorno:** tipo_certidao (nada_consta/verificar) + link PDF/HTML",
)
async def certidao_ibama(req: IBAMARequest):
    cpf_cnpj = _require_cpf_or_cnpj(req.cpf, req.cnpj)

    def _execute():
        mod = _import_script("16-certidao_IBAMA")
        return mod.emitir_certidao_ibama(cpf_cnpj)

    result = await run_in_thread(_execute)
    return _make_response(result)


# ─── 17. TST CNDT ─────────────────────────────────────────
@app.post(
    "/api/v1/certidao/tst-cndt",
    response_model=CertidaoResponse,
    tags=["TST"],
    summary="CNDT - Certidao Negativa de Debitos Trabalhistas",
    description="Emite CNDT via TST.\n\n"
                "**CAPTCHA:** Audio custom PT-BR → Whisper medium + parser fonetico\n\n"
                "**Retorno:** tipo_certidao + nome + numero_certidao + validade + link",
)
async def certidao_tst_cndt(req: TSTCNDTRequest):
    cpf_cnpj = _require_cpf_or_cnpj(req.cpf, req.cnpj)

    def _execute():
        mod = _import_script("17-certidao_TST_CNDT")
        return mod.emitir_cndt(cpf_cnpj)

    result = await run_in_thread(_execute)
    return _make_response(result)


# ─── 18. MPGO ─────────────────────────────────────────────
@app.post(
    "/api/v1/certidao/mpgo",
    response_model=CertidaoResponse,
    tags=["MPGO"],
    summary="Certidao MPGO (reCAPTCHA v2 stealth)",
    description="Emite certidao do Ministerio Publico de Goias.\n\n"
                "**CAPTCHA:** reCAPTCHA v2 stealth auto-solve\n\n"
                "**Retorno:** link PDF + pdf_size",
)
async def certidao_mpgo(req: MPGORequest):
    cpf_cnpj = _require_cpf_or_cnpj(req.cpf, req.cnpj)

    def _execute():
        mod = _import_script("18-certidao_MPGO")
        return mod.emitir_certidao_mpgo(cpf_cnpj)

    result = await run_in_thread(_execute)
    return _make_response(result)


# ═══════════════════════════════════════════════════════════
# ENDPOINTS UTILITARIOS
# ═══════════════════════════════════════════════════════════

CERTIDOES_INFO = [
    {
        "id": "receita-pj",
        "nome": "Receita Federal PJ",
        "endpoint": "/api/v1/certidao/receita-pj",
        "campos_obrigatorios": ["cnpj"],
        "campos_opcionais": [],
        "exemplo": {"cnpj": "26546054000140"},
        "retorno_exemplo": {"status": "sucesso", "link": "http://tmpfiles.org/.../cert.pdf", "tipo_certidao": "Negativa"},
    },
    {
        "id": "receita-pf",
        "nome": "Receita Federal PF",
        "endpoint": "/api/v1/certidao/receita-pf",
        "campos_obrigatorios": ["cpf", "dt_nascimento"],
        "campos_opcionais": [],
        "exemplo": {"cpf": "99999999999", "dt_nascimento": "01/01/1900"},
        "retorno_exemplo": {"status": "sucesso", "link": "http://tmpfiles.org/.../cert.pdf", "tipo_certidao": "Negativa"},
    },
    {
        "id": "protesto",
        "nome": "Consulta Protesto",
        "endpoint": "/api/v1/certidao/protesto",
        "campos_obrigatorios": ["cpf_cnpj", "usuario_login", "usuario_senha"],
        "campos_opcionais": [],
        "exemplo": {"cpf_cnpj": "72467355187", "usuario_login": "72467355187", "usuario_senha": "@Protesto.25"},
        "retorno_exemplo": {"status": "sucesso", "link": "http://tmpfiles.org/.../protesto.pdf", "status": "Nao constam protestos"},
    },
    {
        "id": "stj-pf",
        "nome": "STJ Pessoa Fisica",
        "endpoint": "/api/v1/certidao/stj-pf",
        "campos_obrigatorios": ["cpf"],
        "campos_opcionais": [],
        "exemplo": {"cpf": "13683315725"},
        "retorno_exemplo": {"status": "sucesso", "link": "http://tmpfiles.org/.../stj.pdf"},
    },
    {
        "id": "stj-pj",
        "nome": "STJ Pessoa Juridica",
        "endpoint": "/api/v1/certidao/stj-pj",
        "campos_obrigatorios": ["cnpj"],
        "campos_opcionais": [],
        "exemplo": {"cnpj": "26546054000140"},
        "retorno_exemplo": {"status": "sucesso", "link": "http://tmpfiles.org/.../stj.pdf"},
    },
    {
        "id": "tjgo-civil",
        "nome": "TJGO Civel PF",
        "endpoint": "/api/v1/certidao/tjgo-civil",
        "campos_obrigatorios": ["nome", "cpf", "nm_mae", "dt_nascimento"],
        "campos_opcionais": [],
        "exemplo": {"nome": "THAINA SANTOS GONCALVES", "cpf": "13683315725", "nm_mae": "MARIA SANTOS", "dt_nascimento": "01/01/1990"},
        "retorno_exemplo": {"status": "sucesso", "link": "http://tmpfiles.org/.../tjgo.pdf"},
    },
    {
        "id": "tjgo-processos",
        "nome": "TJGO Processos",
        "endpoint": "/api/v1/certidao/tjgo-processos",
        "campos_obrigatorios": ["cpf_cnpj"],
        "campos_opcionais": [],
        "exemplo": {"cpf_cnpj": "04144748000119"},
        "retorno_exemplo": {"status": "sucesso", "link": "http://tmpfiles.org/.../tjgo.pdf"},
    },
    {
        "id": "tjgo-criminal",
        "nome": "TJGO Criminal PF",
        "endpoint": "/api/v1/certidao/tjgo-criminal",
        "campos_obrigatorios": ["nome", "cpf", "nm_mae", "dt_nascimento"],
        "campos_opcionais": [],
        "exemplo": {"nome": "THAINA SANTOS GONCALVES", "cpf": "13683315725", "nm_mae": "MARIA SANTOS", "dt_nascimento": "01/01/1990"},
        "retorno_exemplo": {"status": "sucesso", "link": "http://tmpfiles.org/.../tjgo.pdf"},
    },
    {
        "id": "trf1",
        "nome": "TRF1 (Civil/Criminal/Eleitoral)",
        "endpoint": "/api/v1/certidao/trf1",
        "campos_obrigatorios": ["tp_certidao", "tipo_cpf_cnpj", "cpf_cnpj"],
        "campos_opcionais": [],
        "nota": "tp_certidao: civil | criminal | eleitoral. tipo_cpf_cnpj: cpf | cnpj",
        "exemplo": {"tp_certidao": "criminal", "tipo_cpf_cnpj": "cnpj", "cpf_cnpj": "26546054000140"},
        "retorno_exemplo": {"status": "sucesso", "link": "http://tmpfiles.org/.../trf1.pdf"},
    },
    {
        "id": "tcu",
        "nome": "TCU - Nada Consta",
        "endpoint": "/api/v1/certidao/tcu",
        "campos_obrigatorios": [],
        "campos_opcionais": ["cpf", "cnpj"],
        "nota": "Informar cpf OU cnpj",
        "exemplo": {"cpf": "13683315725"},
        "retorno_exemplo": {"status": "sucesso", "tipo_certidao": "nada_consta", "nome": "THAINA SANTOS GONCALVES", "link": "http://tmpfiles.org/.../tcu.pdf"},
    },
    {
        "id": "cpf-receita",
        "nome": "CPF Receita (Situacao Cadastral)",
        "endpoint": "/api/v1/certidao/cpf-receita",
        "campos_obrigatorios": ["cpf", "data_nascimento"],
        "campos_opcionais": [],
        "exemplo": {"cpf": "13683315725", "data_nascimento": "01/01/1990"},
        "retorno_exemplo": {"status": "sucesso", "nome": "THAINA SANTOS GONCALVES", "situacao_cadastral": "REGULAR", "link": "http://tmpfiles.org/.../cpf.html"},
    },
    {
        "id": "mpf",
        "nome": "MPF - Certidao Negativa",
        "endpoint": "/api/v1/certidao/mpf",
        "campos_obrigatorios": [],
        "campos_opcionais": ["cpf", "cnpj"],
        "nota": "Informar cpf OU cnpj",
        "exemplo": {"cpf": "13683315725"},
        "retorno_exemplo": {"status": "sucesso", "nome": "THAINA SANTOS GONCALVES", "link": "http://tmpfiles.org/.../mpf.pdf", "metodo": "stealth_local"},
    },
    {
        "id": "stf",
        "nome": "STF (Distribuicao/Antecedentes/Eleitoral)",
        "endpoint": "/api/v1/certidao/stf",
        "campos_obrigatorios": [],
        "campos_opcionais": ["cpf", "cnpj", "tipo", "nome"],
        "nota": "Informar cpf OU cnpj. tipo default: distribuicao. Opcoes: distribuicao | antecedentes-criminais | fins-eleitorais | atuacao-de-advogado | objeto-e-pe",
        "exemplo": {"cpf": "13683315725", "tipo": "distribuicao"},
        "retorno_exemplo": {"status": "sucesso", "tipo_certidao": "distribuicao", "link": "http://tmpfiles.org/.../stf.pdf", "metodo": "local_audio_whisper"},
    },
    {
        "id": "trt18",
        "nome": "TRT18 Goias",
        "endpoint": "/api/v1/certidao/trt18",
        "campos_obrigatorios": ["cpf_cnpj"],
        "campos_opcionais": ["tipo"],
        "nota": "tipo: andamento (default) | arquivadas | objeto_pe",
        "exemplo": {"cpf_cnpj": "13683315725", "tipo": "andamento"},
        "retorno_exemplo": {"status": "sucesso", "link": "http://tmpfiles.org/.../trt18.pdf"},
    },
    {
        "id": "ibama",
        "nome": "IBAMA - Negativa de Debito",
        "endpoint": "/api/v1/certidao/ibama",
        "campos_obrigatorios": [],
        "campos_opcionais": ["cpf", "cnpj"],
        "nota": "Informar cpf OU cnpj",
        "exemplo": {"cnpj": "00000000000191"},
        "retorno_exemplo": {"status": "sucesso", "tipo_certidao": "nada_consta", "link": "http://tmpfiles.org/.../ibama.pdf"},
    },
    {
        "id": "tst-cndt",
        "nome": "TST CNDT - Debitos Trabalhistas",
        "endpoint": "/api/v1/certidao/tst-cndt",
        "campos_obrigatorios": [],
        "campos_opcionais": ["cpf", "cnpj"],
        "nota": "Informar cpf OU cnpj",
        "exemplo": {"cnpj": "33000167000101"},
        "retorno_exemplo": {"status": "sucesso", "tipo_certidao": "nada_consta", "nome": "BANCO DO BRASIL SA", "numero_certidao": "...", "validade": "dd/mm/aaaa", "link": "http://tmpfiles.org/.../cndt.pdf"},
    },
    {
        "id": "mpgo",
        "nome": "MPGO - Ministerio Publico GO",
        "endpoint": "/api/v1/certidao/mpgo",
        "campos_obrigatorios": [],
        "campos_opcionais": ["cpf", "cnpj"],
        "nota": "Informar cpf OU cnpj",
        "exemplo": {"cnpj": "33000167000101"},
        "retorno_exemplo": {"status": "sucesso", "link": "http://tmpfiles.org/.../mpgo.pdf", "pdf_size": 85528},
    },
]


@app.get("/", tags=["Status"])
async def root():
    return {
        "projeto": "PEDRO PROJECT - API de Certidoes",
        "versao": "1.0.0",
        "documentacao": "/docs",
        "total_endpoints": len(CERTIDOES_INFO),
    }


@app.get("/health", tags=["Status"])
async def health():
    return {"status": "ok"}


@app.get(
    "/api/v1/certidoes",
    tags=["Status"],
    summary="Lista todas as certidoes disponiveis com campos e exemplos",
)
async def listar_certidoes():
    return {"total": len(CERTIDOES_INFO), "certidoes": CERTIDOES_INFO}


# ═══════════════════════════════════════════════════════════
# JOBS — Execucao em lote (CPF ou CNPJ -> todas as certidoes)
# ═══════════════════════════════════════════════════════════

from pydantic import BaseModel, Field
from typing import Optional as Opt


class JobCreateRequest(BaseModel):
    """Request para criar job de certidoes em lote."""
    cpf: Opt[str] = Field(None, description="CPF -- informar cpf OU cnpj", json_schema_extra={"examples": ["27290000625"]})
    cnpj: Opt[str] = Field(None, description="CNPJ -- informar cpf OU cnpj", json_schema_extra={"examples": ["26546054000140"]})
    nome: Opt[str] = Field(None, description="Nome completo (necessario para TJGO civil/criminal)", json_schema_extra={"examples": ["JAIME FERREIRA DE OLIVEIRA NETO"]})
    nm_mae: Opt[str] = Field(None, description="Nome da mae (necessario para TJGO civil/criminal)", json_schema_extra={"examples": ["JORGETA TAHAN OLIVEIRA"]})
    dt_nascimento: Opt[str] = Field(None, description="Data nascimento dd/mm/aaaa (necessario para Receita PF e TJGO)", json_schema_extra={"examples": ["21/11/1958"]})


@app.post(
    "/api/v1/job",
    tags=["Jobs"],
    summary="Criar job de certidoes em lote",
    description=(
        "Recebe CPF ou CNPJ e dispara TODAS as certidoes relevantes em paralelo.\n\n"
        "**CPF:** ate 12 certidoes (STJ, TCU, MPF, TRT18, IBAMA, TST, MPGO, TJGO + Receita PF, TJGO civil/criminal, TRF1 se dados completos)\n\n"
        "**CNPJ:** ate 10 certidoes (Receita PJ, STJ, TCU, MPF, TRT18, IBAMA, TST, MPGO, TJGO, TRF1)\n\n"
        "Retorna job_id para consultar progresso via GET /api/v1/job/{job_id}"
    ),
)
async def criar_job(req: JobCreateRequest):
    doc = req.cpf or req.cnpj
    if not doc:
        raise HTTPException(status_code=422, detail="Informe cpf ou cnpj")

    from api.jobs import create_job
    params = {k: v for k, v in req.model_dump().items() if v is not None}
    result = create_job(params)
    tipo = "CPF" if req.cpf else "CNPJ"
    _api_log.info(f"JOB CRIADO | {result['job_id']} | {tipo} {doc} | {result['total']} certidoes")
    return JSONResponse(content=result, status_code=201)


@app.get(
    "/api/v1/job/{job_id}",
    tags=["Jobs"],
    summary="Consultar status de um job",
    description="Retorna status do job com resultados parciais. Certidoes vao aparecendo conforme completam.",
)
async def consultar_job(job_id: str):
    from api.jobs import get_job
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} nao encontrado")
    return JSONResponse(content=job)


@app.get(
    "/api/v1/jobs",
    tags=["Jobs"],
    summary="Listar jobs recentes",
)
async def listar_jobs(limit: int = 20):
    from api.jobs import list_jobs
    return JSONResponse(content={"jobs": list_jobs(limit)})


@app.delete(
    "/api/v1/job/{job_id}",
    tags=["Jobs"],
    summary="Deletar job",
)
async def deletar_job(job_id: str):
    from api.jobs import delete_job
    if delete_job(job_id):
        return JSONResponse(content={"ok": True})
    raise HTTPException(status_code=404, detail=f"Job {job_id} nao encontrado")


@app.get(
    "/api/v1/download/{job_id}/{cert_id}",
    tags=["Jobs"],
    summary="Baixar PDF de uma certidao",
    description="Retorna o PDF da certidao salvo localmente pelo worker.",
)
async def download_certidao(job_id: str, cert_id: str):
    from fastapi.responses import FileResponse
    pdf_path = PROJECT_ROOT / "api" / "downloads" / job_id / f"{cert_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF nao encontrado: {job_id}/{cert_id}")
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"certidao_{cert_id}_{job_id}.pdf",
    )


@app.get(
    "/api/v1/queue",
    tags=["Jobs"],
    summary="Status da fila e workers",
)
async def status_fila():
    from api.jobs import queue_size, get_redis
    r = get_redis()
    workers = r.smembers("pedro:workers:active")
    return JSONResponse(content={
        "fila": queue_size(),
        "workers": list(workers),
        "total_workers": len(workers),
    })


@app.get(
    "/api/v1/logs/recent",
    tags=["Dashboard"],
    summary="Logs recentes (ultimas 80 linhas)",
)
async def logs_recentes(arquivo: str = "pedro", linhas: int = 80):
    """arquivo: pedro | jobs | certidoes | erros"""
    import os
    allowed = {"pedro", "jobs", "certidoes", "erros"}
    if arquivo not in allowed:
        raise HTTPException(status_code=400, detail=f"Arquivo invalido. Use: {allowed}")
    log_path = PROJECT_ROOT / "logs" / f"{arquivo}.log"
    if not log_path.exists():
        return JSONResponse(content={"logs": "(vazio)"})
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        recent = all_lines[-linhas:]
        return JSONResponse(content={"logs": "".join(recent), "total_linhas": len(all_lines)})
    except Exception as e:
        return JSONResponse(content={"logs": f"Erro: {e}"})


# ═══════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="API Unificada de Certidoes")
    parser.add_argument("--port", type=int, default=API_PORT, help="Porta (default: 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--workers", type=int, default=1, help="Workers uvicorn (default: 1)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload em dev")
    args = parser.parse_args()

    uvicorn.run(
        "api.main:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
    )
