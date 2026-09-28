# TrustMap Synology NAS 이전 준비

상태(2026-09-28): DS923+에서 앱 이미지 빌드, PostgreSQL 17 최신 운영 DB 복원, 전체 테이블 건수 일치 확인. 외부 HTTPS·도메인 전환은 아직 수행하지 않음.

## 설치 전 확인
- NAS 모델/CPU/메모리, DSM 버전 및 Container Manager 지원 확인.
- NAS 디스크 여유 공간, 복구 가능한 별도 백업 위치, 정전/회선 장애 대응 확인.
- 실제 원본: Render srv-daluaue7bikc73ak99e0 / test/company-account-login.
- PostgreSQL 서버의 실제 메이저 버전을 조회하고 동일 버전 이미지 사용. 이 구성의 데이터 경로는 PostgreSQL 17 이하용이다. 18 이상이면 공식 이미지의 볼륨 경로에 맞게 먼저 수정한다.
- NAS가 외부 HTTPS 서비스를 제공할 수 있는지 확인. QuickConnect 관리 화면 접속만으로 trustflow.co.kr 웹 서비스 연결이 보장되지는 않는다.

## 비밀 설정
저장소 루트의 .env.nas는 NAS 내부에서만 만들고 권한을 제한한다. Git에 저장하지 않는다.
필수: POSTGRES_IMAGE, NAS_DB_PASSWORD, NAS_DATABASE_URL, SECRET_KEY.
NAS_DATABASE_URL은 postgresql+psycopg://trustmap:<URL-encoded password>@db:5432/trustmap 형식.
SECRET_KEY와 메일/문자 관련 기존 환경설정은 보안 경로로 옮기고 로그나 채팅에 출력하지 않는다.
ADMIN_USERNAME/ADMIN_PASSWORD로 기존 계정을 새로 덮어쓰지 않는다.

## 데이터 복원 및 검증
1. 새 비공개 NAS 프로젝트를 만들고 db만 시작한다.
   docker compose --env-file .env.nas -f deploy/nas/compose.yaml up -d db
2. 실제 운영 DB에서 최신 pg_dump(custom format)를 생성한다. 원본과 대상의 DB 버전 확인 후 pg_restore --no-owner --no-acl --exit-on-error로 **빈 NAS DB에만** 복원한다.
3. DB 외부 첨부파일이 있는지도 확인하고 함께 복사한다. 9월 21일 JSON ZIP은 참고 자료이며 최신 운영 DB 대신 사용하지 않는다.
4. 복원 전후 회사·지점·직원·고객·예약·판매·재고 건수, PK/시퀀스, 예약 날짜·상태, 첨부파일을 대조한다.
5. web을 시작하고 NAS의 HTTPS 역방향 프록시를 127.0.0.1:18080에 연결한다. DB 포트는 외부에 공개하지 않는다.
6. 관리/직원 로그인과 지점 격리, 오늘·기한초과 예약, 파일 접근을 비공개 상태에서 검증한다. 대표에게 테스트메일을 발송하지 않는다.

## 전환
- 실제 영업 쓰기 작업을 잠시 멈춘 뒤 최종 백업/복원 및 건수 대조를 수행한다.
- TLS 인증서와 NAS 외부 HTTPS 접근을 확인한 후 도메인을 전환한다.
- NAS에서 새 쓰기가 시작된 뒤 Render로 되돌릴 경우 데이터를 먼저 동기화해야 한다. 이전 DB로 무조건 전환하지 않는다.
- NAS 운영과 예약 데이터 검증이 끝날 때까지 Render/원본 DB를 삭제하거나 중지하지 않는다.
- NAS 자동 백업 및 별도 장치/위치 복구 테스트 후 유료 서비스 해지 여부를 결정한다.

## 검증 범위
NAS에서 `trustmap-nas:preflight` 빌드와 의존성 import, `trustmap-nas:migration` 인증서 포함 빌드 및 TLS verify-full 연결 검증 완료. 고객 1,036 / 고객 일정 1,172 / 재고 592 / 계정 4건의 복사본을 포함하여 전체 테이블 건수 일치. 이는 특정 시점 복사본이며 운영 전환 전 최종 동기화가 필요하다.

복원 컨테이너는 일회성이다. 성공 후 정지되는 것이 정상이다. 기존 복원본은 덮어쓰지 않는다. `Dockerfile.migration`에서 ca-certificates를 설치해야 하며 인증서 검증을 해제하지 않는다. `verify-stage.py`는 새 계정이나 실제 이메일을 만들지 않고 비공개 앱 상태를 검사한다.

2026-09-28 NAS 앱 기본 검사 통과: /health 200(57ms), /login 200(245ms), /signup 200(152ms), 미로그인 /customers·/manager는 /login으로 302. Flask test client 내부 측정으로 외부 접속 지연을 의미하지 않는다. 테스트 발송/계정 생성 없음.

NAS 회귀 검사: 105개 중 104개 통과, 비공개 원본이 필요한 1개 제외, 31.024초. 운영 DB 연결 없이 network_mode=none 및 메모리 SQLite로 실행. 외부 fild.synology.me HTTPS는 인증서 신뢰 오류가 발생했고 DSM에는 해당 도메인 인증서가 없었다. 새 인증서 발급 화면만 준비했으며 아직 발급/외부 앱 공개/운영 도메인 변경은 하지 않았다.

2026-09-28 NAS DDNS(fild.synology.me) 인증서 발급 성공: 만료 2026-12-27. 대표 승인 이메일로 발급했으며 trustflow.co.kr 운영 인증서와는 별개다.
NAS 시스템 기본 웹 인증서에 fild.synology.me 적용 후 외부 HTTPS 접속이 인증서 오류 없이 Synology Web Station 기본 페이지를 반환함을 확인했다. 아직 TrustMap 역방향 프록시와 운영 DNS 전환은 적용하지 않았다.
