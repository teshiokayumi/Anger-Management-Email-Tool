import streamlit as st
import json
import google.generativeai as genai

# --- Gmail API連携用モジュール ---
import os.path
import base64
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ==========================================
# 1. APIキーの設定 (ご自身のAPIキーに書き換えてください)
# ==========================================
GOOGLE_API_KEY = ""
genai.configure(api_key=GOOGLE_API_KEY)

# ==========================================
# 2. Gmail下書き作成関数（一番最初のコードを関数化）
# ==========================================
SCOPES = ['https://www.googleapis.com/auth/gmail.compose']

def create_gmail_draft(subject_text: str, body_text: str):
    creds = None
    # 既存のトークンを読み込む
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # トークンがない・期限切れの場合は再認証
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    # Gmail APIのクライアント作成
    service = build('gmail', 'v1', credentials=creds)

    # メールの内容をセット
    message = EmailMessage()
    message.set_content(body_text)
    message['To'] = '' # 送信先は最初は空欄にしておきます
    message['From'] = 'me'
    message['Subject'] = subject_text

    # エンコードしてAPIに送信
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {'message': {'raw': encoded_message}}
    draft = service.users().drafts().create(userId='me', body=create_message).execute()
    
    return draft['id']

# ==========================================
# 3. Gemini APIを呼び出す関数
# ==========================================
def call_gemini_api(memo: str) -> dict:
    prompt = f"""あなたは教育現場で働く教員をサポートする、優秀なコミュニケーション・アシスタントです。
教員が直面する保護者対応において、感情的になりそうな場面でも、冷静かつ専門的で、保護者との信頼関係を損なわないメールの文面を作成するのがあなたの役割です。

以下の【教員のメモ（本音）】を元に、分析とメール文面の作成を行ってください。

【作成時の条件】
1. 丁寧でプロフェッショナルな言葉遣い（正しい敬語・謙譲語）を使用すること。
2. 相手の心情に寄り添う「クッション言葉（恐れ入りますが、あいにくですが、等）」を適切に交えること。
3. 感情的な表現、皮肉、相手を責めるような表現は完全に排除し、事実を客観的に伝えること。
4. 学校側として譲れない方針やルールは、角が立たないようにしつつも明確に伝えること。

【出力形式】
必ず以下のJSON形式で出力してください。（Markdownのコードブロックは使用しないでください）
{{
  "anger_score": 教員のメモから推測される怒りやストレスの度合い（0〜100の数値）,
  "advice": "先生への労いと、少し時間を置くことを推奨する短いアドバイス",
  "subject": "提案するメールの件名",
  "body": "保護者宛てのメール本文"
}}

【教員のメモ（本音）】
{memo}
"""
    model = genai.GenerativeModel("gemini-3.6-flash")
    
    response = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json"
        )
    )
    return json.loads(response.text)

# ==========================================
# 4. UI構築
# ==========================================
st.set_page_config(page_title="アンガーマネジメントツール", layout="centered")

# --- 背景画像を設定する関数 ---
def set_background(image_file):
    # 画像を読み込んでエンコード
    with open(image_file, "rb") as file:
        encoded_string = base64.b64encode(file.read()).decode()
    
    # CSSを使って背景に設定し、固定（fixed）にする
    css = f"""
    <style>
    .stApp {{
        background-image: url(data:image/png;base64,{encoded_string});
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }}
    /* 文字を読みやすくするため、メインコンテンツ部分に半透明の白い枠を付ける */
    .block-container {{
        background-color: rgba(255, 255, 255, 0.85);
        padding: 2rem;
        border-radius: 15px;
        margin-top: 2rem;
        margin-bottom: 2rem;
    }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)

# 背景画像を適用（illut.png という名前のファイルが同じフォルダにある前提です）
try:
    set_background('illut.png')
except Exception as e:
    st.warning("背景画像が見つかりませんでした。ファイル名が 'illut.png' になっているか確認してください。")

# --- ここから下のUIの中身は今までと同じです ---
st.title("🛡️ 教員向け アンガーマネジメントツール")
st.write("感情のままに書いたメモを、AIが冷静で適切な文面に変換し、Gmailの下書きに保存します。")

st.subheader("1. 本音・メモを入力")
teacher_memo = st.text_area(
    "保護者に伝えたいことや、今の率直な感情を書き出してください。（相手には送信されません）", 
    height=150,
    placeholder="例: また理不尽なクレームが来た。こっちだって忙しいのに..."
)

if st.button("AIで文面を生成・推敲する", type="primary"):
    if teacher_memo:
        with st.spinner("AIが感情を分析し、文面を作成中です..."):
            try:
                result = call_gemini_api(teacher_memo)
                st.session_state['result'] = result
            except Exception as e:
                st.error(f"AIの呼び出しエラーが発生しました: {e}")
    else:
        st.warning("メモを入力してください。")

if 'result' in st.session_state:
    res = st.session_state['result']
    
    st.divider()
    
    st.subheader("2. 分析とアドバイス")
    score = res.get('anger_score', 0)
    
    if score >= 70:
        st.error(f"🔥 現在のストレス度: {score} / 100\n\n{res.get('advice')}")
    elif score >= 40:
        st.warning(f"💦 現在のストレス度: {score} / 100\n\n{res.get('advice')}")
    else:
        st.info(f"🍀 現在のストレス度: {score} / 100\n\n{res.get('advice')}")
        
    st.subheader("3. 生成されたメール文面（編集可能）")
    edited_subject = st.text_input("件名", value=res.get('subject', ''))
    edited_body = st.text_area("本文", value=res.get('body', ''), height=200)
    
    if st.button("Gmailの下書きに保存する"):
        try:
            with st.spinner("Gmailに下書きを保存中..."):
                draft_id = create_gmail_draft(edited_subject, edited_body)
                st.success(f"✅ Gmailの下書きに保存しました！ブラウザでGmailを開いて確認してください。")
        except Exception as e:
            st.error(f"下書き保存エラーが発生しました: {e}")