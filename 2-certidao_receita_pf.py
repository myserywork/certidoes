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
        self.driver.get("https://servicos.receitafederal.gov.br/servico/certidoes/#/home/cpf")
        

    def verificar_e_baixar_certidao(self):
        # Espera a tabela estar visível
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

    def emitir_certidao(self, cpf, dt_nascimento):
        self.pagina_inicial()

        print(f"Iniciando consulta para o CPF: {cpf} e Data de Nascimento: {dt_nascimento}")
        time.sleep(random.uniform(2, 4))

        # Aceitar cookies
        try:
            aceitar = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="card0"]/div/div[2]/button[2]'))
            )
            aceitar.click()
        except:
            print("Botão de cookies não encontrado ou já aceito.")
        time.sleep(random.uniform(1, 3))

        # Preencher CPF
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[name="niContribuinte"]'))
        ).send_keys(cpf)
        time.sleep(random.uniform(1, 2))

        # Preencher data nascimento
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[name="dataNascimento"]'))
        ).send_keys(dt_nascimento)
        time.sleep(random.uniform(1, 2))

        # Clicar no botao de acao (site pode ter diferentes versoes)
        clicked = False
        for label in ['Consultar Certidão', 'Nova Certidão', 'Emitir Certidão']:
            try:
                btn = WebDriverWait(self.driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, f".//button[contains(text(), '{label}')]"))
                )
                # Usar JS click (mais robusto com overlays Angular)
                self.driver.execute_script("arguments[0].click();", btn)
                print(f"Botao '{label}' clicado via JS")
                clicked = True
                break
            except:
                continue

        if not clicked:
            print("Nenhum botao de acao encontrado")
            return None

        time.sleep(3)

        # Tratar modal de certidao existente
        try:
            modal_btn = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.XPATH,
                    "/html/body/modal-container/div[2]/div/div[3]/button[2]"))
            )
            self.driver.execute_script("arguments[0].click();", modal_btn)
            print("Modal tratado")
        except:
            pass

        time.sleep(3)

        # Tentar submit se existir
        try:
            submit = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'button[type="submit"]'))
            )
            self.driver.execute_script("arguments[0].click();", submit)
        except:
            pass

        time.sleep(3)

        # Verificar resultado — tentar varias abordagens
        import base64

        # 1. Tentar tabela de certidoes
        try:
            resultado = self.verificar_e_baixar_certidao()
            if resultado and resultado.get("link"):
                return resultado
        except Exception as e:
            print(f"Tabela nao encontrada: {e}")

        # 2. Verificar se tem mensagem de erro/status na pagina
        try:
            body = self.driver.find_element(By.TAG_NAME, "body").text
            if "não existe" in body.lower() or "não há" in body.lower():
                print("Site diz: certidao nao existe")
        except Exception:
            pass

        # 3. Sempre gerar printToPDF como fallback
        print("Gerando PDF da pagina via printToPDF...")
        try:
            time.sleep(2)
            pdf = self.driver.execute_cdp_cmd("Page.printToPDF", {
                "printBackground": True,
                "preferCSSPageSize": True
            })
            pdf_path = os.path.join(self.tempdir, f"certidao_receita_pf_{cpf}.pdf")
            with open(pdf_path, "wb") as f:
                f.write(base64.b64decode(pdf['data']))
            print(f"PDF gerado: {pdf_path} ({os.path.getsize(pdf_path)} bytes)")
            link = self.upload_para_fileio(pdf_path)
            if link:
                return {"link": link, "tipo": "receita_pf"}
            # Upload falhou mas PDF local existe
            return {"link": None, "tipo": "receita_pf", "pdf_local": pdf_path}
        except Exception as e2:
            print(f"printToPDF falhou: {e2}")
            return None

    def fechar(self):
        self.driver.quit()
        try:
            shutil.rmtree(self.tempdir)
            print(f"Pasta temporária {self.tempdir} removida com sucesso.")
        except Exception as e:
            print(f"Erro ao remover pasta temporária: {e}")

    
@app.route("/certidao", methods=["POST"])
def api_certidao():
    cpf = request.json.get("cpf")
    dt_nascimento = request.json.get("dt_nascimento")

    if not cpf:
        return jsonify({"erro": "cpf não informado"}), 400

    bot = Navegador(headless=False)
    try:
        resultado = bot.emitir_certidao(cpf,dt_nascimento)  # recebe dicionário {"link":..., "tipo":...}
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
