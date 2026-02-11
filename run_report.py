import os
import json
import requests
from datetime import date, timedelta
import pandas as pd

# ===== 설정 =====
START_DATE = "2026-01-01"
KEYWORDS = ["전자담배", "하카전담", "하카", "하카전자담배", "하카매장", "레딜전자담배", "전자담배 액상", "무니코틴 전자담배", "편의점 전자담배", "전자담배 세금", "아이코스", "릴하이브리드"]

NAVER_CLIENT_ID = os.environ["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])


def fetch_datalab():
    url = "https://openapi.naver.com/v1/datalab/search"
    end_date = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    payload = {
        "startDate": START_DATE,
        "endDate": end_date,
        "timeUnit": "date",
        "keywordGroups": [{"groupName": kw, "keywords": [kw]} for kw in KEYWORDS],
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


def make_report_text(report: pd.DataFrame) -> str:
    def fmt(d):
        d = pd.to_datetime(d)
        return f"{d.month}월 {d.day}일"

    r = report.copy()
    r["ratio_d_2"] = r["ratio_d_2"].round(2)
    r["ratio_d_1"] = r["ratio_d_1"].round(2)
    r["pct_change"] = r["pct_change"].round(0)

    d2 = fmt(r.iloc[0]["date_d_2"])
    d1 = fmt(r.iloc[0]["date_d_1"])

    lines = []
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
    data = fetch_datalab()
    report = build_report(data)
    text = make_report_text(report)
    send_telegram(text)


if __name__ == "__main__":
    main()
