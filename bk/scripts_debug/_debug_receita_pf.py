#!/usr/bin/env python3
"""Debug: por que receita-pf falha no WSL2?"""
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import tempfile, time, traceback

tempdir = tempfile.mkdtemp()
options = uc.ChromeOptions()
options.add_argument('--no-first-run')
options.add_argument('--no-service-autorun')
options.add_argument('--password-store=basic')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_experimental_option('prefs', {
    "download.default_directory": tempdir,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "plugins.always_open_pdf_externally": True
})

driver = uc.Chrome(options=options)
driver.implicitly_wait(3)
print("Chrome OK")

try:
    driver.get("https://servicos.receitafederal.gov.br/servico/certidoes/#/home/cpf")
    print(f"Title: {driver.title}")
    time.sleep(5)
    print(f"URL: {driver.current_url}")

    # Aceitar cookies
    try:
        aceitar = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="card0"]/div/div[2]/button[2]'))
        )
        aceitar.click()
        print("Cookies aceitos")
    except:
        print("Sem modal de cookies")

    time.sleep(2)

    # Preencher CPF
    campo = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[name="niContribuinte"]'))
    )
    campo.send_keys("99999999999")
    print("CPF preenchido OK")

    # Preencher nascimento
    campo_nasc = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[name="dataNascimento"]'))
    )
    campo_nasc.send_keys("01/01/1900")
    print("Nascimento preenchido OK")

    # Nova Certidao
    WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, ".//button[contains(text(), 'Nova Certidão')]"))
    ).click()
    print("Botao Nova Certidao clicado")
    print("TUDO OK!")

except Exception as e:
    print(f"ERRO: {e}")
    traceback.print_exc()
    print(f"URL final: {driver.current_url}")

driver.quit()
