import json
from pathlib import Path
from fastapi import APIRouter

router = APIRouter(tags=["meta"])

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.json"


@router.get("/config")
async def get_config():
    return json.loads(CONFIG_PATH.read_text())
