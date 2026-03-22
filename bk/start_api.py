#!/usr/bin/env python3
"""
Inicia a API unificada de certidões.

Uso:
    python start_api.py                    # porta 8000
    python start_api.py --port 9000        # porta customizada
    python start_api.py --reload           # auto-reload em dev
    python start_api.py --workers 2        # múltiplos workers

Swagger UI: http://localhost:8000/docs
"""
import sys
import os

# Garantir que o diretório do projeto é o working directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Adicionar ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.main import app

if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="API Unificada de Certidões - PEDRO PROJECT")
    parser.add_argument("--port", type=int, default=8000, help="Porta (default: 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--workers", type=int, default=1, help="Workers (default: 1)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload em dev")
    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════════════════╗
║        API de Certidões - PEDRO PROJECT              ║
║                                                      ║
║  Swagger UI:  http://localhost:{args.port}/docs           ║
║  Health:      http://localhost:{args.port}/health          ║
║  Certidões:   http://localhost:{args.port}/api/v1/certidoes║
║                                                      ║
║  18 endpoints disponíveis                            ║
╚══════════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        "api.main:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
    )
