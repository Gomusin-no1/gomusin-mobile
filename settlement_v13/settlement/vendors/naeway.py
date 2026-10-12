"""내외정보통신 정산서 (판매일보 청약점 = '내외'). 계정명 예: 김민성▶폰명장고무신부평본점.

양식: 시트 1개. 4행 헤더(순 번/모 델 명/일련번호/.../리베이트/총정산금), 5행부터 데이터.
  여러 통신사(LGT/SKT 등) 개통 건을 함께 취급. 개통번호는 마스킹 없이 전체 노출.
  일련번호가 없는 행(예: '5월 부가서비스 미유지 환수')은 매장 단위 조정 건.
부호: 총정산금 = 모든 항목의 단순 합이며 대부분 음수 = 매장이 거래처에 낼 돈.
      → 판매일보(매장이 받을 돈 = 양수)와 방향을 맞추려고 비교 금액은 부호를 뒤집는다.

비교 규칙 (2026-09 확인):
  정산서_비교금액 = −(필수팩+보험+요금제추가+(KT정책·추가지원금활성화)+요금할인추가+별도정책추가+제휴카드추가+차감+선납금+리베이트)
  추가지원금(판매일보 T열과 같은 값)·유심·이동수수료·현금건은 차액 계산에서 제외
  리베이트 비교: 판매일보 R/B ↔ −리베이트
"""
from ..common import date_gap, date_str, device_score, digits, name_ok, note, num
from ..io_excel import load_workbook_any, norm_header, clean_label
from .base import Vendor

EXCLUDE = ("이동수수료", "현금건(단말기)", "추가지원금", "유심")
CORE = ("필수팩", "보험", "요금제추가", "KT정책추가", "요금할인추가", "별도정책추가", "제휴카드추가", "차감", "선납금", "리베이트")


class Naeway(Vendor):
    code = "naeway"
    name = "내외정보통신"
    sales_keyword = "내외"
    vendor_cmp_label = "정산서_비교금액(부호반전)"
    rebate_vendor_label = "리베이트_정산서(부호반전)"
    excl_vendor_label = "제외_정산서(추가지원금·유심·이동수수료·현금건)"
    totals_vendor_label = "정산서 핵심금액 합계(부호반전)"
    top_note = ("※ 추가지원금·유심·이동수수료·현금건은 정산 차액 계산에서 제외. 내외 정산서는 '매장이 낼 돈'이 음수로 표시되는 "
                "부호 체계라 비교 금액은 부호를 뒤집어 판매일보와 맞췄습니다.")
    uv_headers = ["정산서_행", "모델명/항목", "개통일", "개통판매처(정산서 표기)", "고객명", "개통번호", "총정산금", "", "비고"]
    uv_widths = [10, 26, 12, 40, 14, 16, 14, 4, 50]

    def load(self, paths):
        rows, store_level, info = [], [], []
        for path in paths:
            ws = load_workbook_any(path).worksheets[0]
            hr = next(r for r in range(1, 15)
                      if any(norm_header(ws.cell(r, c).value) == "고객명" for c in range(1, ws.max_column + 1)))
            h = {}
            for c in range(1, ws.max_column + 1):
                k = norm_header(ws.cell(hr, c).value)
                if k and k not in h:           # '추가지원금'은 두 번 나오는데 앞쪽(정산 상세) 열을 쓴다
                    h[k] = c
            info.append(f"거래처 표기: {clean_label(ws.cell(1, 2).value)}")
            for r in range(hr + 1, ws.max_row + 1):
                g = lambda k: ws.cell(r, h[k]).value if k in h else None  # noqa: E731
                has_name = g("고객명") not in (None, "")
                has_amount = isinstance(g("총정산금"), (int, float)) and g("총정산금") != 0
                if not has_name and not (g("모델명") not in (None, "") and has_amount):
                    continue                    # 합계 줄·하단 안내문 줄은 건너뜀
                v = {"row": r, "model": g("모델명"), "serial": g("일련번호"), "shop": g("개통판매처"),
                     "name": g("고객명"), "phone_masked": g("개통번호"), "date": date_str(g("개통일")),
                     "carrier": g("유형"), "total": num(g("총정산금")), "memo": g("수정건"),
                     "amt": {k: num(g(k)) for k in CORE + EXCLUDE}}
                v["kind"] = "무선" if v["serial"] not in (None, "") else "매장단위"
                (rows if v["kind"] == "무선" else store_level).append(v)
        return rows, store_level, info

    def strict_key(self, v, s):
        if v["kind"] != "무선":
            return None
        if digits(v["phone_masked"]) != s["phone_digits"] or not name_ok(v["name"], s["name"]):
            return None
        gap = date_gap(v["date"], s["date"])
        return None if gap > 45 else (1 if s["is_bundle"] else 0, -device_score(s["device"], v["model"]), gap)

    def compare(self, v):
        a = v["amt"]
        labels = {"KT정책추가": "추가지원금활성화(KT정책추가 열)", "별도정책추가": "별도추가"}
        return {"kind": f"무선({v['carrier'] or ''})", "vendor_cmp": -sum(a[k] for k in CORE),
                "rebate_vendor": -a["리베이트"],
                "vendor_other_note": note([(labels.get(k, k), -a[k]) for k in CORE if k != "리베이트"]),
                "detail_items": [(labels.get(k, k), -a[k]) for k in CORE if k != "리베이트"],
                "excluded_vendor": note([(k, a[k]) for k in EXCLUDE])}

    def unmatched_vendor_row(self, v):
        memo = ("매장 단위 조정 건 — 개별 판매 건과 1:1 매칭 대상 아님" + (f" ({v['memo']})" if v.get("memo") else "")
                if v["kind"] == "매장단위" else "판매일보(청약점=내외)에서 같은 번호·이름을 찾지 못함")
        return [v["row"], v["model"], v["date"], v["shop"], v["name"], v["phone_masked"], v["total"], "", memo]

    def guide(self):
        return [
            "■ 부호 체계 (중요)",
            "내외정보통신 정산서의 총정산금은 대부분 음수 = 매장이 낼 돈입니다. 판매일보와 방향을 맞추려고 비교 금액은 부호를 뒤집었습니다.",
            "■ 비교 금액 계산 방법",
            "판매일보_비교금액 = 리베이트(P) + 구두(Q) − 차감금액(R)",
            "정산서_비교금액 = −(필수팩+보험+요금제추가+추가지원금활성화+요금할인추가+별도추가+제휴카드추가+차감+선납금+리베이트)",
            "  → 추가지원금·유심·이동수수료·현금건은 제외 (오른쪽 끝 참고용)",
            "정산서의 '개통 판매처' 표기는 실제 매장과 다를 수 있어 매장 구분은 판매일보 기준입니다.",
        ]
