# Cloud Run へのデプロイ手順（ハッカソン向け）

プロジェクト: `email-anger-management-tool`（プロジェクト番号 747422260737）／リージョン: `asia-northeast1`

APIキーやOAuthクライアントは **Secret Manager** に置き、コードには一切書きません。

---

## 0. 準備（最初の1回だけ）

```bash
gcloud auth login
```

```bash
gcloud config set project email-anger-management-tool
```

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com generativelanguage.googleapis.com gmail.googleapis.com
```

## 1. Gemini APIキーを Secret Manager に登録

`YOUR_GEMINI_API_KEY` を実際のキーに置き換えて実行します。**PowerShell の場合**（改行が混ざらないよう、いったんファイルに書き出します）:

```powershell
[IO.File]::WriteAllText("$env:TEMP\gemini-key.txt", "YOUR_GEMINI_API_KEY"); gcloud secrets create gemini-api-key --data-file="$env:TEMP\gemini-key.txt"; Remove-Item "$env:TEMP\gemini-key.txt"
```

Git Bash などの場合:

```bash
printf 'YOUR_GEMINI_API_KEY' | gcloud secrets create gemini-api-key --data-file=-
```

```bash
gcloud secrets add-iam-policy-binding gemini-api-key --member=serviceAccount:747422260737-compute@developer.gserviceaccount.com --role=roles/secretmanager.secretAccessor
```

## 2. 1回目のデプロイ（URLを確定させる）

```bash
gcloud run deploy anger-management-tool --source . --region asia-northeast1 --allow-unauthenticated --memory 1Gi --cpu 1 --timeout 3600 --max-instances 1 --set-secrets GEMINI_API_KEY=gemini-api-key:latest
```

表示されたURLを控えます（次のコマンドでも確認できます）。

```bash
gcloud run services describe anger-management-tool --region asia-northeast1 --format="value(status.url)"
```

この時点で **メール生成とサンプルデータの課題分析** は動きます。Gmail連携は3〜4の設定後に使えます。

## 3. OAuth の設定（Cloud Console での作業）

1. **OAuth同意画面**（APIとサービス → OAuth同意画面）
   - ユーザーの種類：外部／公開ステータス：テスト
   - スコープに `https://www.googleapis.com/auth/gmail.compose` を追加
   - **テストユーザー**に、デモで使うGoogleアカウント（自分・審査員）を追加
   - テスト中は「このアプリは確認されていません」と出ます。「詳細」→「（安全でないページ）に移動」で進めます
2. **認証情報 → 認証情報を作成 → OAuth クライアント ID**
   - 種類：**ウェブ アプリケーション**
   - **承認済みのリダイレクト URI**：手順2で控えたURLを**そのまま**貼り付け
     （例 `https://anger-management-tool-xxxxxxxx.a.run.app`）
   - 作成後、JSONをダウンロード

## 4. OAuthクライアントを登録して再デプロイ

ダウンロードしたJSONのパスと、手順2のURLを置き換えて実行します。

```bash
gcloud secrets create oauth-client --data-file="C:/Users/User/Downloads/client_secret_xxx.json"
```

```bash
gcloud secrets add-iam-policy-binding oauth-client --member=serviceAccount:747422260737-compute@developer.gserviceaccount.com --role=roles/secretmanager.secretAccessor
```

```bash
gcloud run services update anger-management-tool --region asia-northeast1 --set-secrets GEMINI_API_KEY=gemini-api-key:latest,GOOGLE_OAUTH_CLIENT_JSON=oauth-client:latest --set-env-vars OAUTH_REDIRECT_URI=https://anger-management-tool-xxxxxxxx.a.run.app
```

`OAUTH_REDIRECT_URI` は、手順3で登録したリダイレクトURIと**1文字も違わない**必要があります（末尾の `/` の有無も含む）。

## 5. 動作確認

1. URLを開く → 左の「Gmail連携」→「Googleでログイン」
2. テストユーザーのアカウントで許可 → 「接続済み」になる
3. メールを書く → Gmailの下書きに保存 → 実際のGmailで確認
4. 課題分析タブ →「Gmailの下書き」→ エージェント実行 → Word資料をダウンロード

## コードを直した後の再デプロイ

```bash
gcloud run deploy anger-management-tool --source . --region asia-northeast1
```

（環境変数とシークレットの設定は引き継がれます）

---

## 補足

- **`--max-instances 1` は外さないでください。** ログインの途中経過（state と PKCE）をサーバーのメモリに持っているため、
  インスタンスが増えるとログインに失敗することがあります。増やす場合は `--session-affinity` も付けてください。
- **本音メモの記録は保存されません。** Cloud Run ではファイルが消える上に利用者どうしで混ざるため、
  ブラウザのセッション内だけに保持します（`case_log.is_ephemeral()`）。ローカル実行時は従来どおり `data/` に保存します。
- **公開範囲**：`--allow-unauthenticated` はURLを知っていれば誰でも開けます。ただしGmailは各自のログインが必要で、
  OAuth同意画面がテストモードのうちはテストユーザー以外はログインできません。
- **コールドスタート**：初回アクセスは10秒ほどかかります。発表直前に一度アクセスして温めておくか、
  `--min-instances 1` を付けてください（少し課金されます）。
- `credentials.json` `token.json` `data/` は `.dockerignore` でイメージに含めていません。
