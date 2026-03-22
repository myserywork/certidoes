import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests
import random
import time
from selenium.common.exceptions import TimeoutException
from flask import Flask, request, jsonify
import tempfile
import os
import shutil
import urllib3

# Desativar warnings de SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
        self.driver.get("https://projudi.tjgo.jus.br/CertidaoNegativaPositivaPublica?PaginaAtual=1&TipoArea=1&InteressePessoal=&Territorio=&Finalidade=")

    def upload_para_fileio(self, caminho_arquivo):
        try:
            with open(caminho_arquivo, 'rb') as f:
                response = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
            print("Resposta do tmpfiles:", response.text)
            if response.status_code == 200:
                link = response.json().get("data", {}).get("url")
                print("Arquivo enviado. Link:", link)
                return link
            else:
                print("Erro no upload. Status:", response.status_code)
                return None
        except Exception as e:
            print("Erro no upload:", e)
            return None

    def emitir_certidao(self, nome, cpf, nm_mae, dt_nascimento):
        self.pagina_inicial()

        print(f"Iniciando consulta para o CPF: {cpf} e Data de Nascimento: {dt_nascimento}")
        time.sleep(random.uniform(1, 3))
        
        WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="Nome"]'))).send_keys(nome)
        time.sleep(random.uniform(1, 3))
        WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="Cpf"]'))).send_keys(cpf)
        time.sleep(random.uniform(1, 3))
        WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="NomeMae"]'))).send_keys(nm_mae)
        time.sleep(random.uniform(1, 3))
        WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.XPATH, '//*[@id="DataNascimento"]'))).send_keys(dt_nascimento)
        time.sleep(random.uniform(1, 3))

        try:
            WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.XPATH, '//*[@value="Gerar Certidão"]'))).click()
        except TimeoutException:
            print("Botão de gerar certidão não encontrado.")
            return None

        # Aguardar download do PDF
        print("Aguardando download do PDF...")
        pdf_path = None
        timeout = time.time() + 15
        while time.time() < timeout:
            arquivos = os.listdir(self.tempdir)
            pdfs = [f for f in arquivos if f.lower().endswith(".pdf")]
            if pdfs:
                pdf_path = os.path.join(self.tempdir, pdfs[0])
                if not any(f.endswith(".crdownload") for f in arquivos):
                    break
            time.sleep(0.5)

        if not pdf_path or not os.path.exists(pdf_path):
            # Fallback: printToPDF da pagina resultado
            print("Download nao detectado, usando printToPDF...")
            import base64
            try:
                pdf = self.driver.execute_cdp_cmd("Page.printToPDF", {
                    "printBackground": True,
                    "preferCSSPageSize": True
                })
                pdf_path = os.path.join(self.tempdir, f"certidao_civil_tjgo_{cpf}.pdf")
                with open(pdf_path, "wb") as f:
                    f.write(base64.b64decode(pdf['data']))
                print(f"printToPDF OK: {pdf_path}")
            except Exception as e:
                print(f"printToPDF falhou: {e}")
                return None

        print(f"PDF baixado: {pdf_path}")
        link = self.upload_para_fileio(pdf_path)
        return {"link": link}


    def fechar(self):
        self.driver.quit()
        try:
            shutil.rmtree(self.tempdir)
            print(f"Pasta temporária {self.tempdir} removida com sucesso.")
        except Exception as e:
            print(f"Erro ao remover pasta temporária: {e}")

    
@app.route("/certidao", methods=["POST"])
def api_certidao():
    nome = request.json.get("nome")
    cpf = request.json.get("cpf")
    nm_mae = request.json.get("nm_mae")
    dt_nascimento = request.json.get("dt_nascimento")

    if not cpf:
        return jsonify({"erro": "cpf não informado"}), 400

    bot = Navegador(headless=False)
    try:
        resultado = bot.emitir_certidao(nome, cpf, nm_mae, dt_nascimento)  
        bot.fechar()
        
        if resultado and resultado.get("link"):
            return jsonify({
                "status": "sucesso",
                "link": resultado["link"],
            }), 200
        else:
            return jsonify({"status": "falha", "mensagem": "Certidão não disponível"}), 404
    except Exception as e:
        import traceback
        traceback.print_exc()
        bot.fechar()
        return jsonify({"status": "erro", "mensagem": str(e)}), 500



if __name__ == "__main__":
    app.run(port=5000, debug=True)
