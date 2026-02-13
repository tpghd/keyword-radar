import os
import json
import requests
from datetime import date, timedelta
import pandas as pd

# ===== 기준 =====
START_DATE = "2026-01-01"

# ===== 너가 원하는 "섹션(그룹)" 구성 =====
GROUPS = {
    "경쟁사 그룹": ["아이코스", "릴하이브리드", "글로전자담배", "레딜전자담배", "하카"],
    "자사 그룹": ["하카", "하카전담", "하카매장", "하카전자담배"],
    "시장 그룹": ["전자담배액상", "편의점전자담배", "궐련형전자담배", "무니코틴전자담배"],
    "H2 그룹": ["하카신제품", "하카H", "하카궐련형", "하카H2", "HAKAH2"],
}

NAVER_CLIENT_ID = os.environ["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])


def fetch_datalab(keyword_list):
    """keywordGroups는 최대 5개라서, 이 함수에는 최대 5개만 넣는 걸 권장."""
    url = "https://openapi.naver.com/v1/datalab/search"
    end_date = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    payload = {
        "startDate": START_DATE,
        "endDate": end_date,
        "timeUnit": "date",
        "keywordGroups": [{"groupName": kw, "keywords": [kw]} for kw in keyword_list],
    }

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json",
    }

    res = requests.post(url, headers=headers, data=json.dumps(payload))
    res.raise_for_status()
    return res.json()


def build_report(data):
    rows = []
    for result in data.get("results", []):
        keyword = result["title"]
        for item in result["data"]:
            rows.append({"keyword": keyword, "date": item["period"], "ratio": item["ratio"]})

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["keyword", "date"])

    last2 = df.groupby("keyword").tail(2)
    pivot = last2.pivot_table(index="keyword", columns="date", values="ratio")
    pivot = pivot.reindex(sorted(pivot.columns), axis=1)

    if pivot.shape[1] < 2:
        raise RuntimeError("비교할 날짜가 2일치 미만입니다. (데이터가 충분한지 확인)")

    d2_col, d1_col = pivot.columns[-2], pivot.columns[-1]

    report = pd.DataFrame({
        "keyword": pivot.index,
        "date_d_2": d2_col.date(),
        "ratio_d_2": pivot[d2_col].values,
        "date_d_1": d1_col.date(),
        "ratio_d_1": pivot[d1_col].values,
    })

    report["diff"] = report["ratio_d_1"] - report["ratio_d_2"]
    report["pct_change"] = report.apply(
        lambda r: (r["diff"] / r["ratio_d_2"] * 100) if r["ratio_d_2"] not in [0, None] else None,
        axis=1
    )
    return report


def make_section_text(title: str, report: pd.DataFrame) -> str:
    def fmt(d):
        d = pd.to_datetime(d)
        return f"{d.month}월 {d.day}일"

    r = report.copy()
    r["ratio_d_2"] = r["ratio_d_2"].round(2)
    r["ratio_d_1"] = r["ratio_d_1"].round(2)
    r["pct_change"] = r["pct_change"].round(0)

    # 키워드 순서 유지(입력한 순서대로 나오게)
    order = {k: i for i, k in enumerate(r["keyword"].tolist())}
    r = r.sort_values("keyword", key=lambda s: s.map(order))

    d2 = fmt(r.iloc[0]["date_d_2"])
    d1 = fmt(r.iloc[0]["date_d_1"])

    lines = []
    lines.append(f"")
    lines.append(f"{d2} 검색 현황")
    for _, row in r.iterrows():
        lines.append(f"{row['keyword']} : {row['ratio_d_2']}")

    lines.append("")
    lines.append(f"{d1} 검색 현황")
    for _, row in r.iterrows():
        pct = row["pct_change"]
        if pd.isna(pct):
            lines.append(f"{row['keyword']} : {row['ratio_d_1']} (변화율 계산 불가)")
        else:
            direction = "증가" if pct >= 0 else "감소"
            lines.append(f"{row['keyword']} : {row['ratio_d_1']} ({abs(int(pct))}% {direction})")

    return "\n".join(lines)


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    resp.raise_for_status()


def main():
    sections = []
    for group_title, keywords in GROUPS.items():
        # 만약 어느 그룹이 6개 이상으로 늘어나면, 여기서 5개씩 쪼개는 로직을 추가하면 됨
        data = fetch_datalab(keywords)
        report = build_report(data)

        # 출력 순서를 입력한 키워드 순서대로 고정
        report["keyword"] = pd.Categorical(report["keyword"], categories=keywords, ordered=True)
        report = report.sort_values("keyword")

        sections.append(make_section_text(group_title, report))

    # 섹션 사이를 구분선으로
    final_text = "\n\n" + ("-" * 22) + "\n\n"
    final_text = final_text.join(sections)

    send_telegram(final_text)


if __name__ == "__main__":
    main()
