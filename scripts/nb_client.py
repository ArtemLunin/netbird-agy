import os
import json
from datetime import datetime
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("NETBIRD_URL", "").rstrip("/") + "/api"
TOKEN = os.getenv("NETBIRD_TOKEN", "")

HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

def request(method: str, endpoint: str, payload: dict | None = None):
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    resp = requests.request(method, url, headers=HEADERS, json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json() if resp.text else None

def backup_resource(name: str, data: dict | list):
    Path("backups").mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path("backups") / f"{name}_{ts}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)
