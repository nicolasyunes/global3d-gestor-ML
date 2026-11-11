"""Conexión compartida a Supabase (REST) y a la API de MercadoLibre."""
import json
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ML_API = "https://api.mercadolibre.com"
SITE = "MLA"

if not SUPABASE_URL or not SERVICE_KEY:
    sys.exit("Falta SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY en .env")

# Claves nuevas (sb_secret_...) van solo en "apikey"; la service_role legacy (JWT) también en Authorization.
_SB_HEADERS = {"apikey": SERVICE_KEY, "Content-Type": "application/json"}
if not SERVICE_KEY.startswith("sb_"):
    _SB_HEADERS["Authorization"] = f"Bearer {SERVICE_KEY}"


def sb(method, path, params=None, body=None, prefer=None):
    """Llamada a PostgREST. path ej: 'shop_families'."""
    headers = dict(_SB_HEADERS)
    if prefer:
        headers["Prefer"] = prefer
    r = requests.request(method, f"{SUPABASE_URL}/rest/v1/{path}", headers=headers,
                         params=params, json=body, timeout=30)
    if r.status_code >= 400:
        sys.exit(f"Supabase {r.status_code}: {r.text}")
    return r.json() if r.text else None


_token_cache = None


def ml_token(force=False):
    global _token_cache
    if _token_cache and not force:
        return _token_cache
    r = requests.post(f"{SUPABASE_URL}/functions/v1/ml-token" + ("?force=1" if force else ""),
                      headers=_SB_HEADERS, timeout=30)
    data = r.json()
    if r.status_code != 200:
        sys.exit(f"No se pudo obtener token de ML: {data}")
    _token_cache = data
    return data


def ml(method, path, params=None, body=None, files=None, auth=True):
    headers = {}
    if auth:
        headers["Authorization"] = f"Bearer {ml_token()['access_token']}"
    r = requests.request(method, f"{ML_API}{path}", headers=headers, params=params,
                         json=body if files is None else None, files=files, timeout=60)
    if r.status_code == 401 and auth:  # token revocado/vencido: forzar renovación una vez
        headers["Authorization"] = f"Bearer {ml_token(force=True)['access_token']}"
        r = requests.request(method, f"{ML_API}{path}", headers=headers, params=params,
                             json=body if files is None else None, files=files, timeout=60)
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text}
    return r.status_code, data


def out(obj):
    """Salida compacta (JSON en una línea por objeto) para no gastar tokens."""
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str))
