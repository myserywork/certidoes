#!/usr/bin/env python3
"""Debug: verificar fluxo atual do site da Receita PF"""
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import tempfile, time

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

driver.get("https://servicos.receitafederal.gov.br/servico/certidoes/#/home/cpf")
print(f"Title: {driver.title}")
time.sleep(5)

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
campo.send_keys("27290000625")
print("CPF preenchido")

# Preencher nascimento
time.sleep(1)
campo_nasc = WebDriverWait(driver, 10).until(
    EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[name="dataNascimento"]'))
)
campo_nasc.send_keys("21/11/1958")
print("Nascimento preenchido")
time.sleep(2)

# Listar TODOS os botões visíveis na página
botoes = driver.find_elements(By.TAG_NAME, "button")
print(f"\nBotoes encontrados: {len(botoes)}")
for i, b in enumerate(botoes):
    txt = b.text.strip()
    vis = b.is_displayed()
    enabled = b.is_enabled()
    if txt or vis:
        print(f"  [{i}] text='{txt}' visible={vis} enabled={enabled}")

# Tentar variações do botão
for label in ['Consultar Certidão', 'Consultar', 'Nova Certidão', 'Emitir', 'Enviar']:
    try:
        btn = driver.find_element(By.XPATH, f".//button[contains(text(), '{label}')]")
        print(f"\nBotao '{label}' ENCONTRADO: displayed={btn.is_displayed()}")
    except:
        pass

# Print page source snippet para ver o HTML
print(f"\nURL: {driver.current_url}")
src = driver.page_source
# Procurar por botões no source
import re
buttons = re.findall(r'<button[^>]*>([^<]*)</button>', src)
print(f"Botoes no HTML: {buttons[:10]}")

driver.quit()
