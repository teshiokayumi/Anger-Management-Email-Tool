import base64
from datetime import date
from typing import get_args

import pandas as pd
import streamlit as st
from pydantic import BaseModel, Field

import case_log
import gemini_client
import issue_agent
import report_builder
from gmail_client import create_gmail_draft
from sample_data import SAMPLE_CASES


# ==========================================
# 1. メール文面の生成（Gemini）
# ==========================================
class MailSuggestion(BaseModel):
    anger_score: int = Field(ge=0, le=100, description="教員のメモから推測される怒りやストレスの度合い")
    advice: str = Field(description="先生への労いと、少し時間を置くことを推奨する短いアドバイス")
    subject: str = Field(description="提案するメールの件名")
    body: str = Field(description="保護者宛てのメール本文")


def call_gemini_api(memo: str) -> dict:
    """先生の感情メモを推敲し、分析結果とメール文面を返す"""
    prompt = f"""あなたは教育現場で働く教員をサポートする、優秀なコミュニケーション・アシスタントです。
教員が直面する保護者対応において、感情的になりそうな場面でも、冷静かつ専門的で、保護者との信頼関係を損なわないメールの文面を作成するのがあなたの役割です。

以下の【教員のメモ（本音）】を元に、分析とメール文面の作成を行ってください。

【作成時の条件】
1. 丁寧でプロフェッショナルな言葉遣い（正しい敬語・謙譲語）を使用すること。
2. 相手の心情に寄り添う「クッション言葉（恐れ入りますが、あいにくですが、等）」を適切に交えること。
3. 感情的な表現、皮肉、相手を責めるような表現は完全に排除し、事実を客観的に伝えること。
4. 学校側として譲れない方針やルールは、角が立たないようにしつつも明確に伝えること。

【教員のメモ（本音）】
{memo}
"""
    return gemini_client.generate_structured(prompt, MailSuggestion).model_dump()


# ==========================================
# 2. Streamlit UI構築
# ==========================================
st.set_page_config(page_title="アンガーマネジメントツール", layout="centered")


def set_background(image_file):
    with open(image_file, "rb") as file:
        encoded_string = base64.b64encode(file.read()).decode()
    css = f"""
    <style>
    .stApp {{
        background-image: url(data:image/png;base64,{encoded_string});
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }}
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


try:
    set_background('illut.png')
except Exception as e:
    st.warning("背景画像が見つかりませんでした。ファイル名が 'illut.png' になっているか確認してください。")

# --- APIキー（環境変数 GEMINI_API_KEY / .streamlit/secrets.toml / 画面入力 のいずれか） ---
with st.sidebar:
    st.header("⚙️ 設定")
    api_key_input = st.text_input("Gemini APIキー", type="password",
                                  help="環境変数 GEMINI_API_KEY を設定済みなら空欄のままで大丈夫です。")
try:
    api_key = api_key_input or st.secrets.get("GEMINI_API_KEY")
except Exception:
    api_key = api_key_input
if api_key and st.session_state.get('api_key') != api_key:
    gemini_client.set_api_key(api_key)
    st.session_state['api_key'] = api_key

st.title("🛡️ 教員向け アンガーマネジメントツール")
tab_mail, tab_agent = st.tabs(["✉️ メールを書く", "🧭 課題を見つけて相談資料をつくる"])

# ==========================================
# タブ1：メール作成（アンガーマネジメント → 下書き保存）
# ==========================================
with tab_mail:
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
                    st.session_state['result'] = call_gemini_api(teacher_memo)
                    st.session_state['memo'] = teacher_memo
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
        keep_memo = st.checkbox("本音メモとストレス度を、課題分析用にこのPC内へ記録する（保護者には送られません）",
                                value=True)

        if st.button("Gmailの下書きに保存する"):
            try:
                with st.spinner("Gmailに下書きを保存中..."):
                    draft_id = create_gmail_draft(edited_subject, edited_body)
                    case_log.append_case(draft_id, edited_subject, edited_body, score,
                                         st.session_state.get('memo') if keep_memo else None)
                    st.success("✅ Gmailの下書きに保存しました！ブラウザでGmailを開いて確認してください。")
            except Exception as e:
                st.error(f"下書き保存エラーが発生しました: {e}")

# ==========================================
# タブ2：課題分析エージェント → 学年主任との打ち合わせ資料
# ==========================================
def render_agent_result(result: issue_agent.AgentResult, run_id: int, grade: str, author: str):
    stats = result.stats
    charts = st.session_state['agent_charts']

    st.subheader("📋 概要")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("保護者対応", f"{stats['total']}件")
    c2.metric("平均ストレス度", stats['avg_stress'])
    c3.metric(f"ストレス{issue_agent.HIGH_STRESS}以上", f"{stats['high_stress']}件")
    c4.metric("学年で共有すべき", f"{stats['escalation']}件")
    repeat = "、".join(f"{k} {v}件" for k, v in stats['repeat_parents'].items()) or "なし"
    st.caption(f"{issue_agent.AFTER_HOURS_START}時以降・{issue_agent.AFTER_HOURS_END}時前に作成：{stats['after_hours']}件　"
               f"／　複数回やりとりのある保護者：{repeat}"
               + (f"　／　保護者対応と無関係な下書き {result.skipped} 件は除外" if result.skipped else ""))
    summary = st.text_area("全体の要約（編集できます）", value=result.analysis.overall_summary,
                           height=120, key=f"summary_{run_id}")

    st.subheader("📊 可視化")
    t1, t2, t3 = st.tabs(["相談内容の分類", "ストレス度の推移", "課題の優先度マップ"])
    t1.image(charts['category'])
    t2.image(charts['stress'])
    t3.image(charts['matrix'])

    st.subheader("🔍 見えてきた課題")
    for i, issue in enumerate(result.analysis.issues, 1):
        with st.container(border=True):
            st.markdown(f"**課題{i}：{issue.title}**　`緊急度 {issue.urgency}` `影響 {issue.impact}`")
            st.write(issue.description)
            st.caption(f"考えられる原因：{issue.root_cause}　／　根拠：{'、'.join(issue.evidence_case_ids)}")

    st.subheader("🧭 対応アプローチ案（編集できます）")
    st.caption("AIの案をたたき台に、実際に動ける内容へ直してから資料にしましょう。行の追加・削除もできます。")
    approach_df = pd.DataFrame([a.model_dump() for a in result.plan.approaches],
                               columns=["issue_no", "action", "owner", "timeframe", "expected_effect"])
    edited_df = st.data_editor(
        approach_df, key=f"approaches_{run_id}", hide_index=True, num_rows="dynamic", width="stretch",
        column_config={
            "issue_no": st.column_config.NumberColumn("課題", min_value=1, max_value=len(result.analysis.issues),
                                                      step=1, width="small"),
            "action": st.column_config.TextColumn("取り組み", width="large"),
            "owner": st.column_config.SelectboxColumn("担当", options=list(get_args(issue_agent.Owner))),
            "timeframe": st.column_config.SelectboxColumn("時期", options=list(get_args(issue_agent.Timeframe))),
            "expected_effect": st.column_config.TextColumn("期待される効果"),
        },
    )
    approaches = [
        {**row, "issue_no": int(row["issue_no"]) if pd.notna(row["issue_no"]) else 0,
         "owner": row["owner"] or "", "timeframe": row["timeframe"] or "", "expected_effect": row["expected_effect"] or ""}
        for row in edited_df.to_dict("records") if row.get("action")
    ]

    st.subheader("🙋 学年主任に相談したいこと（編集できます）")
    consultation_text = st.text_area("1行に1項目", value="\n".join(result.plan.consultation_points),
                                     height=140, key=f"consultation_{run_id}")
    consultation = [line.strip() for line in consultation_text.splitlines() if line.strip()]

    st.subheader("🌱 担任の負担について")
    st.info(f"{result.analysis.stress_trend}\n\n{result.plan.teacher_care}")

    with st.expander("案件一覧（氏名は匿名化済み）"):
        st.dataframe(pd.DataFrame([{
            "ID": c["case_id"], "日時": f"{c['created_at']:%m/%d %H:%M}", "分類": c["category"],
            "相手": c["parent_label"], "概要": c["summary"], "緊急度": c["urgency"],
            "ストレス度": c["stress"], "共有": "要" if c["needs_escalation"] else "", "状態": c["status"],
        } for c in result.cases]), hide_index=True, width="stretch")

    st.subheader("📄 打ち合わせ資料をダウンロード")
    args = (summary, approaches, consultation, author, grade)
    d1, d2 = st.columns(2)
    d1.download_button("Word資料（.docx）", type="primary", width="stretch",
                       data=report_builder.build_docx(result, charts, *args),
                       file_name=f"保護者対応_相談資料_{date.today():%Y%m%d}.docx",
                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    d2.download_button("テキスト（Markdown）", width="stretch",
                       data=report_builder.build_markdown(result, *args),
                       file_name=f"保護者対応_相談資料_{date.today():%Y%m%d}.md", mime="text/markdown")


with tab_agent:
    st.write("Gmailに貯まった下書きをエージェントが読み解き、**課題の発見 → 可視化 → アプローチの立案 → "
             "学年主任との打ち合わせ資料づくり** までを行います。")
    st.caption("① 下書きを集める　② 1件ずつ読み解く（氏名は匿名化）　③ 集計する　④ 共通する課題を探す　⑤ アプローチを考える")

    source = st.radio("分析する下書き", ["Gmailの下書き", "サンプルデータ（デモ用）"], horizontal=True)
    if source == "Gmailの下書き":
        s1, s2 = st.columns(2)
        days = s1.selectbox("対象期間", [7, 14, 30, 60, 90], index=2, format_func=lambda d: f"直近{d}日")
        max_drafts = s2.number_input("読み込む下書きの上限", min_value=5, max_value=100, value=30, step=5)
    m1, m2 = st.columns(2)
    grade = m1.text_input("学年・学級（資料に記載）", placeholder="例: 2年3組")
    author = m2.text_input("作成者（資料に記載）", placeholder="例: 山本")

    if st.button("🤖 エージェントで課題を分析する", type="primary"):
        with st.status("エージェントが作業しています…", expanded=True) as status:
            try:
                raw_cases = SAMPLE_CASES if source != "Gmailの下書き" else issue_agent.collect_cases(days, max_drafts)
                result = issue_agent.run_agent(raw_cases, on_step=st.write)
                st.write("🖼️ グラフを作成しています…")
                st.session_state['agent_charts'] = report_builder.chart_pngs(result)
                st.session_state['agent_result'] = result
                st.session_state['agent_run_id'] = st.session_state.get('agent_run_id', 0) + 1
                status.update(label="分析が完了しました", state="complete", expanded=False)
            except Exception as e:
                status.update(label="分析を中断しました", state="error")
                st.error(f"エラーが発生しました: {e}")

    if 'agent_result' in st.session_state:
        st.divider()
        render_agent_result(st.session_state['agent_result'], st.session_state['agent_run_id'], grade, author)
