"""Fill the unmodified carrier PDFs with an embedded Korean-font overlay."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parent / 'carrier_forms'
FONT = 'CarrierNanumGothic'
pdfmetrics.registerFont(TTFont(FONT, str(ROOT / 'fonts/NanumGothic-Regular.ttf')))
PRINTABLE_TASK_TYPES = ('요금제 변경', '부가서비스 해지')
TEMPLATES = {
    'SKT': dict(file='skt-change.pdf', pages=3, version='2026.07',
                sha256='8bf1ccab08cdcda7f0ffeb0672eafb3f8b62a74b41510fc106446e47ff1d5f44',
                title='변경 신청서', source='https://www.tworld.co.kr/web/support/document'),
    'KT': dict(file='kt-wireless.pdf', pages=3, version='2026.10 Ver1.0',
               sha256='cad51993b4ca254e9c014f62f71b1242bbb7c3339c1a7aaa3dcf7433af87719c',
               title='KT 무선 신청서', source='https://help.kt.com/serviceinfo/FormdownloadInfo.do'),
    'LG U+': dict(file='lgu-change.pdf', pages=4, version='20260610',
                  sha256='0aaef375d42161c031893a2aabbc7b31b0a469cfc0c56600eb58be58389e1476',
                  title='서비스 변경 신청서(모바일)', source='https://www.lguplus.com/support/service/need-docs'),
}


class FormInputError(ValueError):
    pass


class TemplateUnavailable(RuntimeError):
    pass


def normalize_carrier(value):
    key = re.sub(r'\s+', '', str(value or '')).upper()
    return {'SK': 'SKT', 'SKT': 'SKT', 'SK텔레콤': 'SKT', 'KT': 'KT',
            'LG': 'LG U+', 'LGU+': 'LG U+', 'LGU': 'LG U+',
            'LG유플러스': 'LG U+', 'LGU플러스': 'LG U+'}.get(key)


def can_print_change_form(task):
    return bool(task.sale_id and task.task_type in PRINTABLE_TASK_TYPES and task.status != '취소')


@dataclass(frozen=True)
class ChangeForm:
    carrier: str
    task_type: str
    name: str
    birth: str
    phone: str
    current_plan: str
    change: str
    due_date: date
    application_date: date


def validate_form(carrier, task_type, values, *, due_date, application_date=None):
    carrier = normalize_carrier(carrier)
    if carrier not in TEMPLATES:
        raise FormInputError('이 통신사의 공식 변경서식은 아직 지원하지 않습니다. 판매정보의 통신사를 확인해 주세요.')
    if task_type not in PRINTABLE_TASK_TYPES:
        raise FormInputError('요금제 변경 또는 부가서비스 해지 업무에서 출력할 수 있습니다.')
    cleaned = {}
    for key, label in [('name', '고객명'), ('birth', '생년월일'), ('phone', '변경할 회선번호'),
                       ('current_plan', '현재 요금제'), ('change', '변경할 요금제' if task_type == '요금제 변경' else '해지할 부가서비스')]:
        value = str(values.get(key) or '').strip()
        if not value and key != 'current_plan':
            raise FormInputError(f'{label}을(를) 입력해 주세요.')
        if len(value) > 100 or any(ord(c) < 32 for c in value):
            raise FormInputError(f'{label}은(는) 100자 이내의 한 줄로 입력해 주세요.')
        if any(ord(c) not in pdfmetrics.getFont(FONT).face.charToGlyph for c in value):
            raise FormInputError(f'{label}에 서식에서 표시할 수 없는 문자가 있습니다.')
        cleaned[key] = value
    birth = re.sub(r'[-./\s]', '', cleaned['birth'])
    try:
        if not re.fullmatch(r'(?:[0-9]{6}|[0-9]{8})', birth):
            raise ValueError()
        datetime.strptime(birth, '%y%m%d' if len(birth) == 6 else '%Y%m%d')
    except ValueError:
        raise FormInputError('생년월일은 유효한 6자리 또는 8자리 날짜로 입력해 주세요.') from None
    phone = re.sub(r'[-\s()]', '', cleaned['phone'])
    if not re.fullmatch(r'01[016789][0-9]{7,8}', phone):
        raise FormInputError('변경할 휴대전화 회선번호를 확인해 주세요.')
    cleaned.update(birth=birth, phone=f'{phone[:3]}-{phone[3:-4]}-{phone[-4:]}')
    if not isinstance(due_date, date):
        raise FormInputError('고객약속의 변경 예정일을 먼저 등록해 주세요.')
    return ChangeForm(carrier, task_type, **cleaned, due_date=due_date,
                      application_date=application_date or datetime.now(timezone(timedelta(hours=9))).date())


def _text(canvas, page_height, value, x, top, width, size=10, min_size=7):
    """Coordinates are points, measured from the top; top is the text baseline."""
    if not value:
        return
    measured = pdfmetrics.stringWidth(value, FONT, size)
    size = min(size, size * width / measured) if measured else size
    if size < min_size:
        raise FormInputError('입력한 내용이 공식 서식의 칸보다 깁니다. 출력정보에서 내용을 확인해 주세요.')
    canvas.setFont(FONT, size)
    canvas.drawString(x, page_height - top, value)


def _overlay(canvas, height, data, page):
    def write(value, x, top, width, size=10, min_size=7):
        _text(canvas, height, value, x, top, width, size, min_size)

    due = data.due_date.isoformat()
    applied = data.application_date
    is_plan = data.task_type == '요금제 변경'
    if data.carrier == 'SKT' and page == 0:
        write('요금제' if is_plan else '부가서비스', 77, 59, 87, 14)
        write(data.phone, 150, 101, 175)
        write(data.name, 405, 101, 148)
        write(data.birth, 204, 122, 54, 9)
        canvas.circle(153, height - 119, 1.7, stroke=0, fill=1)
        canvas.setLineWidth(1)
        canvas.line(83, height - 76, 85, height - 79)
        canvas.line(85, height - 79, 89, height - 74)
        if is_plan:
            write(data.change, 117, 176, 432, 11)
        else:
            write('해지: ' + data.change, 241, 245, 230, 9)
        write(f'{data.task_type} 예정일: {due}', 64, 620, 480)
        if is_plan:
            write('변경 전 요금제: ' + (data.current_plan or '미등록'), 64, 636, 480, 9)
        write(str(applied.year), 159, 804, 32)
        write(str(applied.month), 222, 804, 18)
        write(str(applied.day), 270, 804, 18)
    elif data.carrier == 'KT' and page == 0:
        write(data.name, 187, 293, 116)
        write(data.birth, 348, 293, 170)
        write(data.phone, 160, 343, 178)
        if is_plan:
            write(data.change, 160, 361, 181)
        write(f'{data.task_type} 예정일: {due}', 160, 489, 396, 9)
        if is_plan:
            write('변경 전 요금제: ' + (data.current_plan or '미등록'), 160, 502, 396, 8)
        write(applied.isoformat(), 78, 812, 130)
    elif data.carrier == 'KT' and page == 2 and not is_plan:
        write(data.change, 125, 40, 435)
    elif data.carrier == 'LG U+':
        if page == 0:
            write(data.name, 133, 121, 112)
            write(data.birth, 309, 121, 106)
            write(data.phone, 470, 121, 98, 9)
            write(data.change, 195, 237 if is_plan else 265, 190 if is_plan else 368)
            write(f'{data.task_type} 예정일: {due}', 88, 513, 472)
            if is_plan:
                write('변경 전 요금제: ' + (data.current_plan or '미등록'), 88, 530, 472, 9)
        elif page == 1:
            write(str(applied.year), 68, 782, 28)
            write(str(applied.month), 142, 782, 16)
            write(str(applied.day), 207, 782, 16)


def render_change_form(data):
    template = TEMPLATES[data.carrier]
    try:
        original = (ROOT / 'originals' / template['file']).read_bytes()
    except OSError as exc:
        raise TemplateUnavailable('공식 서식 파일을 읽을 수 없습니다.') from exc
    if sha256(original).hexdigest() != template['sha256']:
        raise TemplateUnavailable('공식 서식의 버전과 입력 위치가 일치하지 않습니다.')
    reader = PdfReader(BytesIO(original))
    if len(reader.pages) != template['pages']:
        raise TemplateUnavailable('공식 서식의 페이지 구성이 변경되었습니다.')
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    for index, page in enumerate(writer.pages):
        overlay = BytesIO()
        height = float(page.mediabox.height)
        canvas = Canvas(overlay, pagesize=(float(page.mediabox.width), height))
        _overlay(canvas, height, data, index)
        canvas.showPage()
        canvas.save()
        page.merge_page(PdfReader(BytesIO(overlay.getvalue())).pages[0])
    # No customer identifiers in the filename or PDF metadata.
    writer.add_metadata({'/Title': f'{data.carrier} {data.task_type}', '/Author': 'TrustFlow'})
    result = BytesIO()
    writer.write(result)
    result.seek(0)
    return result
