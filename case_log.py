"""このツールで作成した下書きの記録（本音メモ・ストレス度など）をPC内に保存する

本音メモは保護者に送るメールには含めず、このファイルにだけ残します。
data/ フォルダは .gitignore 済みです。
"""
import json
import os
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(__file__).parent / "data" / "case_log.jsonl"


def is_ephemeral() -> bool:
    """Cloud Run 上ではファイルに残しても消えるうえ、利用者どうしで共有されてしまうため保存しない"""
    return bool(os.environ.get("K_SERVICE"))


def make_record(draft_id: str, subject: str, body: str, anger_score: int, memo: str | None) -> dict:
    return {
        "draft_id": draft_id,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "subject": subject,
        "body": body,
        "anger_score": anger_score,
        "memo": memo,
    }


def append_case(record: dict) -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_cases() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    with LOG_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
