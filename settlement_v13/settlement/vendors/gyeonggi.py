"""경기서부모바일 정산서 (판매일보 청약점 = '경기').

양식: 시트 1개. 7행 헤더(가입번호/판매일자/.../액면/별도추가1/.../지급계/실지급계), 8행부터 데이터.
부호: 정산서 금액은 음수 = 매장에 지급. 비교할 때는 부호를 바꿔 '매장 기준(+받음)'으로 쓴다.
행 종류: 무선(번호 뒤 4자리 노출), TV/인터넷 결합(유형2에 'DPS'), 퀵비(가입번호='퀵비'), 해지반환.

비교 규칙 (2026-08 사용자 확정):
  정산서_비교금액 = −지급계 = −(액면 + 별도추가1·2 + 기타추가 + 축소정책 + 부가서비스 + 기타열들)
  유통망지원금·현금판매분은 차액 계산에서 완전히 제외 (리베이트에도 더하지 않음)
  리베이트 비교: 판매일보 R/B ↔ −액면
"""
from ..common import date_gap, date_str, device_score, digits, name_ok, note, num
from ..io_excel import load_workbook_any, norm_header, clean_label
from .base import Vendor


class Gyeonggi(Vendor):
    code = "gyeonggi"
    name = "경기서부모바일"
    sales_keyword = "경기"
    vendor_cmp_label = "정산서_비교금액(지급계, 매장기준)"
    rebate_vendor_label = "리베이트_정산서(액면)"
    excl_vendor_label = "제외_정산서(유통망지원금+현금판매분)"
    totals_vendor_label = "정산서 지급계 합계(매장기준)"
    top_note = "※ 유통망지원금·현금판매분·이동통신료·유심비는 정산 차액 계산에서 제외(참고용 표시)."
    uv_headers = ["구분", "정산서_행", "날짜", "판매처", "고객명", "CTN", "지급계(매장기준)", "실지급계(매장기준)", "비고"]
    uv_widths = [20, 9, 12, 44, 14, 16, 15, 15, 50]

    def load(self, paths):
        rows, store_level, info = [], [], []
        for path in paths:
            wb = load_workbook_any(path)
            ws = wb.worksheets[0]
            hr = next(r for r in range(1, 20) if norm_header(ws.cell(r, 1).value) == "가입번호")
            col = {}
            for c in range(1, ws.max_column + 1):
                h = norm_header(ws.cell(hr, c).value)
                if h and h not in col:
                    col[h] = c
            def find(prefix):
                return next(c for h, c in col.items() if h.startswith(prefix))
            c_face, c_pay, c_real = col["액면"], col["지급계"], col["실지급계"]
            detail_cols = [(c, clean_label(ws.cell(hr, c).value)) for c in range(c_face + 1, c_pay)]
            C = dict(date=col["판매일자"], shop=col["판매처"], name=col["고객명"], ctn=col["CTN"], t1=col["유형"],
                     t2=col["유형2"], model=col["모델명"], dist=col["유통망지원금"], cash=find("현금판매분"))
            for r in range(1, hr):
                lab = norm_header(ws.cell(r, 1).value)
                if lab in ("정산금", "공과금", "실지급", "반환금"):
                    info.append(f"{lab}: {num(ws.cell(r, 2).value):,.0f} (정산서 부호 그대로)")
            for r in range(hr + 1, ws.max_row + 1):
                a = ws.cell(r, 1).value
                if a in (None, ""):
                    continue
                g = lambda c: ws.cell(r, c).value  # noqa: E731
                t1, t2 = str(g(C["t1"]) or ""), str(g(C["t2"]) or "")
                if str(a).strip() == "퀵비":
                    kind = "퀵비"
                elif "DPS" in t2:
                    kind = "TV결합"
                elif "반환" in t1 + t2 or "해지" in t1 + t2:
                    kind = "해지반환"
                else:
                    kind = "무선"
                v = {"row": r, "kind": kind, "date": date_str(g(C["date"])), "shop": g(C["shop"]),
                     "name": g(C["name"]), "phone_masked": g(C["ctn"]) if kind == "무선" else "",
                     "model": g(C["model"]), "face": num(g(c_face)), "pay": num(g(c_pay)), "real": num(g(c_real)),
                     "dist": num(g(C["dist"])), "cash": num(g(C["cash"])),
                     "detail": [(lab, num(g(c))) for c, lab in detail_cols]}
                v["last4"] = digits(v["phone_masked"])[-4:] if kind == "무선" else ""
                if kind in ("퀵비", "해지반환"):
                    store_level.append(v)
                else:
                    rows.append(v)
        return rows, store_level, info

    def strict_key(self, v, s):
        if v["kind"] == "무선":
            if len(v["last4"]) != 4 or not s["phone_digits"].endswith(v["last4"]):
                return None
            if not name_ok(v["name"], s["name"]):
                return None
            gap = date_gap(v["date"], s["date"])
            if gap > 45:
                return None
            return (1 if s["is_bundle"] else 0, -device_score(s["device"], v["model"]), gap)
        if v["kind"] == "TV결합":
            if not s["is_bundle"] or not name_ok(v["name"], s["name"]):
                return None
            gap = date_gap(v["date"], s["date"])
            return None if gap > 45 else (gap,)
        return None

    @staticmethod
    def _short(label):
        if label in ("-", ""):
            return "기타('-'열)"
        if label.startswith("1.유통망"):
            return "유통망지원금10만미만·U+ONE 미로그인 차감"
        if label.startswith("축소정책"):
            return "축소정책(선약·33미만·기변·디즈니 차감)"
        return label.replace("별도추가 1", "별도추가1").replace("별도추가 2", "별도추가2")

    def compare(self, v):
        detail = [(self._short(lab), -val) for lab, val in v["detail"]]
        return {"kind": "TV/인터넷 결합" if v["kind"] == "TV결합" else "무선",
                "vendor_cmp": -v["pay"], "rebate_vendor": -v["face"],
                "vendor_other_note": note(detail), "detail_items": detail,
                "excluded_vendor": note([("유통망지원금", v["dist"]), ("현금판매분", v["cash"])])}

    def unmatched_vendor_row(self, v):
        if v["kind"] in ("퀵비", "해지반환"):
            memo = "매장 단위 항목 — 개별 판매 건과 1:1 매칭 대상 아님"
        else:
            memo = "판매일보(청약점=경기)에서 같은 번호 뒷자리·이름을 찾지 못함"
        return [v["kind"], v["row"], v["date"], v["shop"], v["name"], v["phone_masked"], -v["pay"], -v["real"], memo]

    def guide(self):
        return [
            "■ 비교 금액 계산 방법",
            "판매일보_비교금액 = 리베이트(P) + 구두(Q) − 차감금액(R)  (S·T열 지원금/현금개통, 유심비, 수수료 제외)",
            "정산서_비교금액 = 지급계를 매장 기준(+받음)으로 바꾼 값 = 액면 + 별도추가 + 기타추가 + 축소정책 + 부가서비스 등",
            "  → 유통망지원금·현금판매분은 차액 계산에서 완전히 제외 (리베이트에도 더하지 않음, 오른쪽 끝에 참고로만 표시)",
            "① 리베이트 비교: 판매일보 R/B ↔ 정산서 액면",
            "② 기타조정 비교: 판매일보 구두−차감금액 ↔ 정산서 액면과 지급계 사이 모든 열의 합",
            "정산서 상세 금액은 매장 기준으로 부호를 바꿔 표시합니다 (+ = 매장이 받는 돈, − = 차감).",
        ]
