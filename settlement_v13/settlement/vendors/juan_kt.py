"""KT ㈜주안정보통신 정산서 (판매일보 청약점 = '주안').

양식: 계정(매장 코드)마다 파일 1개(.xls). 시트: 통계 / 무선 / 유선 / 기타 / 유심 인수단말 / 수정요청.
  무선 시트: 2행 그룹(①판매수수료 ②현금판매 기기대금 ③세금계산서 미발행 / 실지급액 / 무선 수수료 상세),
            3행 항목명, 4행부터 데이터. 월마다 열 위치가 바뀌므로(2026-09 에 리베이트 W→Y 이동 등)
            열 문자 대신 '항목명'으로 열을 찾는다.
  계정 이름(통계 B5)과 실제 판매 매장은 다를 수 있음 → 매장 구분은 항상 판매일보 기준.

비교 규칙 (2026-08 사용자 확정, 2026-09 양식 변경 반영):
  무선: 정산서_비교금액 = 무선 수수료 = 리베이트 + 무선 수수료 상세 항목 합
        추가지원금·유심후청구·② 합계(현금판매 기기대금)·③ 항목(번동료 등)은 차액 계산에서 제외
        리베이트 비교: 판매일보 R/B ↔ '리베이트' 열
  유선: 정산서_비교금액 = 총 유선 수수료 (리베이트를 나눌 열이 없어 종합 금액만 비교)
"""
from ..common import date_gap, date_str, device_score, name_ok, note, num, phone_regex, phone_tail
from ..io_excel import load_workbook_any, norm_header, clean_label
from .base import Vendor


def _row_map(ws, r):
    m = {}
    for c in range(1, ws.max_column + 1):
        h = norm_header(ws.cell(r, c).value)
        if h and h not in m:
            m[h] = c
    return m


class JuanKT(Vendor):
    code = "juan"
    name = "KT ㈜주안정보통신"
    sales_keyword = "주안"
    vendor_cmp_label = "정산서_비교금액(무선수수료 / 유선수수료)"
    rebate_vendor_label = "리베이트_정산서"
    excl_vendor_label = "제외_정산서(추가지원금·유심후청구·현금판매기기대금·번동료 등)"
    totals_vendor_label = "정산서 비교금액 합계(무선수수료 + 유선수수료)"
    top_note = "※ 추가지원금·유심후청구·현금판매기기대금·번동료 등은 정산 차액 계산에서 제외(참고용 표시)."
    uv_headers = ["정산서 계정", "위치", "날짜", "고객명/항목", "번호", "수수료/금액", "실지급/합계", "비고"]
    uv_widths = [34, 14, 12, 28, 16, 14, 14, 60]

    def load(self, paths):
        rows, store_level, info = [], [], []
        for path in paths:
            wb = load_workbook_any(path)
            acct = str(wb["통계"]["B5"].value or path)
            info.append(f"{acct}: 실수령 {num(wb['통계']['D5'].value):,.0f}")
            rows += self._wireless(wb["무선"], acct)
            if "유선" in wb.sheetnames:
                rows += self._wired(wb["유선"], acct)
            for sn, label in (("기타", "퀵비·기타 차감"), ("유심 인수단말", "유심 인수단말(유심 구매)")):
                if sn not in wb.sheetnames:
                    continue
                w = wb[sn]
                items = [(w.cell(r, 3).value, num(w.cell(r, 4).value))
                         for r in range(3, w.max_row + 1) if w.cell(r, 2).value and w.cell(r, 4).value not in (None, "")]
                if items:
                    store_level.append({"kind": "매장단위", "acct": acct, "sheet": sn, "label": label,
                                        "count": len(items), "amount": sum(x[1] for x in items),
                                        "items": "; ".join(f"{a}({b:,.0f})" for a, b in items[:5]) + (" …" if len(items) > 5 else "")})
        return rows, store_level, info

    def _wireless(self, ws, acct):
        g2 = {}
        for c in range(1, ws.max_column + 1):
            t = norm_header(ws.cell(2, c).value)
            for key in ("①", "②", "③", "실지급", "무선수수료상세"):
                if t.startswith(key) and key not in g2:
                    g2[key] = c
        h = _row_map(ws, 3)
        c_fee, c_add, c_usim = h["무선수수료"], h["추가지원금"], h["유심후청구"]
        c_reb = h.get("리베이트")                         # 개통 건이 없는 달은 상세 열 자체가 없을 수 있음
        c3, c_real = g2["③"], g2["실지급"]
        c_sum2 = c3 - 1                                   # ② 그룹의 마지막(항목명 없는) 열 = 현금판매 기기대금 합계
        group3 = [(c, clean_label(ws.cell(3, c).value)) for c in range(c3, c_real) if ws.cell(3, c).value]
        detail = ([(c, clean_label(ws.cell(3, c).value)) for c in range(c_reb + 1, ws.max_column + 1) if ws.cell(3, c).value]
                  if c_reb else [])
        out = []
        for r in range(4, ws.max_row + 1):
            if ws.cell(r, h["개통시간"]).value in (None, 0, ""):
                continue
            g = lambda c: ws.cell(r, c).value  # noqa: E731
            out.append({"kind": "무선", "acct": acct, "row": r, "date": date_str(g(h["개통시간"])),
                        "name": g(h["고객명"]), "phone_masked": g(h["개통번호"]), "open_type": g(h["개통구분"]),
                        "model": g(h["모델명"]), "fee": num(g(c_fee)), "add": num(g(c_add)), "usim": num(g(c_usim)),
                        "sum2": num(g(c_sum2)), "group3": [(lab, num(g(c))) for c, lab in group3],
                        "real": num(g(c_real)), "rebate": num(g(c_reb)) if c_reb else None,
                        "detail": [(lab, num(g(c))) for c, lab in detail]})
        return out

    def _wired(self, ws, acct):
        hr = next((r for r in range(1, 6) if "총유선수수료" in _row_map(ws, r)), None)
        if hr is None:
            return []
        h = _row_map(ws, hr)
        c_tot = h["총유선수수료"]
        detail = [(c, clean_label(ws.cell(hr, c).value)) for c in range(c_tot + 1, ws.max_column + 1) if ws.cell(hr, c).value]
        out = []
        for r in range(hr + 1, ws.max_row + 1):
            if not ws.cell(r, h["유선명의자명"]).value:
                continue
            g = lambda c: ws.cell(r, c).value  # noqa: E731
            out.append({"kind": "유선", "acct": acct, "row": r, "date": date_str(g(h["유선접수일자"])),
                        "name": g(h["유선명의자명"]), "product": g(h.get("단품(유선)명", c_tot)),
                        "phone_masked": g(h.get("유선접속번호", c_tot)), "total": num(g(c_tot)),
                        "detail": [(lab, num(g(c))) for c, lab in detail]})
        return out

    def strict_key(self, v, s):
        if v["kind"] == "무선":
            pr = phone_regex(v["phone_masked"])
            if not pr or not pr.match(s["phone_digits"]) or not name_ok(v["name"], s["name"]):
                return None
            gap = date_gap(v["date"], s["date"])
            return None if gap > 45 else (1 if s["is_bundle"] else 0, -device_score(s["device"], v["model"]), gap)
        if v["kind"] == "유선":
            if not s["is_bundle"] or not name_ok(v["name"], s["name"]):
                return None
            gap = date_gap(v["date"], s["date"])
            return None if gap > 15 else (gap,)
        return None

    def compare(self, v):
        if v["kind"] == "무선":
            return {"kind": "무선", "vendor_cmp": v["fee"], "rebate_vendor": v["rebate"],
                    "vendor_other_note": note(v["detail"]), "detail_items": v["detail"],
                    "excluded_vendor": note([("추가지원금", v["add"]), ("유심후청구", v["usim"]),
                                             ("현금판매기기대금", v["sum2"])] + v["group3"])}
        return {"kind": "유선(인터넷/TV)", "vendor_cmp": v["total"], "rebate_vendor": None,
                "vendor_other_note": note(v["detail"] + [("상품", v["product"])]), "excluded_vendor": "없음",
                "detail_items": v["detail"]}

    def unmatched_vendor_row(self, v):
        if v["kind"] == "매장단위":
            return [v["acct"], v["sheet"], "", f"{v['label']} {v['count']}건", "", v["amount"], v["amount"],
                    "매장 단위 차감 항목 — 개별 판매 건과 1:1 매칭 대상 아님. " + v["items"]]
        if v["kind"] == "무선":
            memo = ("유심 단독 개통(유심후청구만 발생)" if str(v["open_type"]) == "유심"
                    else "판매일보(청약점=주안)에서 같은 번호·이름을 찾지 못함")
            return [v["acct"], f"무선 {v['row']}행", v["date"], v["name"], v["phone_masked"], v["fee"], v["real"], memo]
        return [v["acct"], f"유선 {v['row']}행", v["date"], v["name"], v["phone_masked"], v["total"], v["total"],
                "판매일보 결합 행을 찾지 못함"]

    def unmatched_sales_hint(self):
        return "받은 주안 정산서(계정) 어디에도 없음 — 아직 안 받은 다른 계정 정산서에 있을 수 있음"

    def guide(self):
        return [
            "■ 비교 금액 계산 방법",
            "판매일보_비교금액 = 리베이트(P) + 구두(Q) − 차감금액(R)",
            "정산서_비교금액(무선) = 무선 수수료 = 리베이트 + 무선 수수료 상세 항목(추가정책·필수팩·보험·스팟·별도추가 등) 합",
            "  → 추가지원금·유심후청구·현금판매 기기대금(② 합계)·③ 항목(번동료 등)은 제외 (오른쪽 끝 참고용)",
            "정산서_비교금액(유선) = 총 유선 수수료. 유선은 리베이트를 따로 나눌 열이 없어 종합 금액만 비교합니다.",
            "정산서의 계정(매장명)과 실제 판매 매장은 다를 수 있어, 매장 구분은 판매일보 기준으로 표시합니다.",
            "정산서 양식의 열 위치가 달마다 바뀌어도 '항목명'으로 열을 찾기 때문에 그대로 동작합니다.",
        ]
