"""課題分析エージェント

下書き（＋ツールの記録）を集め、次の順に自律的に処理します。
  1. 収集   : Gmailの下書きと、このツールの記録（本音メモ・ストレス度）を突き合わせる
  2. 読解   : 1件ずつ読み、保護者対応かどうかの判定・分類・匿名化した要約を作る
  3. 集計   : 分類・ストレス度・時間帯・同じ保護者とのやりとり回数などを数える
  4. 課題抽出: 集計と個別の読解結果から、背景にある課題を見つける
  5. 立案   : 課題ごとに、誰が・いつまでに・何をするかのアプローチ案を作る
"""
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Literal

from pydantic import BaseModel, Field

import case_log
import gmail_client
from gemini_client import generate_structured

Category = Literal[
    "成績・評価", "学習指導・宿題", "友人関係・トラブル", "生活指導・きまり",
    "行事・部活動", "連絡・情報共有", "教員の対応への不満", "健康・安全", "その他",
]
Owner = Literal["担任", "学年団", "学年主任", "管理職", "養護教諭・SC・SSW", "学校全体"]
Timeframe = Literal["今週中", "2週間以内", "1か月以内", "学期内"]

HIGH_STRESS = 70
# 19時以降・7時前に作成された下書きを「勤務時間外の対応」として数える
AFTER_HOURS_START, AFTER_HOURS_END = 19, 7


# ---------- AIに返してもらう形 ----------
class CaseInsight(BaseModel):
    is_parent_matter: bool = Field(description="保護者対応に関する下書きなら true。私用・事務連絡など無関係なら false")
    counterpart_name: str = Field(description="宛先の保護者の呼称（例: 佐藤様）。集計のためだけに使う。不明なら空文字")
    category: Category
    summary: str = Field(description="案件の要約（60字以内）。児童生徒・保護者の実名は書かず「生徒」「保護者」と表現する")
    parent_request: str = Field(description="保護者が求めていること（40字以内、実名なし）")
    parent_emotion: int = Field(ge=0, le=100, description="保護者の感情の強さの推定")
    teacher_stress: int = Field(ge=0, le=100, description="教員の負担・ストレスの推定")
    urgency: int = Field(ge=1, le=5, description="対応の緊急度（5が最も緊急）")
    needs_escalation: bool = Field(description="担任だけで抱えず、学年や管理職と共有すべきなら true")
    escalation_reason: str = Field(description="共有すべき理由（不要なら空文字）")
    unresolved_points: list[str] = Field(description="まだ解決していない論点・確認事項")
    background_factors: list[str] = Field(description="背景にありそうな要因（例: 評価基準の説明不足、連絡手段の不統一）")


class Issue(BaseModel):
    title: str = Field(description="課題名（25字以内）")
    description: str = Field(description="何が起きているか（120字以内）")
    root_cause: str = Field(description="考えられる根本原因（80字以内）")
    evidence_case_ids: list[str] = Field(description="根拠となる案件ID（例: C01）")
    urgency: int = Field(ge=1, le=5, description="緊急度（5が最も緊急）")
    impact: int = Field(ge=1, le=5, description="放置した場合の影響の大きさ（5が最大）")


class IssueAnalysis(BaseModel):
    overall_summary: str = Field(description="学年主任が最初に読む全体の要約（200字以内）")
    stress_trend: str = Field(description="担任の負担・ストレスの傾向（120字以内）")
    issues: list[Issue] = Field(description="重要な順に3〜5件")


class Approach(BaseModel):
    issue_no: int = Field(description="対応する課題の番号（1始まり）")
    action: str = Field(description="具体的な取り組み（60字以内）")
    owner: Owner
    timeframe: Timeframe
    expected_effect: str = Field(description="期待される効果（40字以内）")


class ApproachPlan(BaseModel):
    approaches: list[Approach] = Field(description="各課題に1〜3件")
    consultation_points: list[str] = Field(description="学年主任に相談・判断を仰ぎたいこと（3〜5項目、問いかけの形）")
    teacher_care: str = Field(description="担任自身の負担を減らすための提案（120字以内）")


@dataclass
class AgentResult:
    cases: list[dict]
    stats: dict
    analysis: IssueAnalysis
    plan: ApproachPlan
    skipped: int
    period: tuple[date, date]


SYSTEM = (
    "あなたは中学校・小学校の保護者対応と学年経営に詳しい教育コンサルタントです。"
    "担任の先生を責めず、事実と根拠に基づいて、学年として取り組める現実的な提案を行います。"
    "出力には児童生徒・保護者の実名を含めないでください。"
)


# ---------- 1. 収集 ----------
def collect_cases(days: int, max_drafts: int) -> list[dict]:
    """Gmailの下書きとツールの記録を突き合わせて、分析対象の一覧を作る"""
    since = date.today() - timedelta(days=days)
    logs = {r["draft_id"]: r for r in case_log.load_cases()}

    cases = []
    for draft in gmail_client.list_drafts(max_drafts, since):
        log = logs.pop(draft["draft_id"], {})
        cases.append({**draft, "memo": log.get("memo"), "anger_score": log.get("anger_score"),
                      "status": "下書き保存中"})

    # 送信・削除などで下書きから消えたものは、ツールの記録から補う
    for log in logs.values():
        saved_at = datetime.fromisoformat(log["saved_at"])
        if saved_at.date() >= since:
            cases.append({"draft_id": log["draft_id"], "created_at": saved_at, "to": "",
                          "subject": log["subject"], "body": log["body"], "memo": log.get("memo"),
                          "anger_score": log.get("anger_score"), "status": "ツールの記録から"})
    return cases


# ---------- 2. 読解 ----------
def read_case(case: dict) -> CaseInsight:
    memo = f"\n【教員の本音メモ（保護者には送っていない）】\n{case['memo']}\n" if case.get("memo") else ""
    prompt = f"""以下は教員のメール下書きです。保護者対応の案件として読み解いてください。

【作成日時】{case['created_at']:%Y-%m-%d %H:%M}
【件名】{case['subject']}
【本文】
{case['body']}
{memo}"""
    return generate_structured(prompt, CaseInsight, SYSTEM)


def _parent_labels(names: list[str]) -> list[str]:
    """同じ保護者を「保護者A」「保護者B」…と匿名のラベルにそろえる"""
    labels: dict[str, str] = {}
    result = []
    for name in names:
        key = re.sub(r"(様|さん|殿|保護者|\s)", "", name)
        if not key:
            result.append("不明")
            continue
        if key not in labels:
            labels[key] = f"保護者{chr(ord('A') + len(labels))}" if len(labels) < 26 else f"保護者{len(labels) + 1}"
        result.append(labels[key])
    return result


# ---------- 3. 集計 ----------
def _is_after_hours(dt: datetime) -> bool:
    return dt.hour >= AFTER_HOURS_START or dt.hour < AFTER_HOURS_END


def aggregate(cases: list[dict]) -> dict:
    parent_counts = Counter(c["parent_label"] for c in cases if c["parent_label"] != "不明")
    stresses = [c["stress"] for c in cases]
    return {
        "total": len(cases),
        "avg_stress": round(sum(stresses) / len(stresses)) if stresses else 0,
        "high_stress": sum(s >= HIGH_STRESS for s in stresses),
        "escalation": sum(c["needs_escalation"] for c in cases),
        "after_hours": sum(c["after_hours"] for c in cases),
        "repeat_parents": {k: v for k, v in parent_counts.most_common() if v >= 2},
        "category_counts": dict(Counter(c["category"] for c in cases).most_common()),
    }


def _cases_for_prompt(cases: list[dict]) -> str:
    keys = ["case_id", "created_at", "category", "summary", "parent_request", "parent_label", "urgency",
            "stress", "needs_escalation", "unresolved_points", "background_factors", "after_hours"]
    return "\n".join(json.dumps({k: str(c[k]) if k == "created_at" else c[k] for k in keys}, ensure_ascii=False)
                     for c in cases)


# ---------- 4. 課題抽出 ----------
def find_issues(cases: list[dict], stats: dict) -> IssueAnalysis:
    prompt = f"""ある担任が作成した保護者対応メールの下書きを1件ずつ読み解いた結果と、その集計です。
個別の案件の対応ではなく、複数の案件に共通する「背景にある課題」を見つけてください。
（例: 学年の方針が保護者に伝わっていない、特定の保護者との関係が長期化している、勤務時間外の対応が常態化している など）
各課題には根拠となる案件IDを必ず挙げてください。

【集計】
{json.dumps(stats, ensure_ascii=False)}
※ stress は担任のストレス度（0〜100）、after_hours は{AFTER_HOURS_START}時以降・{AFTER_HOURS_END}時前に作成された下書き

【案件一覧】
{_cases_for_prompt(cases)}
"""
    return generate_structured(prompt, IssueAnalysis, SYSTEM)


# ---------- 5. アプローチ立案 ----------
def plan_approaches(analysis: IssueAnalysis, stats: dict) -> ApproachPlan:
    issues = "\n".join(f"課題{i}: {it.title} — {it.description}（原因: {it.root_cause}／緊急度{it.urgency}・影響度{it.impact}）"
                       for i, it in enumerate(analysis.issues, 1))
    prompt = f"""担任が学年主任と打ち合わせをするための資料を作ります。
次の課題それぞれについて、担任ひとりで抱え込まず、学年・学校として取り組めるアプローチを考えてください。
「誰が」「いつまでに」「何をするか」が明確で、明日から動ける具体的な内容にしてください。
また、打ち合わせで学年主任に相談・判断してほしいことを、問いかけの形でまとめてください。

【全体の要約】{analysis.overall_summary}
【担任の負担の傾向】{analysis.stress_trend}
【集計】{json.dumps(stats, ensure_ascii=False)}

【課題】
{issues}
"""
    return generate_structured(prompt, ApproachPlan, SYSTEM)


# ---------- 実行 ----------
def run_agent(raw_cases: list[dict], on_step: Callable[[str], None] = print, workers: int = 4) -> AgentResult:
    if not raw_cases:
        raise ValueError("分析できる下書きが見つかりませんでした。")
    raw_cases = sorted(raw_cases, key=lambda c: c["created_at"])
    on_step(f"📥 下書き {len(raw_cases)} 件を集めました")

    on_step("📖 1件ずつ読み解いています…")
    insights: list[CaseInsight | None] = [None] * len(raw_cases)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(read_case, c): i for i, c in enumerate(raw_cases)}
        for done, future in enumerate(as_completed(futures), 1):
            insights[futures[future]] = future.result()
            on_step(f"　読解 {done}/{len(raw_cases)} 件")

    pairs = [(raw, ins) for raw, ins in zip(raw_cases, insights) if ins.is_parent_matter]
    skipped = len(raw_cases) - len(pairs)
    if skipped:
        on_step(f"🗂️ 保護者対応と関係のない下書き {skipped} 件を除外しました")
    if not pairs:
        raise ValueError("保護者対応に関する下書きが見つかりませんでした。")

    labels = _parent_labels([ins.counterpart_name for _, ins in pairs])
    cases = []
    for i, ((raw, ins), label) in enumerate(zip(pairs, labels), 1):
        cases.append({
            "case_id": f"C{i:02d}",
            "created_at": raw["created_at"],
            "status": raw["status"],
            "parent_label": label,
            # ツールで記録したストレス度があれば実測値を優先し、なければAIの推定値を使う
            "stress": raw["anger_score"] if raw.get("anger_score") is not None else ins.teacher_stress,
            "after_hours": _is_after_hours(raw["created_at"]),
            **ins.model_dump(exclude={"is_parent_matter", "counterpart_name", "teacher_stress"}),
        })

    on_step("📊 分類・ストレス度・時間帯を集計しています…")
    stats = aggregate(cases)

    on_step("🔍 案件に共通する課題を探しています…")
    analysis = find_issues(cases, stats)

    on_step("🧭 課題ごとのアプローチを考えています…")
    plan = plan_approaches(analysis, stats)

    period = (cases[0]["created_at"].date(), cases[-1]["created_at"].date())
    on_step("✅ 分析が完了しました")
    return AgentResult(cases, stats, analysis, plan, skipped, period)
