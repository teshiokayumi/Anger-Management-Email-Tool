"""Gmail API：下書きの保存・読み込み（認証は gmail_auth.py）"""
import base64
import re
from datetime import date, datetime
from email.message import EmailMessage

from googleapiclient.discovery import build


def create_gmail_draft(creds, subject_text: str, body_text: str) -> str:
    """Gmailに下書きを保存し、下書きIDを返す"""
    message = EmailMessage()
    message.set_content(body_text)
    message['To'] = ''
    message['From'] = 'me'
    message['Subject'] = subject_text

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {'message': {'raw': encoded_message}}
    draft = build('gmail', 'v1', credentials=creds).users().drafts().create(
        userId='me', body=create_message).execute()
    return draft['id']


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode('utf-8', errors='replace')


def _extract_text(payload: dict) -> str:
    """メール本文（text/plain優先、なければHTMLからタグを除去）を取り出す"""
    plain, html = [], []

    def walk(part):
        mime = part.get('mimeType', '')
        data = part.get('body', {}).get('data')
        if data and mime == 'text/plain':
            plain.append(_decode(data))
        elif data and mime == 'text/html':
            html.append(_decode(data))
        for child in part.get('parts', []):
            walk(child)

    walk(payload)
    if plain:
        return '\n'.join(plain).strip()
    if html:
        text = re.sub(r'<br\s*/?>|</p>', '\n', '\n'.join(html), flags=re.I)
        return re.sub(r'<[^>]+>', '', text).strip()
    return ''


def list_drafts(creds, max_results: int = 30, since: date | None = None) -> list[dict]:
    """下書きを本文ごと取得する。戻り値は新しい順の dict のリスト"""
    service = build('gmail', 'v1', credentials=creds)
    query = f"after:{since:%Y/%m/%d}" if since else None
    results = service.users().drafts().list(userId='me', maxResults=max_results, q=query).execute()

    drafts = []
    for item in results.get('drafts', []):
        detail = service.users().drafts().get(userId='me', id=item['id'], format='full').execute()
        message = detail.get('message', {})
        payload = message.get('payload', {})
        headers = {h['name'].lower(): h['value'] for h in payload.get('headers', [])}
        drafts.append({
            'draft_id': item['id'],
            'created_at': datetime.fromtimestamp(int(message.get('internalDate', 0)) / 1000),
            'to': headers.get('to', ''),
            'subject': headers.get('subject', ''),
            'body': _extract_text(payload) or message.get('snippet', ''),
        })
    return drafts
