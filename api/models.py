"""
Modelos Pydantic para request/response da API de Certidoes.
Cada model corresponde exatamente aos campos que o script original espera.
"""
from pydantic import BaseModel, Field
from typing import Optional, Any


# ═══════════════════════════════════════════════════════════
# RESPONSES
# ═══════════════════════════════════════════════════════════

class CertidaoResponse(BaseModel):
    """Resposta padrao de todos os endpoints."""
    status: str = Field(..., description="sucesso | erro | falha | parcial")
    mensagem: Optional[str] = Field(None, description="Mensagem de erro ou informacao")
    link: Optional[str] = Field(None, description="Link tmpfiles.org do PDF/HTML da certidao")
    tipo_certidao: Optional[str] = Field(None, description="nada_consta | consta | positiva | verificar")
    nome: Optional[str] = Field(None, description="Nome do consultado (quando disponivel)")
    cpf_cnpj: Optional[str] = Field(None, description="CPF/CNPJ consultado")
    metodo: Optional[str] = Field(None, description="Metodo de resolucao do captcha")

    class Config:
        extra = "allow"


# ═══════════════════════════════════════════════════════════
# REQUESTS - SCRIPTS 1-9 (Pedro / Selenium)
# ═══════════════════════════════════════════════════════════

class ReceitaPJRequest(BaseModel):
    """1 - Certidao Receita Federal PJ"""
    cnpj: str = Field(
        ...,
        description="CNPJ (apenas digitos)",
        json_schema_extra={"examples": ["04144748000119"]},
    )


class ReceitaPFRequest(BaseModel):
    """2 - Certidao Receita Federal PF"""
    cpf: str = Field(
        ...,
        description="CPF (apenas digitos)",
        json_schema_extra={"examples": ["12345678900"]},
    )
    dt_nascimento: str = Field(
        ...,
        description="Data de nascimento dd/mm/aaaa",
        json_schema_extra={"examples": ["01/01/1990"]},
    )


class ProtestoRequest(BaseModel):
    """3 - Consulta Protesto"""
    cpf_cnpj: str = Field(
        ...,
        description="CPF ou CNPJ",
        json_schema_extra={"examples": ["12345678900"]},
    )
    usuario_login: str = Field(
        ...,
        description="Login do usuario no site de protesto",
        json_schema_extra={"examples": ["12345678900"]},
    )
    usuario_senha: str = Field(
        ...,
        description="Senha do usuario",
    )


class STJPFRequest(BaseModel):
    """4 - Certidao STJ Pessoa Fisica"""
    cpf: str = Field(
        ...,
        description="CPF (apenas digitos)",
        json_schema_extra={"examples": ["12345678900"]},
    )


class STJPJRequest(BaseModel):
    """5 - Certidao STJ Pessoa Juridica"""
    cnpj: str = Field(
        ...,
        description="CNPJ (apenas digitos)",
        json_schema_extra={"examples": ["26546054000140"]},
    )


class TJGOPessoaFisicaRequest(BaseModel):
    """6 e 8 - Certidao TJGO Civel/Criminal PF"""
    nome: str = Field(
        ...,
        description="Nome completo",
        json_schema_extra={"examples": ["FULANO DA SILVA"]},
    )
    cpf: str = Field(
        ...,
        description="CPF (apenas digitos)",
        json_schema_extra={"examples": ["12345678900"]},
    )
    nm_mae: str = Field(
        ...,
        description="Nome da mae",
        json_schema_extra={"examples": ["MARIA DA SILVA"]},
    )
    dt_nascimento: str = Field(
        ...,
        description="Data de nascimento dd/mm/aaaa",
        json_schema_extra={"examples": ["01/01/1990"]},
    )


class TJGOProcessosRequest(BaseModel):
    """7 - Consulta Processos TJGO PJ"""
    cpf_cnpj: str = Field(
        ...,
        description="CPF ou CNPJ",
        json_schema_extra={"examples": ["04144748000119"]},
    )


class TRF1Request(BaseModel):
    """9 - Certidao TRF1 (Civil / Criminal / Eleitoral)"""
    tp_certidao: str = Field(
        ...,
        description="Tipo da certidao: civil | criminal | eleitoral",
        json_schema_extra={"examples": ["civil"]},
    )
    tipo_cpf_cnpj: str = Field(
        ...,
        description="cpf ou cnpj",
        json_schema_extra={"examples": ["cpf"]},
    )
    cpf_cnpj: str = Field(
        ...,
        description="Numero do CPF ou CNPJ",
        json_schema_extra={"examples": ["12345678900"]},
    )


# ═══════════════════════════════════════════════════════════
# REQUESTS - SCRIPTS 11-18 (Puppeteer stealth + solvers)
# ═══════════════════════════════════════════════════════════

class TCURequest(BaseModel):
    """11 - Certidao TCU"""
    cpf: Optional[str] = Field(
        None,
        description="CPF (apenas digitos) -- informar cpf OU cnpj",
        json_schema_extra={"examples": ["12345678900"]},
    )
    cnpj: Optional[str] = Field(
        None,
        description="CNPJ (apenas digitos) -- informar cpf OU cnpj",
        json_schema_extra={"examples": ["00000000000191"]},
    )


class CPFReceitaRequest(BaseModel):
    """12 - Consulta Situacao Cadastral CPF Receita"""
    cpf: str = Field(
        ...,
        description="CPF (apenas digitos)",
        json_schema_extra={"examples": ["12345678900"]},
    )
    data_nascimento: str = Field(
        ...,
        description="Data de nascimento dd/mm/aaaa",
        json_schema_extra={"examples": ["01/01/1990"]},
    )


class MPFRequest(BaseModel):
    """13 - Certidao MPF"""
    cpf: Optional[str] = Field(
        None,
        description="CPF (apenas digitos) -- informar cpf OU cnpj",
        json_schema_extra={"examples": ["12345678900"]},
    )
    cnpj: Optional[str] = Field(
        None,
        description="CNPJ (apenas digitos) -- informar cpf OU cnpj",
        json_schema_extra={"examples": ["00000000000191"]},
    )


class STFRequest(BaseModel):
    """14 - Certidao STF"""
    cpf: Optional[str] = Field(
        None,
        description="CPF -- informar cpf OU cnpj",
        json_schema_extra={"examples": ["12345678900"]},
    )
    cnpj: Optional[str] = Field(
        None,
        description="CNPJ -- informar cpf OU cnpj",
        json_schema_extra={"examples": ["33000167000101"]},
    )
    tipo: str = Field(
        "distribuicao",
        description="Tipo: distribuicao | antecedentes-criminais | fins-eleitorais | atuacao-de-advogado | objeto-e-pe",
        json_schema_extra={"examples": ["distribuicao"]},
    )
    nome: str = Field(
        "",
        description="Nome completo do sujeito",
        json_schema_extra={"examples": ["JAIME FERREIRA DE OLIVEIRA NETO"]},
    )
    nome_mae: str = Field(
        "",
        description="Nome da mae (obrigatorio para PF)",
        json_schema_extra={"examples": ["JORGETA TAHAN OLIVEIRA"]},
    )
    rg: str = Field(
        "",
        description="Numero do RG (obrigatorio para PF)",
        json_schema_extra={"examples": ["1234567"]},
    )
    orgao_expedidor: str = Field(
        "",
        description="Orgao expedidor do RG (ex: SSP/GO)",
        json_schema_extra={"examples": ["SSP/GO"]},
    )
    estado_civil: str = Field(
        "",
        description="Estado civil: solteiro | casado | divorciado | viuvo | separado | uniao_estavel",
        json_schema_extra={"examples": ["casado"]},
    )


class TRT18Request(BaseModel):
    """15 - Certidao TRT18 Goias"""
    cpf_cnpj: str = Field(
        ...,
        description="CPF ou CNPJ",
        json_schema_extra={"examples": ["12345678900"]},
    )
    tipo: str = Field(
        "andamento",
        description="Tipo: andamento | arquivadas | objeto_pe",
        json_schema_extra={"examples": ["andamento"]},
    )


class IBAMARequest(BaseModel):
    """16 - Certidao IBAMA"""
    cpf: Optional[str] = Field(
        None,
        description="CPF -- informar cpf OU cnpj",
        json_schema_extra={"examples": ["12345678900"]},
    )
    cnpj: Optional[str] = Field(
        None,
        description="CNPJ -- informar cpf OU cnpj",
        json_schema_extra={"examples": ["00000000000191"]},
    )


class TSTCNDTRequest(BaseModel):
    """17 - CNDT TST"""
    cpf: Optional[str] = Field(
        None,
        description="CPF -- informar cpf OU cnpj",
        json_schema_extra={"examples": ["12345678900"]},
    )
    cnpj: Optional[str] = Field(
        None,
        description="CNPJ -- informar cpf OU cnpj",
        json_schema_extra={"examples": ["33000167000101"]},
    )


class MPGORequest(BaseModel):
    """18 - Certidao MPGO"""
    cpf: Optional[str] = Field(
        None,
        description="CPF -- informar cpf OU cnpj",
        json_schema_extra={"examples": ["12345678900"]},
    )
    cnpj: Optional[str] = Field(
        None,
        description="CNPJ -- informar cpf OU cnpj",
        json_schema_extra={"examples": ["33000167000101"]},
    )
