"""Gmail API：認証・下書きの保存・下書きの読み込み"""
import base64
import os.path
import re
from datetime import date, datetime
from email.message import EmailMessage

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']


def get_credentials():
    """Gmail APIの認証情報を取得・更新する"""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds


def _service():
    return build('gmail', 'v1', credentials=get_credentials())


def create_gmail_draft(subject_text: str, body_text: str) -> str:
    """Gmailに下書きを保存し、下書きIDを返す"""
    message = EmailMessage()
    message.set_content(body_text)
    message['To'] = ''
    message['From'] = 'me'
    message['Subject'] = subject_text

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {'message': {'raw': encoded_message}}
    draft = _service().users().drafts().create(userId='me', body=create_message).execute()
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


def list_drafts(max_results: int = 30, since: date | None = None) -> list[dict]:
    """下書きを本文ごと取得する。戻り値は新しい順の dict のリスト"""
    service = _service()
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
