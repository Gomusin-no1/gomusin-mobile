"""정산 대사 엔진: 판매일보 + 거래처 정산서 → 건별 비교 결과(JSON 가능 dict).

    from settlement.engine import reconcile
    result = reconcile("gyeonggi", 2026, 9, {"본점": "...xlsx", "2호점": "...", "3호점": "..."}, ["정산서.xlsx"])
    result["summary"], result["items"], result["unmatched_vendor"], result["unmatched_sales"]
"""
import calendar
import datetime

from .analysis import analyze
from .common import date_gap, first_line, match, note, status_of
from .sales import read_sales
from .vendors import VENDORS


def _sales_excluded(s):
    return note([(s["S_label"], s["S"]), (s["T_label"], s["T"]), ("유심비", s["U"]), ("수수료(이동통신료)", s["V"])])


def _item(v, s, cmp_, flag):
    it = {
        "kind": cmp_["kind"], "store": s["store"], "seller": s["seller"], "date": s["date"],
        "name": first_line(s["name"]), "phone": s["phone"], "device": first_line(s["device"]),
        "sales_row": s["row"], "vendor_row": v.get("row"), "vendor_account": v.get("acct"),
        "sales_cmp": s["P"] + s["Q"] - s["R"], "vendor_cmp": cmp_["vendor_cmp"],
        "rebate_sale": s["P"], "rebate_vendor": cmp_["rebate_vendor"],
        "other_sale": s["Q"] - s["R"],
        "sale_other_note": note([("구두", s["Q"]), ("차감금액", -s["R"] if s["R"] else 0)]),
        "vendor_other_note": cmp_["vendor_other_note"],
        "excluded_sale": _sales_excluded(s), "excluded_vendor": cmp_["excluded_vendor"],
        "flag": flag,
    }
    it["diff"] = it["vendor_cmp"] - it["sales_cmp"]
    it["status"] = status_of(it["diff"])
    if it["rebate_vendor"] is not None:
        it["rebate_diff"] = it["rebate_vendor"] - it["rebate_sale"]
        it["other_vendor"] = it["vendor_cmp"] - it["rebate_vendor"]
        it["other_diff"] = it["other_vendor"] - it["other_sale"]
    else:
        it["rebate_diff"] = it["other_vendor"] = it["other_diff"] = None
    return analyze(it, cmp_.get("detail_items", []), s.get("memo", ""))


def reconcile(vendor_code, year, month, sales_files, vendor_files, sales_rows=None):
    vendor = VENDORS[vendor_code]
    if sales_rows is None:
        sales_rows = read_sales(sales_files, month)
    sales = [s for s in sales_rows if vendor.sales_keyword in s["vendor_raw"]]
    vrows, store_level, info = vendor.load(vendor_files)

    # 1차: 엄격 매칭 → 2차: 남은 것끼리 이름/번호 오타 보정 매칭
    pairs, uv, us = match(vrows, sales, vendor.strict_key)
    def relaxed_score(v, s):
        r = vendor.relaxed_key(v, s)
        return None if r is None else r[0]

    p2, uv, us = match(uv, us, relaxed_score)
    items = [_item(v, s, vendor.compare(v), None) for v, s in pairs]
    items += [_item(v, s, vendor.compare(v), vendor.relaxed_key(v, s)[1]) for v, s in p2]

    month_end = datetime.date(year, month, calendar.monthrange(year, month)[1])
    hint = getattr(vendor, "unmatched_sales_hint", lambda: "")()
    unmatched_sales = []
    for s in us:
        why = []
        if s["is_bundle"]:
            why.append("인터넷/TV 결합 행")
        if date_gap(s["date"], month_end) <= 3:
            why.append("월말 개통 — 다음 달 정산서 반영 가능성")
        if not why:
            why.append("정산서에서 같은 번호·이름을 찾지 못함 (누락 여부 확인 필요)")
        if hint:
            why.append(hint)
        unmatched_sales.append({**{k: s[k] for k in ("store", "seller", "row", "date", "phone", "P", "Q", "R", "W")},
                                "name": first_line(s["name"]), "device": first_line(s["device"]),
                                "sales_cmp": s["P"] + s["Q"] - s["R"], "reason": " / ".join(why)})

    n = {k: sum(1 for x in items if x["status"] == k) for k in ("match", "more", "less")}
    rb = [x for x in items if x["rebate_vendor"] is not None]
    summary = {
        "vendor": vendor.name, "vendor_code": vendor.code, "year": year, "month": month,
        "matched": len(items), "match": n["match"], "more": n["more"], "less": n["less"],
        "more_amount": sum(x["diff"] for x in items if x["status"] == "more"),
        "less_amount": sum(x["diff"] for x in items if x["status"] == "less"),
        "sales_total": sum(x["sales_cmp"] for x in items), "vendor_total": sum(x["vendor_cmp"] for x in items),
        "rebate_sales_total": sum(x["rebate_sale"] for x in rb), "rebate_vendor_total": sum(x["rebate_vendor"] for x in rb),
        "rebate_mismatch": sum(1 for x in rb if x["rebate_diff"]),
        "unmatched_vendor": len(uv), "store_level_items": len(store_level), "unmatched_sales": len(unmatched_sales),
        "vendor_info": info,
    }
    summary["total_diff"] = summary["vendor_total"] - summary["sales_total"]
    return {"summary": summary, "items": items,
            "unmatched_vendor": [vendor.unmatched_vendor_row(v) for v in sorted(uv, key=lambda x: x.get("row", 0))]
                                + [vendor.unmatched_vendor_row(v) for v in store_level],
            "unmatched_sales": unmatched_sales}
