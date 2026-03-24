"""
Shared helpers para scripts HTTP de certidões.
"""
import subprocess
import tempfile
import os
import re
import requests


def clean_certidao_html(html: str, titulo: str = "Certidao", orgao: str = "") -> str:
    """
    Limpa HTML de certidão: remove menus, headers, scripts do site original.
    Adiciona header DIP e formatação profissional.
    """
    # Extrair o conteúdo relevante
    body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
    body = body_match.group(1) if body_match else html

    # Remover scripts, styles, nav, menus, iframes, forms
    body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r'<nav[^>]*>.*?</nav>', '', body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r'<iframe[^>]*>.*?</iframe>', '', body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r'<header[^>]*>.*?</header>', '', body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r'<footer[^>]*>.*?</footer>', '', body, flags=re.DOTALL | re.IGNORECASE)
    # Remover menus, nav bars, sidebars
    body = re.sub(r'<div[^>]*class="[^"]*(?:menu|sidebar|navbar|topbar|header|footer|bread)[^"]*"[^>]*>.*?</div>', '', body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r'<ul[^>]*class="[^"]*nav[^"]*"[^>]*>.*?</ul>', '', body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r'<a[^>]*href="javascript:[^"]*"[^>]*>.*?</a>', '', body, flags=re.DOTALL | re.IGNORECASE)
    # Remover formularios (inputs, selects, textareas)
    body = re.sub(r'<form[^>]*>.*?</form>', '', body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r'<input[^>]*/?\s*>', '', body, flags=re.IGNORECASE)
    body = re.sub(r'<select[^>]*>.*?</select>', '', body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r'<textarea[^>]*>.*?</textarea>', '', body, flags=re.DOTALL | re.IGNORECASE)
    # Remover fieldsets com formulario (TJGO)
    body = re.sub(r'<fieldset[^>]*>.*?Dados da Certid.*?</fieldset>', '', body, flags=re.DOTALL | re.IGNORECASE)
    # Limpar tags vazias e espacos excessivos
    body = re.sub(r'<(?:div|span|p|li|ul|ol)\s*>\s*</(?:div|span|p|li|ul|ol)>', '', body, flags=re.IGNORECASE)
    body = re.sub(r'\n{3,}', '\n\n', body)

    from datetime import datetime
    data = datetime.now().strftime("%d/%m/%Y %H:%M")

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>{titulo}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px; background: white; color: #333; font-size: 14px; line-height: 1.6; }}
  .dip-header {{ background: linear-gradient(135deg, #007366, #00aa84); color: white; padding: 15px 20px; border-radius: 8px; margin-bottom: 20px; display: flex; align-items: center; justify-content: space-between; }}
  .dip-header h1 {{ margin: 0; font-size: 16px; font-weight: 700; }}
  .dip-header .meta {{ font-size: 11px; opacity: 0.8; }}
  .certidao-body {{ border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; background: #fafafa; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
  th, td {{ padding: 8px 12px; border: 1px solid #ddd; text-align: left; font-size: 13px; }}
  th {{ background: #007366; color: white; font-weight: 600; }}
  .footer {{ margin-top: 20px; padding-top: 15px; border-top: 1px solid #e0e0e0; text-align: center; font-size: 11px; color: #999; }}
  @media print {{
    body {{ padding: 10px; }}
    .dip-header {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    th {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  }}
</style>
</head>
<body>
  <div class="dip-header">
    <div>
      <h1>{titulo}</h1>
      <div class="meta">{orgao}</div>
    </div>
    <div class="meta">Emitido em {data}<br>DIP - Diligencia Inteligente</div>
  </div>
  <div class="certidao-body">
    {body}
  </div>
  <div class="footer">
    Documento extraido automaticamente via DIP (Diligencia Previa Inteligente) em {data}
  </div>
</body>
</html>"""


def html_to_pdf(html_content: str, filename: str = "certidao.pdf") -> str:
    """Convert HTML to PDF using Chrome headless."""
    tmpdir = tempfile.mkdtemp()
    html_path = os.path.join(tmpdir, "page.html")
    pdf_path = os.path.join(tmpdir, filename)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome):
        chrome = "google-chrome"

    subprocess.run([
        chrome, "--headless", "--disable-gpu", "--no-sandbox",
        f"--print-to-pdf={pdf_path}", f"file:///{html_path.replace(os.sep, '/')}"
    ], capture_output=True, timeout=30)

    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 100:
        return pdf_path
    return None


def upload_pdf(pdf_path: str) -> str:
    """Upload PDF to tmpfiles.org."""
    with open(pdf_path, "rb") as f:
        r = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": f}, timeout=30)
    if r.status_code == 200:
        data = r.json()
        return data.get("data", {}).get("url", "")
    return None
