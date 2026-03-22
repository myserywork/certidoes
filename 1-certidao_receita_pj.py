import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests
import random
import time
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import argparse
from flask import Flask, request, jsonify
import time
import random
import tempfile
import os
import shutil


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
        self.driver.get("https://servicos.receitafederal.gov.br/servico/certidoes/#/home/cnpj")
        
    def tratar_certidao_existente(self):
        try:
            # Espera até o modal estar presente (timeout curto)
            modal = WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.CLASS_NAME, "modal-content"))
            )
            # Verifica se o texto esperado está no modal
            texto_modal = modal.text
            if "Já existe uma certidão válida" in texto_modal:
                # Encontra e clica no botão "Consultar Certidão"
                btn_consultar = modal.find_element(By.XPATH, ".//button[contains(text(), 'Consultar Certidão')]")
                btn_consultar.click()
                print("Modal detectado e botão 'Consultar Certidão' clicado.")
                return True
        except (TimeoutException, NoSuchElementException):
            # Modal não apareceu, ou botão não encontrado, segue normalmente
            pass
        return False

    def verificar_e_baixar_certidao(self):
        # Espera a tabela estar visível
        print("Esperando tabela de certidões...")
        WebDriverWait(self.driver, 10).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, 'datatable-body'))
        )
        
        # Localiza todas as linhas visíveis na tabela (cada linha é um 'datatable-body-row')
        linhas = self.driver.find_elements(By.CSS_SELECTOR, 'datatable-body-row')
        if not linhas:
            print("Nenhuma linha encontrada na tabela.")
            return
        
        for linha in linhas:
            # Na linha, localize a célula da coluna "Tipo" (terceira coluna)
            # Ajuste o índice se necessário (index começa em 0)
            # Pelo seu HTML, "Tipo" está na terceira coluna: datatable-body-cell[2] (contando 1-based)
            celula_tipo = linha.find_element(By.CSS_SELECTOR, 'datatable-body-cell:nth-child(3) div.datatable-body-cell-label span').text
            celula_situacao = linha.find_element(By.CSS_SELECTOR, 'datatable-body-cell:nth-child(6) div.datatable-body-cell-label span').text
   
            
            if celula_situacao.lower() == "válida":
                print(f"Tipo de certidão: {celula_tipo}")
                tipo_certidao = celula_tipo
            else:
                print("Certidão não válida ou expirada.")
                tipo_certidao = "Certidão expirada"


            # Localiza botão para baixar certidão (última coluna: coluna 7 no seu exemplo)
            # Ajuste índice se mudar estrutura
            try:
                botao_baixar = linha.find_element(By.CSS_SELECTOR, 'datatable-body-cell:nth-child(7) button')
                botao_baixar.click()
                print("Botão para baixar a certidão clicado.")
                time.sleep(5)
                                # Espera o arquivo aparecer na pasta temporária
                arquivo = self.esperar_pdf_baixado()
                if arquivo:
                    link = self.upload_para_fileio(arquivo)
                    # Aqui, retorna link e tipo_certidao juntos
                    return {"link": link, "tipo": tipo_certidao}
                
            except Exception as e:
                print("Botão para baixar certidão não encontrado ou não clicável:", e)

            # Se quiser processar apenas a primeira linha, pode fazer break aqui
            break

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

    def emitir_certidao(self, cnpj):
        self.pagina_inicial()
        try:
            aceitar = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="card0"]/div/div[2]/button[2]'))
            )
            aceitar.click()
        except:
            print("Botão de cookies não encontrado ou já aceito.")
        time.sleep(random.uniform(1, 3))
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[name="niContribuinte"]'))
        ).send_keys(cnpj)
        time.sleep(random.uniform(1, 3))
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, ".//button[contains(text(), 'Consultar Certidão')]"))
        ).click()
        
        if self.tratar_certidao_existente():
            # Continue o fluxo após clicar em "Consultar Certidão"
            pass
        else:
            # Caso modal não apareça, continue normalmente
            pass
        time.sleep(3)
        try:
            WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[type="submit"]'))).click()
        except TimeoutException:
            pass
        time.sleep(3)
        
        try:
            aviso = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'div[class="description"]'))
            ).text
            print("Aviso:", aviso)
            if aviso == 'Não existe certidão emitida para os dados consultados.':
                WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.XPATH, '//button[contains(text(), "Voltar")]'))).click()
                WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[type="submit"]'))).click()
        except TimeoutException:
            pass
        time.sleep(3)
        try:
            resultado = self.verificar_e_baixar_certidao()
            return resultado  # retornando dicionário com link e tipo
        except Exception as e:
            print("Não foi possível emitir certidão. Favor verificar site da Receita", e)
            return None  # <- também bom garantir um retorno padrão

    def fechar(self):
        self.driver.quit()
        try:
            shutil.rmtree(self.tempdir)
            print(f"Pasta temporária {self.tempdir} removida com sucesso.")
        except Exception as e:
            print(f"Erro ao remover pasta temporária: {e}")

    
@app.route("/certidao", methods=["POST"])
def api_certidao():
    cnpj = request.json.get("cnpj")
    dt_nascimento = request.json.get("dt_nascimento")

    if not cnpj:
        return jsonify({"erro": "cnpj não informado"}), 400

    bot = Navegador(headless=False)
    try:
        resultado = bot.emitir_certidao(cnpj)  # recebe dicionário {"link":..., "tipo":...}
        bot.fechar()
        
        if resultado and resultado.get("link"):
            return jsonify({
                "status": "sucesso",
                "link": resultado["link"],
                "tipo_certidao": resultado.get("tipo", "desconhecida")
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
