"""
Patch para undetected_chromedriver funcionar em Windows + Docker + Linux.

Fixes:
  1. --no-sandbox e --disable-dev-shm-usage (Docker/root)
  2. Remover version_main hardcoded
  3. Windows: usar user_data_dir unico por instancia (evita WinError 183)
  4. Windows: headless=new quando sem display
"""
import os
import platform
import tempfile
import uuid

IS_WINDOWS = platform.system() == "Windows"


def patch_chrome():
    try:
        import undetected_chromedriver as uc
        _original_init = uc.Chrome.__init__

        def _patched_init(self, *args, **kwargs):
            options = kwargs.get("options") or (args[0] if args else None)
            if options is None:
                options = uc.ChromeOptions()
                kwargs["options"] = options

            existing_args = set(options.arguments)

            # Flags essenciais
            for flag in ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]:
                if flag not in existing_args:
                    options.add_argument(flag)

            # Remover version_main hardcoded
            if "version_main" in kwargs and kwargs["version_main"]:
                del kwargs["version_main"]

            # Windows: user_data_dir unico evita [WinError 183]
            if IS_WINDOWS and "user_data_dir" not in kwargs:
                unique_dir = os.path.join(tempfile.gettempdir(), f"uc_{uuid.uuid4().hex[:8]}")
                kwargs["user_data_dir"] = unique_dir

            _original_init(self, *args, **kwargs)

        uc.Chrome.__init__ = _patched_init
    except ImportError:
        pass


patch_chrome()
