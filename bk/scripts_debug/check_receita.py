#!/usr/bin/env python3
"""Check Receita page form fields and JS functions."""
import sys
import os
import time
import json

sys.path.insert(0, "/root/pedro_project")
os.environ.setdefault("DISPLAY", ":121")

import undetected_chromedriver as uc

options = uc.ChromeOptions()
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1200,900")

driver = uc.Chrome(options=options, version_main=131, browser_executable_path="/opt/chrome131/chrome")
try:
    driver.get("https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/consultapublica.asp")
    time.sleep(5)

    result = driver.execute_script("""
        var info = {};
        // Check pegaObj
        try { info.pegaObj_src = pegaObj.toString(); } catch(e) { info.pegaObj_err = e.message; }

        // Check h-recaptcha-response element
        try {
            var el = pegaObj('h-recaptcha-response');
            if (el) {
                info.h_recaptcha_response = {tag: el.tagName, id: el.id, name: el.name, val: (el.value || '').substring(0,50)};
            } else {
                info.h_recaptcha_response = 'null/undefined';
            }
        } catch(e) { info.h_recaptcha_response_err = e.message; }

        // List ALL inputs/textareas in form
        var form = document.getElementById('theForm');
        if (form) {
            var inputs = form.querySelectorAll('input, textarea, select');
            info.form_fields = [];
            inputs.forEach(function(el) {
                info.form_fields.push({
                    tag: el.tagName, id: el.id, name: el.name,
                    type: el.type, val: (el.value || '').substring(0,50)
                });
            });
        }

        // Check cookies
        info.cookies = document.cookie;

        return info;
    """)
    print(json.dumps(result, indent=2, ensure_ascii=False))
finally:
    driver.quit()
