"""Gemini API 呼び出しの共通処理（google-genai / Interactions API）

APIキーは環境変数 GEMINI_API_KEY（または画面から入力）で設定します。
保護者対応の内容は個人情報を含むため、サーバー側に会話を保存しない（store=False）設定で呼び出します。
"""
import os
from typing import TypeVar

from google import genai
from pydantic import BaseModel

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.7-flash")

T = TypeVar("T", bound=BaseModel)
_client: genai.Client | None = None


def set_api_key(api_key: str) -> None:
    global _client
    _client = genai.Client(api_key=api_key)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client()  # GEMINI_API_KEY / GOOGLE_API_KEY を自動で読む
    return _client


def generate_structured(prompt: str, schema: type[T], system_instruction: str | None = None) -> T:
    """プロンプトを送り、Pydanticモデルの形に沿ったJSONを受け取って検証する"""
    kwargs = {
        "model": MODEL,
        "input": prompt,
        "store": False,
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": schema.model_json_schema(),
        },
    }
    if system_instruction:
        kwargs["system_instruction"] = system_instruction
    interaction = _get_client().interactions.create(**kwargs)
    return schema.model_validate_json(interaction.output_text)
