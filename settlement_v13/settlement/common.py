"""공통 유틸: 숫자/날짜/마스킹 이름·번호 매칭, 1:1 매칭 엔진."""
import datetime
import re


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def digits(s):
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def first_line(s):
    return str(s or "").split("\n")[0].strip()


# ------------------------------------------------------------------ 이름/번호
def name_regex(masked):
    """'오*식', 'Q********I', 'LI* *****NG' → 연속된 * 는 '0글자 이상'으로 처리.
    (한글은 글자당 * 1개, 영문은 길이와 무관하게 * 여러 개로 가리는 거래처가 있음)"""
    s = str(masked or "").strip()
    out, i = [], 0
    while i < len(s):
        if s[i] == "*":
            while i < len(s) and s[i] == "*":
                i += 1
            out.append(".*")
        else:
            out.append(re.escape(s[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


def name_ok(masked, sales_name):
    """판매일보 이름 칸에는 메모가 줄바꿈으로 붙거나(예: '이윤정\\n숭의점접수'),
    영문 이름이 두 줄로 나뉘어 있는 경우가 있어 여러 형태로 시도한다."""
    if not str(masked or "").strip():
        return False
    pat = name_regex(masked)
    raw = str(sales_name or "")
    cands = {first_line(raw),
             " ".join(x.strip() for x in raw.split("\n")).strip(),
             raw.replace("\n", "").replace(" ", "")}
    return any(pat.match(c) for c in cands if c)


def phone_regex(masked):
    """'010-56**-*924', '01053***425', '010-7630-8619' → 숫자는 그대로, * 는 숫자 1자리."""
    parts = []
    for ch in str(masked or ""):
        if ch.isdigit():
            parts.append(ch)
        elif ch == "*":
            parts.append(r"\d")
    return re.compile("^" + "".join(parts) + "$") if len(parts) >= 8 else None


def phone_tail(masked):
    """마스킹된 번호에서 끝부분에 그대로 보이는 숫자들. '010-****-3654'→'3654', '010-56**-*924'→'924'."""
    s = str(masked or "").strip()
    out = ""
    for ch in reversed(s):
        if ch.isdigit():
            out = ch + out
        elif ch == "-" and out == "":
            continue
        else:
            break
    return out


def to_date(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def date_str(v):
    d = to_date(v)
    return d.isoformat() if d else str(v or "")


def date_gap(a, b):
    da, db = to_date(a), to_date(b)
    return abs((da - db).days) if da and db else 999


MODEL_RE = re.compile(r"[A-Z]\d{3}")


def device_score(sales_dev, vendor_model):
    """판매일보 기종 vs 정산서 모델명 유사도. 같은 고객이 폰+워치처럼 여러 회선을 열었을 때 구분용."""
    sd = str(sales_dev or "").upper().replace(" ", "")
    vm = str(vendor_model or "").upper().replace(" ", "")
    if not sd or not vm:
        return 0
    score = 0
    for tok in MODEL_RE.findall(sd):
        if tok in vm:
            score += 3
    if (("아이폰" in sd) or ("IP" in sd)) and "IP" in vm:
        score += 1
        for gen in ("15", "16", "17", "18", "19"):
            if gen in sd and gen in vm:
                score += 1
    if ("워치" in sd or "WATCH" in sd) and re.search(r"L\d{3}", vm):
        score += 3
    return score


# ------------------------------------------------------------------ 매칭 엔진
def match(vendor_rows, sales_rows, key_fn):
    """정산서 행마다 key_fn(v, s) 로 후보 판매일보 행에 점수(작을수록 우선)를 매기고,
    후보가 적은 정산서 행부터 1:1로 배정한다. key_fn 이 None 을 주면 후보가 아니다."""
    used, pairs, unmatched_v = set(), [], []
    plan = []
    for v in vendor_rows:
        cands = []
        for i, s in enumerate(sales_rows):
            k = key_fn(v, s)
            if k is not None:
                cands.append((k, i))
        cands.sort(key=lambda x: x[0])
        plan.append((len(cands), v, cands))
    plan.sort(key=lambda x: x[0])
    for _, v, cands in plan:
        pick = next((i for _, i in cands if i not in used), None)
        if pick is None:
            unmatched_v.append(v)
        else:
            used.add(pick)
            pairs.append((v, sales_rows[pick]))
    unmatched_s = [s for i, s in enumerate(sales_rows) if i not in used]
    return pairs, unmatched_v, unmatched_s


# ------------------------------------------------------------------ 표시
def fmt_amt(v):
    return f"{v:+,.0f}" if isinstance(v, (int, float)) else str(v)


def note(items):
    """[(라벨, 값), ...] → '라벨 +10,000 / 라벨 -5,000' (0 은 생략)"""
    parts = []
    for label, val in items:
        if isinstance(val, (int, float)):
            if val:
                parts.append(f"{label} {fmt_amt(val)}")
        elif val not in (None, "", 0, "0"):
            parts.append(f"{label}({str(val).strip()})")
    return " / ".join(parts) if parts else "없음"


def status_of(diff):
    return "match" if diff == 0 else ("more" if diff > 0 else "less")
