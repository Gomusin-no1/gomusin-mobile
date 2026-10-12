"""건별 '점검 항목'과 '예상 원인' 만들기.

화면 요구사항(2026-10): 고객을 누르면 "무엇이 틀렸고, 맞는 값은 무엇이고, 무엇 때문으로 예상되는지" 보여준다.
큰 틀은 ① 정책 단가(리베이트) ② 부가서비스 유치 ③ 개통 조건 ④ 정책 추가금.

정산서 상세 항목(매장 기준 금액: + 받음 / − 차감)을 이름으로 분류하고,
차이 금액과 정확히 맞아떨어지는 항목 조합을 찾아 원인으로 제시한다.
"""
import re
from itertools import combinations

from .common import fmt_amt

# 판매일보 메모(구두내용/부가추가/차감내역)는 '항목 +3' 처럼 만원 단위로 적는다.
MEMO_RE = re.compile(r"([+\-−])\s*(\d+(?:\.\d+)?)\s*(?:만)?\s*\)?\s*$")
MEMO_SKIP = ("중고폰", "페이백", "사은품", "현금", "퀵")
AFFINITY = [(("보험", "안심"), ("보험",)), (("VAS", "교보", "V컬", "벨링", "구글", "부가"), ("VAS", "SET")),
            (("필수팩",), ("필수팩",)), (("소급",), ("소급",)), (("스팟",), ("스팟",)), (("케어",), ("케어",)),
            (("OTT", "티빙"), ("OTT",)), (("유통망",), ("유통망", "별도", "기타추가")), (("별도",), ("별도",))]

CATEGORIES = [
    ("부가서비스", ("부가", "VAS", "보험", "필수팩", "OTT", "SET", "케어", "구독", "미유치", "원스톱", "인터넷팩")),
    ("개통 조건", ("유통망지원금10", "U+ONE", "로그인", "축소", "선약", "33미만", "기변차감", "요금제", "요금할인",
                   "제휴카드", "선납", "모든G", "미만")),
    ("정책 추가금", ("별도", "기타추가", "추가정책", "스팟", "소급", "활성화", "KT정책", "MIT")),
    ("기본 수수료", ("상품권", "미포함계")),
]
CHECK_ORDER = ["정책 단가(리베이트)", "부가서비스", "개통 조건", "정책 추가금"]
HINT = {
    "부가서비스": "부가서비스(필수팩·보험·VAS 등) 미유치/미유지 여부 확인",
    "개통 조건": "요금제·약정·로그인·지원금 조건 충족 여부 확인",
    "정책 추가금": "추가 정책금 지급 조건·판매일보 구두 금액 확인",
    "기본 수수료": "기본 수수료(단가표) 확인",
    "기타": "정산서 해당 항목 내역을 거래처에 확인",
}


def category_of(label):
    t = "".join(str(label or "").split()).upper()
    for cat, words in CATEGORIES:
        if any(w.upper().replace(" ", "") in t for w in words):
            return cat
    return "기타"


def _won(v):
    return f"{fmt_amt(v)}원"


def _subset_for(target, items, max_size=3):
    """합이 target 인 항목 조합들 중 가장 그럴듯한 것. (조합, 확실함 여부)"""
    if not target or not items:
        return None, False
    best_rank, found = None, []
    for size in range(1, min(max_size, len(items)) + 1):
        for combo in combinations(items, size):
            if sum(x["amount"] for x in combo) != target:
                continue
            same_sign = all((x["amount"] > 0) == (target > 0) for x in combo)
            rank = (size, 0 if same_sign else 1)
            if best_rank is None or rank < best_rank:
                best_rank, found = rank, [combo]
            elif rank == best_rank:
                found.append(combo)
        if found:
            break
    if not found:
        return None, False
    return found[0], len(found) == 1


def parse_memo(memo):
    """'그레이드+5\n보험 미가입 -1' → [{'text': '그레이드', 'amount': 50000}, {'text': '보험 미가입', 'amount': -10000}]"""
    out = []
    for line in str(memo or "").split("\n"):
        line = line.strip()
        m = MEMO_RE.search(line)
        if not m:
            continue
        amt = round(float(m.group(2)) * 10000)
        out.append({"text": line[:m.start()].strip(" :/") or line, "amount": -amt if m.group(1) in "-−" else amt, "line": line})
    return out


def _affinity(text, label):
    t, l = str(text).upper(), str(label).upper()
    return any(any(w.upper() in t for w in mw) and any(w.upper() in l for w in vw) for mw, vw in AFFINITY)


def reconcile_memo(memo, items, other_sale):
    """판매일보 메모 항목 ↔ 정산서 상세 항목을 금액으로 짝짓기.
    메모 합계가 판매일보 구두−차감금액과 정확히 같을 때만 사용(아니면 None)."""
    memo_items = parse_memo(memo)
    if not memo_items:
        return None
    usable = None
    for cand in (memo_items, [m for m in memo_items if not any(k in m["line"] for k in MEMO_SKIP)]):
        if cand and sum(m["amount"] for m in cand) == other_sale:
            usable = cand
            break
    if usable is None:
        return None
    M = [dict(m, used=False) for m in sorted(usable, key=lambda x: -abs(x["amount"]))]
    V = [dict(v, used=False) for v in items]
    pairs = []

    def one_to_one(need_aff):
        for m in M:
            if m["used"]:
                continue
            cands = [v for v in V if not v["used"] and v["amount"] == m["amount"]
                     and (not need_aff or _affinity(m["text"], v["label"]))]
            if cands:
                v = sorted(cands, key=lambda x: 0 if _affinity(m["text"], x["label"]) else 1)[0]
                v["used"] = m["used"] = True
                pairs.append(([m["line"]], [v["label"]], m["amount"]))

    def two_memo_to_one(need_aff):
        for v in V:
            if v["used"]:
                continue
            for a, b in combinations([m for m in M if not m["used"]], 2):
                if a["amount"] + b["amount"] != v["amount"]:
                    continue
                if need_aff and not (_affinity(a["text"], v["label"]) and _affinity(b["text"], v["label"])):
                    continue
                a["used"] = b["used"] = v["used"] = True
                pairs.append(([a["line"], b["line"]], [v["label"]], v["amount"]))
                break

    def two_vendor_to_one():
        for m in M:
            if m["used"]:
                continue
            for a, b in combinations([v for v in V if not v["used"]], 2):
                if a["amount"] + b["amount"] == m["amount"]:
                    a["used"] = b["used"] = m["used"] = True
                    pairs.append(([m["line"]], [a["label"], b["label"]], m["amount"]))
                    break

    one_to_one(True)          # 같은 금액 + 이름 비슷 (보험↔보험류, 교보·V컬↔VAS …)
    two_memo_to_one(True)     # 메모 2개 = 정산서 1개 (예: 교보 -1 + V컬 -1 = VAS -2만)
    one_to_one(False)         # 같은 금액
    two_memo_to_one(False)
    two_vendor_to_one()       # 정산서 2개 = 메모 1개

    def drop_zero_pairs(rows):   # '상품권 +3 / 상품권 -3' 처럼 서로 상쇄되는 줄은 원인에서 뺀다
        rows = list(rows)
        changed = True
        while changed:
            changed = False
            for a, b in combinations(range(len(rows)), 2):
                if rows[a]["amount"] + rows[b]["amount"] == 0:
                    rows = [r for i, r in enumerate(rows) if i not in (a, b)]
                    changed = True
                    break
        return rows

    return {"pairs": pairs,
            "memo_only": drop_zero_pairs({"text": m["line"], "amount": m["amount"]} for m in M if not m["used"]),
            "vendor_only": drop_zero_pairs({"label": v["label"], "amount": v["amount"], "category": v["category"]}
                                           for v in V if not v["used"])}


def analyze(it, detail_items, sale_memo):
    """it: engine 결과 1건, detail_items: [(라벨, 매장기준 금액)], sale_memo: 판매일보 구두·차감 메모."""
    items = [{"label": lab, "amount": amt, "category": category_of(lab)} for lab, amt in detail_items if amt]

    other_sale = it["other_sale"] if it["rebate_vendor"] is not None else it["sales_cmp"]
    it["memo_match"] = reconcile_memo(sale_memo, items, other_sale) if it["rebate_vendor"] is not None else None

    # ---- 큰 틀 점검표
    checks = []
    if it["rebate_vendor"] is not None:
        checks.append({"name": "정책 단가(리베이트)", "status": "ok" if not it["rebate_diff"] else "bad",
                       "text": "판매일보와 일치" if not it["rebate_diff"] else
                       f"판매일보 {it['rebate_sale']:,.0f} / 정산서 {it['rebate_vendor']:,.0f} ({_won(it['rebate_diff'])})"})
    for cat in CHECK_ORDER[1:]:
        cat_items = [x for x in items if x["category"] == cat]
        minus = [x for x in cat_items if x["amount"] < 0]
        plus = [x for x in cat_items if x["amount"] > 0]
        if minus:
            status, text = "warn", "차감 있음: " + ", ".join(f"{x['label']} {_won(x['amount'])}" for x in minus)
        elif plus:
            status, text = "ok", "지급: " + ", ".join(f"{x['label']} {_won(x['amount'])}" for x in plus)
        else:
            status, text = "ok", "해당 없음"
        if minus and plus:
            text += " / 지급: " + ", ".join(f"{x['label']} {_won(x['amount'])}" for x in plus)
        checks.append({"name": cat, "status": status, "text": text})

    # ---- 예상 원인
    causes = []
    mr = it.get("memo_match")
    rebate_explained = False
    if mr and it.get("rebate_diff"):
        hit = next((m for m in mr["memo_only"] if m["amount"] == it["rebate_diff"]), None)
        if hit:
            mr["memo_only"].remove(hit)
            rebate_explained = True
            for ch in checks:
                if ch["name"] == "정책 단가(리베이트)":
                    ch["status"], ch["text"] = "warn", ch["text"] + f" — 판매일보 메모 '{hit['text']}'로 이미 반영(같은 내용)"
            causes.append({"category": "정책 단가(리베이트)", "amount": 0, "confident": True,
                           "text": f"리베이트 {_won(it['rebate_diff'])} 차이는 판매일보 메모 '{hit['text']}'와 같은 내용 "
                                   "(판매일보는 차감금액으로, 정산서는 리베이트에서 깎아서 반영) — 실제 차이 아님"})
    if it["status"] != "match":
        if it["rebate_vendor"] is not None and it["rebate_diff"] and not rebate_explained:
            causes.append({"category": "정책 단가(리베이트)", "amount": it["rebate_diff"], "confident": True,
                           "text": f"리베이트(정책 단가)가 판매일보 {it['rebate_sale']:,.0f}원, 정산서 {it['rebate_vendor']:,.0f}원으로 "
                                   f"{_won(it['rebate_diff'])} 차이 → 개통 시점 단가표(모델·요금제·개통유형) 확인"})
        rest = it["other_diff"] if it["rebate_vendor"] is not None else it["diff"]
        if rebate_explained:
            rest = it["diff"]
        if rest and mr and (mr["memo_only"] or mr["vendor_only"]):
            for v in mr["vendor_only"]:
                cat = v["category"]
                if v["amount"] > 0:
                    txt = f"정산서에 '{v['label']}' {_won(v['amount'])}이(가) 추가로 들어옴 — 판매일보 메모에는 없는 항목"
                else:
                    txt = f"정산서에서 '{v['label']}' {_won(v['amount'])} 차감 — 판매일보 메모에는 없는 차감 → {HINT.get(cat, HINT['기타'])}"
                causes.append({"category": cat, "amount": v["amount"], "confident": True, "items": [v["label"]], "text": txt})
            for m in mr["memo_only"]:
                if m["amount"] > 0:
                    txt = f"판매일보 메모 '{m['text']}' ({_won(m['amount'])})가 정산서에 없음 → 해당 정책이 적용되는지 거래처 확인"
                else:
                    txt = f"판매일보 메모 '{m['text']}' ({_won(m['amount'])}) 차감을 예상했지만 정산서에는 없음"
                causes.append({"category": "판매일보 메모", "amount": -m["amount"], "confident": True, "text": txt})
            rest = 0
        if rest:
            combo, sure = _subset_for(rest, items)
            if combo:
                cats = sorted({x["category"] for x in combo}, key=lambda c: CHECK_ORDER.index(c) if c in CHECK_ORDER else 9)
                names = ", ".join(f"{x['label']} {_won(x['amount'])}" for x in combo)
                same = all((x["amount"] > 0) == (rest > 0) for x in combo)
                if same and rest < 0:
                    head = f"정산서의 {names} 차감이 판매일보(구두·차감금액)에 반영 안 된 것으로 보임"
                elif same:
                    head = f"정산서에 {names}이(가) 들어왔는데 판매일보(구두)에는 없는 것으로 보임"
                else:
                    head = f"정산서의 {names} 항목이 판매일보와 다르게 반영된 것으로 보임"
                causes.append({"category": cats[0], "amount": rest, "confident": sure,
                               "items": [x["label"] for x in combo],
                               "text": head + " → " + " / ".join(HINT.get(c, HINT["기타"]) for c in cats)
                                       + ("" if sure else " (같은 금액이 되는 다른 조합도 있어 정확한 항목은 확인 필요)")})
            else:
                causes.append({"category": "기타", "amount": rest, "confident": False,
                               "text": f"정산서 정책 항목과 판매일보 구두·차감이 {_won(rest)} 다름. 한 항목으로 딱 맞지 않아 "
                                       "단가표 기준으로 항목별 확인 필요"})
        for c in causes:
            for ch in checks:
                if ch["name"] == c["category"] and c["amount"]:
                    ch["status"] = "bad"
    if it.get("flag"):
        causes.append({"category": "매칭", "amount": 0, "confident": False, "text": "매칭 참고: " + it["flag"]})

    it["vendor_items"] = items
    it["sale_memo"] = sale_memo
    it["checks"] = checks
    it["causes"] = causes
    it["cause_text"] = " / ".join(c["text"] for c in causes) if causes else ""
    return it
