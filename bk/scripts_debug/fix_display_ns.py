#!/usr/bin/env python3
"""Fix DISPLAY for namespace scripts - adds TCP X11 display mapping."""
import re, glob, os

NS_DISPLAY_BLOCK = """
# Mapeamento de display para namespaces (X11 via TCP no WSL2)
NS_DISPLAY_MAP = {
    "ns_t0": "10.200.0.1:121.0",
    "ns_t1": "10.200.1.1:121.0",
    "ns_t2": "10.200.2.1:121.0",
    "ns_t3": "10.200.3.1:121.0",
    "ns_t4": "10.200.4.1:121.0",
}
"""

BASE = "/root/pedro_project"

files_to_fix = [
    "13-certidao_MPF.py",
    "14-certidao_STF.py",
    "16-certidao_IBAMA.py",
    "18-certidao_MPGO.py",
    "infra/local_captcha_solver.py",
    "infra/aws_waf_solver.py",
    "infra/hcaptcha_solver.py",
    "infra/tst_captcha_solver.py",
]

for fname in files_to_fix:
    fpath = os.path.join(BASE, fname)
    if not os.path.exists(fpath):
        continue

    with open(fpath, "r") as f:
        code = f.read()

    changed = False

    # Add NS_DISPLAY_MAP if not present
    if "NS_DISPLAY_MAP" not in code:
        # Insert after imports
        insert_pos = code.find("\ndef ")
        if insert_pos == -1:
            insert_pos = code.find("\napp = ")
        if insert_pos == -1:
            insert_pos = code.find("\n# ---")
        if insert_pos > 0:
            code = code[:insert_pos] + NS_DISPLAY_BLOCK + code[insert_pos:]
            changed = True

    # Fix DISPLAY in namespace exec commands
    # Pattern: f"DISPLAY={display}" when inside ns block
    # Replace with: f"DISPLAY={NS_DISPLAY_MAP.get(ns, display) if ns else display}"
    old_pattern = 'f"DISPLAY={display}"'
    new_pattern = 'f"DISPLAY={NS_DISPLAY_MAP.get(ns, display)}"'

    # Only replace inside the ns block (where cmd has "ip", "netns")
    if old_pattern in code and "ip\", \"netns" in code:
        # Find all occurrences that are in namespace context
        lines = code.split("\n")
        in_ns_block = False
        for i, line in enumerate(lines):
            if "if ns:" in line or "if ns " in line:
                in_ns_block = True
            elif in_ns_block and (line.strip().startswith("else:") or (line.strip() and not line.startswith(" ") and not line.startswith("\t"))):
                in_ns_block = False

            if in_ns_block and old_pattern in line:
                lines[i] = line.replace(old_pattern, new_pattern)
                changed = True

        code = "\n".join(lines)

    if changed:
        with open(fpath, "w") as f:
            f.write(code)
        print(f"  Fixed: {fname}")
    else:
        print(f"  Skip: {fname} (already fixed or no match)")
