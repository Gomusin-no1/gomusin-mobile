"""정산 대사 실행 (명령줄).

예시:
  python run.py --year 2026 --month 9 \
      --sales 본점=판매일보/본점.xlsx --sales 2호점=판매일보/2호점.xlsx --sales 3호점=판매일보/3호점.xlsx \
      --vendor gyeonggi 정산서/경기_09.xlsx \
      --vendor juan 정산서/주안_2호.xls 정산서/주안_3호.xls \
      --out 결과

거래처 코드: gyeonggi(경기서부모바일), juan(KT 주안정보통신), naeway(내외정보통신)
결과: 거래처마다 '<월>월_<거래처>_대사.xlsx' 와 같은 이름의 .json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from settlement.engine import reconcile  # noqa: E402
from settlement.report import write_excel  # noqa: E402
from settlement.sales import read_sales  # noqa: E402
from settlement.vendors import VENDORS  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="판매일보 vs 거래처 정산서 대사")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--sales", action="append", required=True, help="매장=판매일보경로 (매장마다 한 번씩)")
    ap.add_argument("--vendor", action="append", nargs="+", required=True, metavar=("코드", "파일"),
                    help="거래처코드 정산서파일1 [정산서파일2 ...]")
    ap.add_argument("--out", default="결과")
    a = ap.parse_args(argv)

    sales_files = dict(x.split("=", 1) for x in a.sales)
    os.makedirs(a.out, exist_ok=True)
    sales_rows = read_sales(sales_files, a.month)          # 판매일보는 한 번만 읽어서 거래처마다 재사용
    for spec in a.vendor:
        code, files = spec[0], spec[1:]
        if code not in VENDORS:
            sys.exit(f"알 수 없는 거래처 코드: {code} (가능: {', '.join(VENDORS)})")
        res = reconcile(code, a.year, a.month, sales_files, files, sales_rows=sales_rows)
        base = os.path.join(a.out, f"{a.month}월_{VENDORS[code].name}_대사".replace(" ", "_").replace("㈜", ""))
        write_excel(res, base + ".xlsx")
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1, default=str)
        s = res["summary"]
        print(f"[{s['vendor']}] 매칭 {s['matched']}건 (일치 {s['match']} / 초과 {s['more']} / 부족 {s['less']}), "
              f"총액차이 {s['total_diff']:+,}원, 정산서 미매칭 {s['unmatched_vendor']}건, 판매일보 미매칭 {s['unmatched_sales']}건 → {base}.xlsx")


if __name__ == "__main__":
    main()
