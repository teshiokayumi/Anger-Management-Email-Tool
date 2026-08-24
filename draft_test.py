import os.path
import base64
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# 今回必要な権限（下書きの作成など、メールの作成権限）
SCOPES = ['https://www.googleapis.com/auth/gmail.compose']

def main():
    creds = None
    # 以前に認証したことがある場合は token.json から読み込む
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # 認証情報がない（初回）または期限切れの場合はログイン処理
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # ここでさっきダウンロードした credentials.json を使います
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # 次回以降のために認証情報を保存
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        # Gmail API クライアントの構築
        service = build('gmail', 'v1', credentials=creds)

        # 1. メールの文面を作成（AIが生成する想定の部分）
        message = EmailMessage()
        message.set_content("〇〇様\n\nお世話になっております。\nご意見ありがとうございます。明日改めて事実確認の上、ご連絡いたします。")
        message['To'] = 'test-parent@example.com' # 送信先（下書きなのでダミーでOK）
        message['From'] = 'me' # 自分のアドレス（'me'で自動認識されます）
        message['Subject'] = '【要確認】明日のご連絡について'

        # 2. Gmail API用にエンコード
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {'message': {'raw': encoded_message}}

        # 3. 下書きとして保存
        draft = service.users().drafts().create(userId='me', body=create_message).execute()
        print(f"成功！下書きが作成されました。Draft ID: {draft['id']}")

    except HttpError as error:
        print(f"エラーが発生しました: {error}")

if __name__ == '__main__':
    main()