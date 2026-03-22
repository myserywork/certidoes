"""
Utilidades cross-platform (Windows + Linux).
Substitui comandos Linux-only por equivalentes Windows quando necessario.
"""
import os
import sys
import subprocess
import tempfile
import platform

IS_WINDOWS = platform.system() == "Windows"
TEMP_DIR = tempfile.gettempdir()


def kill_chrome(pattern: str = "chrome"):
    """Mata processos Chrome. Funciona em Windows e Linux."""
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/IM", "chrome.exe", "/T"],
                capture_output=True, timeout=10,
            )
        else:
            subprocess.run(
                ["pkill", "-9", "-f", pattern],
                capture_output=True, timeout=5,
            )
    except Exception:
        pass


def kill_process(pattern: str):
    """Mata processo por pattern. Cross-platform."""
    try:
        if IS_WINDOWS:
            # taskkill por nome de janela ou imagem
            subprocess.run(
                ["taskkill", "/F", "/FI", f"IMAGENAME eq {pattern}*"],
                capture_output=True, timeout=10,
            )
        else:
            subprocess.run(
                ["pkill", "-9", "-f", pattern],
                capture_output=True, timeout=5,
            )
    except Exception:
        pass


def get_temp_path(filename: str = "") -> str:
    """Retorna path temporario cross-platform."""
    if filename:
        return os.path.join(TEMP_DIR, filename)
    return TEMP_DIR


def build_ns_command(ns: str, cmd: list, env_vars: dict = None) -> list:
    """
    Monta comando com ou sem namespace.
    No Windows: ignora namespace (roda direto).
    No Linux: usa ip netns exec se ns fornecido.
    """
    if IS_WINDOWS or not ns:
        return cmd

    # Linux com namespace
    _home = os.environ.get("HOME", "/root")
    _node_path = os.environ.get("NODE_PATH", "/root/node_modules")
    _display = os.environ.get("DISPLAY", ":121")

    env_parts = [
        "env",
        f"DISPLAY={_display}",
        f"HOME={_home}",
        f"NODE_PATH={_node_path}",
    ]
    if env_vars:
        for k, v in env_vars.items():
            env_parts.append(f"{k}={v}")

    return ["sudo", "-n", "ip", "netns", "exec", ns] + env_parts + cmd


def get_display() -> str:
    """Retorna display adequado."""
    if IS_WINDOWS:
        return ""  # Windows nao precisa de DISPLAY
    return os.environ.get("DISPLAY", os.environ.get("CAPTCHA_DISPLAY", ":121"))
