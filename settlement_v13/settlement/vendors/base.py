"""거래처 어댑터 기본형.

새 거래처를 추가할 때는 이 클래스를 상속해서 아래 항목만 채우면 된다.
  code / name / sales_keyword  : 거래처 코드, 표시명, 판매일보 '청약점'에서 찾을 글자
  load(paths)                  : 정산서 파일들을 읽어 '정산서 행' dict 목록과 매장단위 항목 목록을 돌려줌
  strict_key(v, s)             : 1차 매칭 점수 (None 이면 후보 아님, 작을수록 우선)
  relaxed_key(v, s)            : 2차 매칭(이름 오타·번호 오타 보정). (점수, 설명) 또는 None
  compare(v)                   : 정산서 쪽 비교값 dict
  unmatched_vendor_row(v)      : 미매칭 시트에 쓸 한 줄
"""
from ..common import date_gap, first_line, name_ok, phone_tail


class Vendor:
    code = ""
    name = ""
    sales_keyword = ""
    # 엑셀 라벨
    vendor_cmp_label = "정산서_비교금액"
    rebate_vendor_label = "리베이트_정산서"
    other_vendor_label = "기타조정_정산서"
    excl_vendor_label = "제외_정산서"
    totals_vendor_label = "정산서 비교금액 합계"
    top_note = ""
    uv_headers = ["구분", "위치", "날짜", "고객명/항목", "번호", "정산서 금액", "참고 금액", "비고"]
    uv_widths = [22, 12, 12, 30, 16, 14, 14, 60]

    def load(self, paths):
        """→ (vendor_rows, store_level_rows, info_lines)"""
        raise NotImplementedError

    def strict_key(self, v, s):
        raise NotImplementedError

    def relaxed_key(self, v, s):
        """기본 2차 매칭: 같은 날(±1일) + (번호 끝자리 일치 & 이름 첫 글자 일치) 또는 (이름 일치, 번호 누락/불일치)."""
        if v.get("kind") != "무선" or s["is_bundle"]:
            return None
        if date_gap(v["date"], s["date"]) > 1:
            return None
        tail = phone_tail(v.get("phone_masked"))
        tail_ok = len(tail) >= 3 and s["phone_digits"].endswith(tail)
        first_ok = str(v["name"] or " ")[0].upper() == first_line(s["name"])[:1].upper()
        if tail_ok and first_ok:
            return (0, f"이름 표기가 달라 번호 끝자리·날짜로 매칭 (정산서 이름: {v['name']})")
        if name_ok(v["name"], s["name"]):
            if len(tail) < 3:
                why = "정산서 번호 누락"
            else:
                why = f"번호 끝자리 불일치(정산서 {tail} / 판매일보 {s['phone_digits'][-len(tail):]})"
            return (1, why + " — 이름·날짜로 매칭, 번호 확인 필요")
        return None

    def compare(self, v):
        """→ dict(vendor_cmp, rebate_vendor(None 가능), vendor_other_note, excluded_vendor)"""
        raise NotImplementedError

    def unmatched_vendor_row(self, v):
        raise NotImplementedError

    def guide(self):
        return []
