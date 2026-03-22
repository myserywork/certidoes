import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
import requests
import time
import random
import tempfile
import os
import shutil
from selenium.common.exceptions import TimeoutException
from flask import Flask, request, jsonify
import base64
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys

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
        self.driver.get("https://sistemas.trf1.jus.br/certidao/#/solicitacao")

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

    def emitir_certidao(self, tp_certidao,tipo_cpf_cnpj,cpf_cnpj):
        self.pagina_inicial()
        print(f"Selecionando o tipo de certidão: {tp_certidao}...")
        time.sleep(random.uniform(1, 3))
        # variável de entrada
        tp_certidao = tp_certidao  # "civil", "criminal", "eleitoral"

        opcoes_map = {
            "civil": "Cível",
            "criminal": "Criminal",
            "eleitoral": "Para fins eleitorais"
        }

        # 1. Espera o mat-select pelo formcontrolname (mais estável que ID)
        mat_select = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//mat-select[@formcontrolname='tipoCertidaoControl']"))
        )
        mat_select.click()

        # 2. Aguardar opções ficarem visíveis no overlay
        opcao_texto = opcoes_map[tp_certidao]
        opcao_elemento = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, f"//mat-option//span[normalize-space(text())='{opcao_texto}']"))
        )

        # 3. Clicar na opção
        opcao_elemento.click()
        
        print("Selecionando órgão...")
        # Texto que sempre será selecionado
        orgao_texto = "Regionalizada (1º e 2º Graus)"

        # 1. Localiza o campo do chip list pelo formcontrolname estável
        chip_input = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//mat-chip-list[@formcontrolname='orgaoChipListControl']//input"))
        )

        # 2. Clica e digita para acionar o autocomplete
        chip_input.click()
        chip_input.clear()
        chip_input.send_keys("Regionalizada")  # pode ser parte do texto para filtrar

        # 3. Aguarda a opção no autocomplete
        opcao_elemento = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, f"//mat-option//span[normalize-space(text())='{orgao_texto}']"))
        )

        # 4. Clica na opção
        opcao_elemento.click()

        
        # Força fechar o autocomplete
        chip_input.send_keys(Keys.ESCAPE)

        # Aguarda sumir o overlay
        WebDriverWait(self.driver, 10).until(
            EC.invisibility_of_element_located((By.XPATH, "//div[contains(@class,'cdk-overlay-pane')]"))
        )

        print("Selecionando CPF ou CNPJ:")
        tipo_cpf_cnpj = tipo_cpf_cnpj.lower()  # Normaliza para minúsculas
        if tipo_cpf_cnpj == "cpf":
            radio_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((
                    By.XPATH, "//mat-radio-button[@value='1' and .//div[contains(text(), 'CPF')]]"
                ))
            )
            radio_button.click()
        elif tipo_cpf_cnpj == "cnpj":
            radio_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((
                    By.XPATH, "//mat-radio-button[@value='2' and .//div[contains(text(), 'CNPJ')]]"
                ))
            )
            radio_button.click()
        else:
            print("Tipo de CPF/CNPJ não reconhecido.")

        time.sleep(random.uniform(1, 3))
            
        print("Digitando o CPF ou CNPJ...")
        WebDriverWait(self.driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@type="text"]'))
        ).send_keys(cpf_cnpj)
        
        time.sleep(random.uniform(1, 3))
        
        print("Clicando no botão emitir certidão")
        emitir_button = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button//span[normalize-space(text())='Emitir Certidão']"))
        )
        emitir_button.click()

        time.sleep(random.uniform(1, 3))
        print("Clicando no botão imprimir")
        emitir_button = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button//span[normalize-space(text())='Imprimir']"))
        )
        emitir_button.click()

        # Aguarda o download do PDF
        print("Aguardando download do PDF...")
        caminho_pdf = self.esperar_pdf_baixado(timeout=20)
        if not caminho_pdf:
            raise Exception("PDF não foi baixado dentro do tempo esperado.")

        print(f"PDF baixado: {caminho_pdf}")

        # Faz o upload do PDF para tmpfiles
        link = self.upload_para_fileio(caminho_pdf)
        if not link:
            raise Exception("Falha ao fazer upload do arquivo PDF.")

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
    tp_certidao = request.json.get("tp_certidao")
    tipo_cpf_cnpj = request.json.get("tipo_cpf_cnpj")
    cpf_cnpj = request.json.get("cpf_cnpj")

    if not cpf_cnpj or not tipo_cpf_cnpj or not tp_certidao:
        return jsonify({"erro": "cpf_cnpj, tipo_cpf_cnpj e tp_certidao são obrigatórios"}), 400

    bot = Navegador(headless=False)
    try:
        resultado = bot.emitir_certidao(tp_certidao,tipo_cpf_cnpj,cpf_cnpj)
        bot.fechar()

        if resultado and resultado.get("link"):
            return jsonify({
                "status": "sucesso",
                "link": resultado["link"]
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
