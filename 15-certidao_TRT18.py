#!/usr/bin/env python3
"""
15 - Certidão TRT18 (Tribunal Regional do Trabalho 18ª Região - Goiás)
Certidão de processos em andamento / arquivados / objeto e pé
SEM CAPTCHA - JSF/RichFaces puro
Padrão Pedro: undetected_chromedriver + Flask API + upload tmpfiles
"""
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests
import time
import random
import tempfile
import os
import shutil
from selenium.common.exceptions import TimeoutException
from flask import Flask, request, jsonify
import base64

app = Flask(__name__)


class Navegador:
    def __init__(self, headless=False):
        self.tempdir = tempfile.mkdtemp()
        options = uc.ChromeOptions()
        options.add_argument('--no-first-run')
        options.add_argument('--no-service-autorun')
        options.add_argument('--password-store=basic')
        options.add_argument('--start-maximized')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_experimental_option('prefs', {
            "download.default_directory": self.tempdir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True
        })
        if headless:
            options.add_argument('--headless=new')

        self.driver = uc.Chrome(options=options)
        self.driver.implicitly_wait(3)
        try:
            self.driver.maximize_window()
        except Exception:
            pass

    def pagina_inicial(self):
        self.driver.get("https://sistemas.trt18.jus.br/consultasPortal/pages/Processuais/Certidao.seam")

    def esperar_pdf_baixado(self, timeout=15):
        for _ in range(timeout):
            arquivos = [f for f in os.listdir(self.tempdir) if f.lower().endswith(".pdf")]
            if arquivos:
                return os.path.join(self.tempdir, arquivos[0])
            time.sleep(1)
        return None

    def upload_para_fileio(self, caminho_arquivo):
        try:
            with open(caminho_arquivo, 'rb') as f:
                response = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
            if response.status_code == 200:
                link = response.json().get("data", {}).get("url")
                return link
            else:
                print("Erro no upload. Status:", response.status_code)
                return None
        except Exception as e:
            print("Erro no upload:", e)
            return None

    def emitir_certidao(self, cpf_cnpj, tipo="andamento"):
        """
        tipo: "andamento" | "arquivadas" | "objeto_pe"
        """
        self.pagina_inicial()
        print(f"Iniciando consulta TRT18 para: {cpf_cnpj} (tipo: {tipo})")
        time.sleep(random.uniform(2, 4))

        # 1. Selecionar tipo de certidão
        tipo_map = {
            "andamento": "certidao:procsEmAnda",
            "arquivadas": "certidao:procsArq",
            "objeto_pe": "certidao:objPe",
        }
        link_id = tipo_map.get(tipo, "certidao:procsEmAnda")

        try:
            tipo_link = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, link_id))
            )
            tipo_link.click()
            print(f"Tipo '{tipo}' selecionado.")
        except TimeoutException:
            print(f"Tipo '{tipo}' não encontrado. Tentando por texto...")
            try:
                # Fallback: click by panel div
                panel_map = {
                    "andamento": "certidao:j_id60",
                    "arquivadas": "certidao:j_id66",
                    "objeto_pe": "certidao:j_id72",
                }
                panel = self.driver.find_element(By.ID, panel_map.get(tipo, "certidao:j_id60"))
                panel.click()
            except Exception as e:
                print(f"Erro ao selecionar tipo: {e}")
                return None

        time.sleep(random.uniform(2, 4))

        # 2. Aguardar campos de preenchimento (AJAX carrega novo form)
        try:
            # Esperar campo CPF/CNPJ aparecer
            cpf_input = WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[type="text"][maxlength="14"]'))
            )
            cpf_input.clear()
            cpf_input.send_keys(cpf_cnpj)
            print(f"CPF/CNPJ preenchido: {cpf_cnpj}")
        except TimeoutException:
            # Tentar outros seletores
            try:
                cpf_input = self.driver.find_element(By.XPATH, '//input[@type="text" and contains(@class, "soNumeros")]')
                cpf_input.clear()
                cpf_input.send_keys(cpf_cnpj)
            except Exception as e:
                print(f"Campo CPF não encontrado: {e}")
                return None

        time.sleep(random.uniform(1, 2))

        # 3. Clicar em "Emitir" / "Gerar"
        try:
            emitir_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH,
                    '//input[@type="submit" and (contains(@value, "Emitir") or contains(@value, "Gerar") or contains(@value, "Consultar"))]'))
            )
            emitir_btn.click()
            print("Botão Emitir clicado.")
        except TimeoutException:
            # Fallback: qualquer submit visivel
            try:
                btns = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="submit"]')
                for btn in btns:
                    if btn.is_displayed():
                        btn.click()
                        print("Submit fallback clicado.")
                        break
            except Exception as e:
                print(f"Botão submit não encontrado: {e}")
                return None

        time.sleep(random.uniform(3, 5))

        # 4. Capturar resultado como PDF via Page.printToPDF
        print("Gerando PDF da página resultado...")
        pdf_path = os.path.join(self.tempdir, f"certidao_trt18_{cpf_cnpj}.pdf")

        # Verificar se PDF foi baixado automaticamente
        downloaded_pdf = self.esperar_pdf_baixado(timeout=5)
        if downloaded_pdf:
            pdf_path = downloaded_pdf
            print(f"PDF baixado automaticamente: {pdf_path}")
        else:
            # Gerar via CDP
            try:
                pdf = self.driver.execute_cdp_cmd("Page.printToPDF", {
                    "printBackground": True,
                    "preferCSSPageSize": True
                })
                with open(pdf_path, "wb") as f:
                    f.write(base64.b64decode(pdf['data']))
                print(f"PDF via printToPDF: {pdf_path}")
            except Exception as e:
                print(f"Erro gerando PDF: {e}")
                return None

        # 5. Upload
        link = self.upload_para_fileio(pdf_path)

        # 6. Extrair texto do resultado para status
        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
            if "nada consta" in body_text.lower() or "não foram encontrad" in body_text.lower():
                status_texto = "nada_consta"
            elif "constam" in body_text.lower() or "encontrad" in body_text.lower():
                status_texto = "consta"
            else:
                status_texto = "verificar"
        except:
            status_texto = "verificar"

        return {"link": link, "status": status_texto, "tipo": tipo}

    def fechar(self):
        self.driver.quit()
        try:
            shutil.rmtree(self.tempdir)
            print(f"Pasta temporária {self.tempdir} removida com sucesso.")
        except Exception as e:
            print(f"Erro ao remover pasta temporária: {e}")


@app.route("/certidao", methods=["POST"])
def api_certidao():
    data = request.json or {}
    cpf_cnpj = data.get("cpf_cnpj") or data.get("cpf") or data.get("cnpj")
    tipo = data.get("tipo", "andamento")  # andamento | arquivadas | objeto_pe

    if not cpf_cnpj:
        return jsonify({"erro": "cpf_cnpj é obrigatório"}), 400

    bot = Navegador(headless=False)
    try:
        resultado = bot.emitir_certidao(cpf_cnpj, tipo)
        bot.fechar()

        if resultado and resultado.get("link"):
            return jsonify({
                "status": "sucesso",
                "link": resultado["link"],
                "resultado": resultado.get("status", "verificar"),
                "tipo_certidao": resultado.get("tipo", tipo),
            }), 200
        else:
            return jsonify({"status": "falha", "mensagem": "Certidão não disponível"}), 404
    except Exception as e:
        import traceback
        traceback.print_exc()
        bot.fechar()
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


if __name__ == "__main__":
    app.run(port=5015, debug=True)
