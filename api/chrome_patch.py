"""
Patch para forcar --no-sandbox e --disable-dev-shm-usage no undetected_chromedriver.
Importar ANTES de qualquer script que use undetected_chromedriver.

Em Docker, Chrome PRECISA de --no-sandbox (roda como root) e
--disable-dev-shm-usage (evita crash por /dev/shm limitado).
"""
import os

def patch_chrome():
    """Aplica monkey-patch no undetected_chromedriver para adicionar flags Docker."""
    try:
        import undetected_chromedriver as uc
        _original_init = uc.Chrome.__init__

        def _patched_init(self, *args, **kwargs):
            options = kwargs.get("options") or (args[0] if args else None)
            if options is None:
                options = uc.ChromeOptions()
                kwargs["options"] = options

            # Adicionar flags essenciais para Docker/root
            existing_args = set(options.arguments)
            for flag in ["--no-sandbox", "--disable-dev-shm-usage"]:
                if flag not in existing_args:
                    options.add_argument(flag)

            # Remover version_main hardcoded (deixar auto-detectar)
            if "version_main" in kwargs and kwargs["version_main"]:
                del kwargs["version_main"]

            _original_init(self, *args, **kwargs)

        uc.Chrome.__init__ = _patched_init
    except ImportError:
        pass


# Auto-aplicar SEMPRE (--no-sandbox nao faz mal fora do Docker)
patch_chrome()
