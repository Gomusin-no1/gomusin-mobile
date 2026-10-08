# 통신사 변경서식

오늘 업무, 달력의 선택일, 업무 알림, 고객 상세 및 약속 수정에서 **서류 출력**을 누르면
판매정보를 입력한 공식 PDF가 열립니다. PDF 뷰어에서 인쇄합니다.
요금제 변경과 부가서비스 해지를 지원하며, 회선 전체 해지/인터넷 해지에는 사용하지 않습니다.
누락되거나 서식 칸에 들어가지 않는 정보는 출력 전에 확인 화면에서 보완합니다.
확인 화면의 수정값은 해당 PDF에만 적용됩니다. 판매정보를 저장하려면 판매 수정 화면을 사용합니다.

- 고객명/생년월일: 해당 판매 건. 주민등록번호 뒷자리는 수집하거나 채우지 않습니다.
- 회선번호: 개통번호 우선, 미등록이면 판매의 고객 휴대전화 번호.
- 요금제: 현재 요금제와 변경할 요금제. 부가서비스는 해당 약속에 지정된 서비스만 선택.
- 변경 예정일: 고객약속의 최신 날짜. 서식 신청일: PDF 생성일.
- 서명, 대리인 관계, 동의/약정 선택란: 자동 작성하지 않습니다.
- PDF 생성은 감사기록에 남지만 고객약속의 완료 상태를 변경하지 않습니다.
- 생성 PDF는 메모리에서 반환하고 응답은 `private, no-store`입니다.
  회사/지점 권한을 확인하며, 고객정보는 파일명/감사기록에 넣지 않습니다.

## 원본과 버전

2026-10-08 공식 사이트에서 확인한 원본입니다. 자동 갱신하지 않습니다.
PDF 원본을 변경하면 `change_forms.py`의 좌표, 페이지 수, SHA-256도 검증 후 함께 갱신해야 합니다.
SHA가 다르면 잘못된 위치에 인쇄하지 않고 출력을 중단합니다. 약관을 포함한 원본 전체 페이지를 보존합니다.

| 통신사 | 원본 | 확인 버전 | 공식 출처 |
| --- | --- | --- | --- |
| SKT | `originals/skt-change.pdf` | 2026.07, 3쪽 | https://www.tworld.co.kr/web/support/document (변경 신청서) |
| KT | `originals/kt-wireless.pdf` | 2026.10 Ver1.0, 3쪽 | https://help.kt.com/serviceinfo/FormdownloadInfo.do (KT 무선 신청서) |
| LG U+ | `originals/lgu-change.pdf` | 바코드 20260610, 4쪽 | https://www.lguplus.com/support/service/need-docs (서비스 변경 신청서(모바일)) |

SKT 직접 다운로드: https://www.tworld.co.kr/poc/center/info/download/change.pdf

KT 공식 다운로드 요청: `POST https://help.kt.com/serviceinfo/FormdownloadInfo.json`,
`prgIdx=9`, `fileType=1`, `fileName=KT무선신청서_v1.32(260930).pdf`.
LG U+ 다운로드 파일명: `[지류서식]260608 모바일 서비스 변경 신청서_4p.pdf`.

원본 서식은 각 통신사의 저작물입니다. 문구 및 약관을 변경하지 않고 신청정보를 덧입력합니다.
한글 글꼴은 NanumGothic Regular (SIL Open Font License, `fonts/OFL.txt`)를 포함합니다.
글꼴 출처: https://github.com/google/fonts/tree/main/ofl/nanumgothic

## 배포와 검증

기존 Flask 앱에 `pip install -r requirements.txt` 후 앱을 재시작합니다.
`carrier_forms/`와 `change_forms.py`, 변경된 템플릿을 앱과 함께 배포해야 합니다.
DB 스키마 변경이나 데이터 마이그레이션은 없습니다.
`python -m unittest discover -s tests`로 동작/권한/누락정보/페이지 보존을 검증할 수 있습니다.
운영 확인: 실제 변경 예정 판매 한 건에서 서류 출력 → 고객/회선/요금제/날짜와 인쇄 미리보기 확인.
서류 생성만으로 완료 처리되지 않는지도 확인합니다.
