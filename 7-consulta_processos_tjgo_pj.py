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
        self.driver.get("https://projudi.tjgo.jus.br/BuscaProcesso?PaginaAtual=4&TipoConsultaProcesso=24")

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

    def emitir_certidao(self, cpf_cnpj):
        self.pagina_inicial()
        print(f"Iniciando consulta para o CPF/CNPJ: {cpf_cnpj}")
        time.sleep(random.uniform(1, 3))


        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="CpfCnpjParte"]'))
        ).send_keys(cpf_cnpj)

        time.sleep(random.uniform(1, 3))

        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@value="Buscar"]'))
        ).click()

        time.sleep(3)

        # Tira print da tela e salva na pasta temporária
        # Gera PDF da página inteira via DevTools
        pdf_path = os.path.join(self.tempdir, f"resultado_{cpf_cnpj}.pdf")
        pdf = self.driver.execute_cdp_cmd("Page.printToPDF", {
            "printBackground": True,
            "preferCSSPageSize": True
        })
        with open(pdf_path, "wb") as f:
            f.write(base64.b64decode(pdf['data']))

        # Faz upload do PDF
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
    cpf_cnpj = request.json.get("cpf_cnpj")

    if not cpf_cnpj:
        return jsonify({"erro": "cpf_cnpj é obrigatório"}), 400

    bot = Navegador(headless=False)
    try:
        resultado = bot.emitir_certidao(cpf_cnpj)
        bot.fechar()

        if resultado and resultado.get("link"):
            return jsonify({
                "status": "sucesso",
                "link": resultado["link"],
            }), 200
        else:
            return jsonify({"status": "falha", "mensagem": "Falha ao gerar link da imagem"}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        bot.fechar()
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


if __name__ == "__main__":
    app.run(port=5000, debug=True)
