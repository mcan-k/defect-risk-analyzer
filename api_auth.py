"""
API Key Authentication - Basit header-based auth.
Ileride Forge OAuth'a geciste bu katman degisir, endpoint'ler ayni kalir.
"""

import os
import secrets
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from dotenv import load_dotenv

load_dotenv()

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_or_create_api_key() -> str:
    """
    .env'den API key'i okur. Yoksa yeni uretir ve .env'ye yazar.
    Ilk calistirmada otomatik key olusturur.
    """
    key = os.getenv("DEFECT_API_KEY")
    if key:
        return key

    key = f"dap_{secrets.token_urlsafe(32)}"

    env_path = os.path.join(os.path.dirname(__file__), ".env")
    try:
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"\nDEFECT_API_KEY={key}\n")
        print(f"[AUTH] Yeni API key olusturuldu ve .env'ye yazildi.")
        print(f"[AUTH] Key: {key}")
    except IOError:
        print(f"[AUTH] UYARI: .env'ye yazilamadi. Key: {key}")

    os.environ["DEFECT_API_KEY"] = key
    return key


async def verify_api_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    """Her istekte X-API-Key header'ini dogrular. /health haric."""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header eksik"
        )

    expected_key = get_or_create_api_key()

    if not secrets.compare_digest(api_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Gecersiz API key"
        )

    return api_key
