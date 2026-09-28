# Waste Settlement System

## 0. 문서 목적

본 문서는 폐기물 월 정산 업무를 Django 기반 시스템으로 구축하기 위한 개발 명세서다.

시스템의 핵심 목표는 다음과 같다.

- 사내 DB의 계근정보를 기준으로 월별 정산 데이터를 생성한다.
- 정산 원본 데이터와 실제 작업 데이터를 분리한다.
- 운반/처리 업체 및 단가정보를 이용하여 업체별 정산금액을 자동 계산한다.
- 업체별 분배율을 이용하여 사업부별 비용을 자동 배분한다.
- 원 단위 반올림으로 발생하는 차액을 자동 보정한다.
- 공급가액과 부가세의 합계가 원 단위까지 정확하게 일치하도록 한다.
- 정산 과정과 계산 근거를 추적할 수 있도록 한다.
- 중간 저장 후 이전 작업을 이어서 수행할 수 있도록 한다.
- 최종 정산 결과를 지정된 보고서와 Excel 양식으로 생성한다.
- 향후 업체별 이메일 발송까지 확장할 수 있도록 한다.
- 외부 개발환경에서는 Mock Data를 사용하고 사내에서는 DB Adapter만 변경하여 실제 데이터와 연결할 수 있도록 한다.

---

# 1. 핵심 설계 원칙

## 1.1 원본 데이터와 작업 데이터 분리

사내 DB 데이터를 직접 수정하거나 계산 대상으로 계속 참조하지 않는다.

데이터 흐름은 다음과 같이 구성한다.

```text
사내 원본 DB
    ↓
Data Adapter
    ↓
Settlement Source Snapshot
    ↓
Settlement Working Data
    ↓
업체별 정산
    ↓
사업부 배분
    ↓
금액 보정
    ↓
검증
    ↓
정산 확정
    ↓
보고서 / Excel / Email
```

외부 개발환경에서는 사내 DB 대신 Mock Data Adapter를 사용한다.

```text
Mock Data
    ↓
Mock Adapter
    ↓
표준 데이터 구조
```

사내에서는 다음과 같이 변경한다.

```text
Company DB
    ↓
Company DB Adapter
    ↓
동일한 표준 데이터 구조
```

정산 Business Logic은 데이터 출처를 알 필요가 없어야 한다.

---

# 2. 정산 기간

정산 기준은 매월 다음과 같다.

```text
전월 21일 ~ 당월 20일
```

예:

```text
2026년 9월 정산

2026-08-21 ~ 2026-09-20
```

정산월을 선택하면 시스템이 정산기간을 자동 계산한다.

---

# 3. 전체 메뉴 구조

```text
폐기물 정산
│
├─ 월 정산
│
├─ 정산 이력
│
├─ 업체 관리
│
├─ 단가 관리
│
├─ 분배율 관리
│
├─ 보고서 관리
│
└─ 시스템 관리
```

일반적인 정산 작업은 `월 정산` 한 화면에서 진행한다.

업체, 단가, 분배율 등의 Master Data는 별도 관리 메뉴에서 관리한다.

---

# 4. 월 정산 Workflow

월 정산은 하나의 페이지에서 단계별로 진행한다.

```text
① 데이터 준비
      ↓
② 업체별 정산
      ↓
③ 사업부 배분
      ↓
④ 검증 및 확정
      ↓
⑤ 보고서 / Excel 생성
      ↓
⑥ 이메일 발송
```

UI 예시:

```text
[1 데이터 준비]
        ↓
[2 업체 정산]
        ↓
[3 사업부 배분]
        ↓
[4 검증/확정]
        ↓
[5 결과물 생성]
        ↓
[6 이메일]
```

현재 진행단계를 화면에서 명확하게 표시한다.

---

# 5. 정산 시작 화면

사용자가 `월 정산` 메뉴에 진입하면 바로 DB 데이터를 불러오지 않는다.

먼저 다음 선택 화면을 제공한다.

```text
폐기물 월 정산

────────────────────────────

진행 중인 정산

2026년 9월 정산
기간 : 2026-08-21 ~ 2026-09-20

현재 단계
사업부 배분

최종 저장
2026-09-21 09:32

[이어서 작업하기]

────────────────────────────

신규 정산 시작

정산월
[2026년 10월]

정산기간
2026-09-21 ~ 2026-10-20

[DB에서 신규 데이터 불러오기]
```

진행 중인 정산이 여러 개 존재할 경우 목록에서 선택할 수 있도록 한다.

---

# 6. 정산 상태

정산 Header에는 최소 다음 상태를 둔다.

```text
DRAFT
SOURCE_LOADED
VENDOR_CALCULATED
ALLOCATED
VALIDATED
CONFIRMED
REPORT_GENERATED
EMAIL_SENT
```

사용자 화면에서는 다음처럼 표시할 수 있다.

```text
작성 중
데이터 불러오기 완료
업체 정산 완료
사업부 배분 완료
검증 완료
정산 확정
보고서 생성 완료
메일 발송 완료
```

상태값을 통해 중단된 작업을 다시 이어갈 수 있어야 한다.

---

# 7. Step 1 - 데이터 준비

## 7.1 데이터 조회

정산월을 선택하면 시스템은 자동으로 정산기간을 계산한다.

예:

```text
정산월 : 2026-09

조회기간

2026-08-21 00:00:00
~
2026-09-20 23:59:59
```

Data Adapter를 통해 계근정보를 조회한다.

---

# 8. 표준 계근 데이터 모델

사내 DB의 실제 컬럼명과 무관하게 시스템 내부에서는 표준 컬럼을 사용한다.

초기 표준 모델 예시:

```text
source_id
weigh_date
waste_type
transport_company
disposal_company
weight
weight_unit
vehicle_no
slip_no
source_reference
```

실제 사내 DB 구조를 확인한 후 Mapping을 추가한다.

예:

```text
사내 DB                 Standard Model

MEASURE_DT        →     weigh_date
WASTE_NM          →     waste_type
TRANS_VENDOR      →     transport_company
PROC_VENDOR       →     disposal_company
NET_WEIGHT        →     weight
```

사내 DB의 실제 컬럼명은 Business Logic에 직접 사용하지 않는다.

---

# 9. Snapshot

DB에서 불러온 계근정보는 해당 정산의 Snapshot으로 저장한다.

예:

```text
settlement

id = 202609
settlement_month = 2026-09
period_start = 2026-08-21
period_end = 2026-09-20
```

Snapshot:

```text
settlement_source

settlement_id
source_id
weigh_date
waste_type
transport_company
disposal_company
weight
...
```

Snapshot 저장 이후 계산은 사내 원본 DB가 아니라 Snapshot을 기준으로 수행한다.

이를 통해 정산 당시 사용한 원본 데이터를 재현할 수 있도록 한다.

---

# 10. DB 데이터 재조회

이미 작업을 시작한 정산에서는 DB 데이터를 바로 덮어쓰지 않는다.

`DB 데이터 다시 확인` 기능을 제공한다.

비교 결과 예:

```text
현재 Snapshot : 342건
현재 DB       : 345건

추가     3건
변경     2건
삭제     0건
```

사용자가 변경 내용을 확인한 후 반영할 수 있도록 한다.

향후 구현 단계에서는 다음 정책을 적용한다.

```text
DB 최신 데이터
       ↓
Snapshot 비교
       ↓
Diff 생성
       ↓
사용자 확인
       ↓
Snapshot 갱신
       ↓
관련 계산 재실행
```

---

# 11. 업체 관리

업체 Master Data를 별도로 관리한다.

예시 필드:

```text
vendor_id
vendor_name
business_number

vendor_type
- TRANSPORT
- DISPOSAL
- BOTH

manager_name
manager_email

allocation_rule_id

active
created_at
updated_at
```

실제 사내 기존 업체 관리 기능이 존재하는 경우 신규 구현 전에 기존 기능 재사용 가능 여부를 확인한다.

---

# 12. 단가 관리

단가는 업체별 / 폐기물 종류별 / 업무 종류별 관리가 가능하도록 한다.

예:

```text
vendor_id
waste_type
price_type
unit_price
unit

valid_from
valid_to
```

`price_type` 예:

```text
TRANSPORT
DISPOSAL
```

단가는 기존 값을 수정하여 덮어쓰지 않는다.

기간별 이력을 유지한다.

예:

```text
A업체 / 폐액 / 120원 / ~2026-09-30
A업체 / 폐액 / 130원 / 2026-10-01~
```

과거 정산을 다시 조회해도 당시 적용된 단가를 확인할 수 있어야 한다.

---

# 13. Step 2 - 업체별 정산

기본 계산식:

```text
운반금액 = 계근량 × 운반단가

처리금액 = 계근량 × 처리단가
```

업무 특성상 실제 계산식 또는 단위 변환이 필요한 경우 Calculation Service에서 처리한다.

계산 결과에는 반드시 다음 정보를 Snapshot 형태로 남긴다.

```text
적용 업체
적용 폐기물
적용 계근량
적용 단가
단가 적용기간
계산 전 금액
반올림 결과
최종 금액
```

Master 단가가 나중에 변경되더라도 이미 확정된 정산금액이 변경되어서는 안 된다.

---

# 14. 분배율 관리

업체마다 사업부 분배 방식이 다르므로 분배율 Rule을 별도 관리한다.

예:

```text
RATE_01

Foundry             70%
반도체연구소          15%
CSS                  15%
```

다른 Rule:

```text
RATE_02

Foundry             90%
반도체연구소          10%
```

분배율 Master 구조:

```text
allocation_rule
----------------
id
rule_code
rule_name
valid_from
valid_to
active
```

Detail:

```text
allocation_rule_detail
----------------------
rule_id
business_unit
allocation_rate
```

분배율 합계는 반드시

```text
100%
```

가 되어야 한다.

100%가 아닌 경우 저장할 수 없도록 Validation 한다.

---

# 15. 업체와 분배율 연결

업체 Master에서 분배 Rule을 연결한다.

예:

```text
A업체 → RATE_01
B업체 → RATE_02
C업체 → RATE_01
```

필요할 경우 적용기간별 분배율 Rule 변경이 가능하도록 한다.

---

# 16. Step 3 - 사업부 배분

업체별 정산금액을 해당 업체에 설정된 분배율을 기준으로 사업부에 배분한다.

예:

```text
A업체 공급가액

10,001원

RATE_01

Foundry             70%
반도체연구소          15%
CSS                  15%
```

Raw 계산:

```text
Foundry             7,000.70
반도체연구소          1,500.15
CSS                  1,500.15
```

정산 결과는 원 단위 정수로 저장한다.

---

# 17. 금액 보정 알고리즘

독립적인 반올림만 수행하면 전체 금액과 사업부별 금액 합계가 일치하지 않을 수 있다.

따라서 금액 배분에는 `Largest Remainder Method` 방식의 보정 알고리즘을 적용한다.

## 기본 알고리즘

1. 정확한 배분금액 계산
2. 각 금액의 정수 부분 계산
3. 정수 부분의 합계 계산
4. 원금과의 차액 계산
5. 소수점 잔여값이 큰 순서대로 1원씩 배분
6. 최종 합계 검증

예:

```text
총 금액

10,001원

정확 계산

Foundry      7,000.70
연구소       1,500.15
CSS          1,500.15
```

1차 정수:

```text
Foundry      7,000
연구소       1,500
CSS          1,500

합계        10,000
```

차액:

```text
1원
```

잔여값이 가장 큰 Foundry에 1원을 배분한다.

최종:

```text
Foundry      7,001
연구소       1,500
CSS          1,500

합계        10,001
```

---

# 18. 동률 처리

소수점 잔여값이 동일한 경우 결과가 실행할 때마다 달라져서는 안 된다.

따라서 고정된 Tie-breaker를 사용한다.

예:

```text
1. 소수점 잔여값 DESC
2. 분배율 DESC
3. business_unit 고정 sort_order ASC
```

이를 통해 동일 입력은 항상 동일한 결과를 생성해야 한다.

---

# 19. 보정 기록

단순히 최종 결과만 저장하지 않는다.

다음을 기록한다.

```text
raw_amount
base_amount
adjustment_amount
final_amount
```

예:

```text
Foundry

raw        7000.70
base       7000
adjustment +1
final      7001
```

향후 사용자가 왜 특정 사업부에 1원이 추가되었는지 확인할 수 있어야 한다.

---

# 20. 부가세

기본 부가세율은 현재 10%를 기준으로 한다.

단, Business Logic에 `0.1`을 여러 곳에 Hard Coding하지 않는다.

시스템 설정값 또는 Tax Service를 통해 관리한다.

```text
VAT_RATE = 10%
```

기본 처리 흐름:

```text
업체 공급가액 확정
       ↓
업체 전체 부가세 계산
       ↓
사업부 공급가액 배분
       ↓
사업부 부가세 배분
       ↓
합계 검증
```

부가세 배분에서도 동일한 원 단위 보정 알고리즘을 사용한다.

---

# 21. 정산 필수 검증

정산 확정 전에 Validation Engine을 실행한다.

최소 검증 항목:

```text
계근정보 존재 여부

업체 미매칭 여부

단가 미등록 여부

분배율 미등록 여부

분배율 합계 = 100%

사업부 공급가액 합계
= 업체 공급가액

사업부 부가세 합계
= 업체 부가세

사업부 최종금액 합계
= 업체 최종금액

전체 업체 합계
= 전체 정산금액
```

검증 실패 시 정산 확정을 차단한다.

---

# 22. Step 4 - 검증 화면

예:

```text
2026년 9월 정산 검증

✓ 계근 데이터       342건
✓ 업체 미매칭         0건
✓ 단가 미등록         0건
✓ 분배율 미등록       0건
✓ 분배율 오류         0건
✓ 공급가액 차액        0원
✓ 부가세 차액          0원
✓ 최종금액 차액        0원


공급가액     182,394,215원
부가세        18,239,422원

총 정산금액  200,633,637원


[정산 확정]
```

오류 발생 시 어떤 데이터에서 문제가 발생했는지 확인할 수 있어야 한다.

예:

```text
⚠ B업체 / 폐유

처리단가가 등록되어 있지 않습니다.
```

가능하면 오류 항목에서 해당 관리화면으로 이동할 수 있도록 한다.

---

# 23. 정산 확정

정산 확정 이후에는 일반적인 수정이 불가능하도록 한다.

```text
CONFIRMED
```

상태의 정산을 수정해야 할 경우 향후 다음 기능을 고려한다.

```text
확정 취소
↓
사유 입력
↓
재계산
↓
재확정
```

확정/취소 이력은 Audit Log에 기록한다.

---

# 24. Step 5 - 보고서 생성

보고서는 회사에서 사용하는 별도의 정해진 양식이 존재한다.

현재 개발 단계에서는 임시 보고서 Template을 사용한다.

중요한 설계 원칙은 다음과 같다.

```text
Settlement Data
       ↓
Report Context
       ↓
Report Template
       ↓
Report File
```

Business Logic에서 보고서 Layout을 직접 생성하지 않는다.

향후 실제 회사 보고서 양식이 제공되면 Template Layer만 교체할 수 있어야 한다.

---

# 25. 임시 보고서

개발용 보고서는 다음 수준으로 구현한다.

```text
폐기물 월 정산 결과

정산월
정산기간

총 계근량

총 공급가액
총 부가세
총 정산금액

사업부별 금액

업체별 금액

검증 결과
```

본 양식은 개발 및 기능 검증을 위한 임시 양식이며 최종 운영 양식이 아니다.

실제 보고서 양식 제공 후 별도 Mapping 작업을 수행한다.

---

# 26. Excel 생성

회사에서 사용하는 별도의 Excel 정산 양식이 존재한다.

따라서 여러 개의 임의 Sheet를 생성하지 않는다.

최종 목표:

```text
기존 회사 Excel Template
        ↓
지정된 1개 Sheet
        ↓
정산 결과 Mapping
        ↓
완성된 Excel 생성
```

현재 개발 단계에서는 하나의 임시 Sheet를 생성한다.

예:

```text
정산결과
```

Sheet에는 기능 검증을 위해 다음 데이터를 포함할 수 있다.

```text
업체
사업부
계근량
적용단가
공급가액
분배율
배분 공급가액
부가세
총금액
보정금액
```

향후 실제 Excel 양식이 제공되면 셀 위치 및 데이터 Mapping을 별도 정의한다.

---

# 27. Excel Template Adapter

Excel 생성 로직도 Business Logic과 분리한다.

예:

```text
Settlement Result
       ↓
Excel Export Context
       ↓
Excel Template Adapter
       ↓
회사 정산 Template
```

향후 양식이 변경되어도 정산 계산 로직에는 영향을 주지 않도록 한다.

---

# 28. Step 6 - 이메일

이메일 기능은 정산 및 보고서 기능 안정화 이후 구현한다.

업체정보에서 다음 항목을 관리할 수 있도록 준비한다.

```text
정산 담당자
TO
CC
메일 사용 여부
```

메일 흐름:

```text
정산 확정
   ↓
보고서 / Excel 생성
   ↓
업체별 Mail 생성
   ↓
메일 미리보기
   ↓
사용자 승인
   ↓
발송
   ↓
발송이력 저장
```

초기 버전에서는 완전 자동발송을 하지 않는다.

금액 관련 업무이므로 사용자가 최종 내용을 확인한 후 발송하도록 한다.

---

# 29. 정산 이력

과거 정산을 조회할 수 있도록 한다.

예:

```text
2026-09   확정   200,633,637원
2026-08   확정   195,321,200원
2026-07   확정   203,112,320원
```

상세화면에서는 다음 내용을 조회한다.

```text
원본 Snapshot
업체별 정산
적용 단가
적용 분배율
사업부 배분
원 단위 보정
부가세
검증 결과
보고서
Excel
Email 이력
```

---

# 30. 권장 데이터 모델

초기 기준:

```text
Vendor

VendorPrice

AllocationRule
AllocationRuleDetail
VendorAllocationRule

Settlement
SettlementSource

SettlementVendor
SettlementAllocation
SettlementAdjustment

SettlementValidation

SettlementReport
SettlementEmail

SettlementAuditLog
```

실제 구현 전 기존 Django Model과 비교하여 중복 테이블 생성을 방지한다.

---

# 31. Snapshot 정책

정산의 재현성을 위해 Master Data도 필요한 값을 Snapshot으로 저장한다.

예를 들어 정산 당시:

```text
A업체
폐액 처리단가
120원
```

이었다면 이후 Master 단가가 130원으로 변경되어도 과거 정산에는

```text
120원
```

이 유지되어야 한다.

분배율도 동일하다.

```text
정산 당시

RATE_01

Foundry 70
연구소 15
CSS 15
```

이후 RATE_01이 변경되어도 과거 정산 결과에는 영향을 주지 않는다.

---

# 32. Audit

금액을 다루는 시스템이므로 주요 작업을 기록한다.

최소 기록:

```text
정산 생성
DB 데이터 불러오기
DB 데이터 재반영
단가 적용
재계산
사업부 배분
금액 보정
정산 확정
확정 취소
보고서 생성
Excel 생성
메일 발송
```

기본 Audit 정보:

```text
action
settlement_id
user
timestamp
before
after
reason
```

---

# 33. 권장 Service 구조

Django View 내부에 계산 로직을 직접 작성하지 않는다.

예:

```text
services/

settlement_service.py
price_service.py
allocation_service.py
tax_service.py
validation_service.py

report_service.py
excel_service.py
email_service.py

data_source/
    base.py
    mock_source.py
    company_db_source.py
```

View는 Service를 호출하는 역할에 집중한다.

---

# 34. Data Adapter Interface

예:

```python
class WeighingDataSource:

    def get_weighing_data(
        self,
        start_date,
        end_date
    ):
        raise NotImplementedError
```

외부 개발:

```python
MockWeighingDataSource
```

사내:

```python
CompanyDBWeighingDataSource
```

두 Adapter 모두 동일한 Standard Model을 반환해야 한다.

---

# 35. 환경별 차이

```text
외부 개발환경

Mock 계근정보
Mock 업체
Mock 단가
Mock 분배율
Mock User
Email 비활성
임시 Report
임시 Excel
```

사내 운영환경:

```text
사내 DB 계근정보
실제 업체
실제 단가
실제 분배율
사내 인증
사내 Email
회사 Report Template
회사 Excel Template
```

Business Logic은 동일하게 유지한다.

---

# 36. 구현 단계

## Phase 1

기본 Framework

```text
Settlement Model
Mock Data
Data Adapter
정산 시작 화면
Snapshot
업체 관리
단가 관리
업체별 정산
```

## Phase 2

배분 Engine

```text
분배율 관리
업체-분배율 Mapping
사업부 배분
원 단위 보정
부가세 계산
부가세 보정
```

## Phase 3

Workflow

```text
단계별 정산 화면
중간 저장
이어하기
Validation
정산 확정
정산 이력
Audit
```

## Phase 4

Output

```text
임시 Report
Excel 1 Sheet
파일 생성
정산 결과 다운로드
```

## Phase 5

사내 적용

```text
기존 Django 분석
기존 기능 Mapping
Company DB Adapter
실제 업체/단가 연결
사내 인증 연결
실제 Report 양식 적용
실제 Excel 양식 적용
```

## Phase 6

Email

```text
업체 담당자 관리
Mail Template
첨부파일 생성
미리보기
승인
발송
발송이력
```

---

# 37. 개발 시 금지사항

다음 방식으로 구현하지 않는다.

```text
X View에 SQL과 계산식 직접 작성

X 회사 DB 컬럼명을 Business Logic에 직접 사용

X Master 단가 변경 시 과거 정산금액도 변경

X Master 분배율 변경 시 과거 정산금액도 변경

X 각 사업부 금액을 단순 round() 후 합계 검증 없이 저장

X 원 단위 오차를 임의 사업부에 무조건 추가

X 부가세를 사업부별 독립 계산 후 합계 검증 생략

X DB 재조회 시 기존 Snapshot 무조건 덮어쓰기

X 확정된 정산을 이력 없이 수정

X Report Layout을 Settlement Service 안에 구현

X Excel 셀 Mapping을 Calculation Service에 구현

X Email 즉시 자동발송
```

---

# 38. 중요 테스트

금액 계산에는 반드시 자동 테스트를 작성한다.

특히 다음 Case를 포함한다.

```text
1원
10원
101원
10,001원
매우 큰 금액

33.33 / 33.33 / 33.34

70 / 15 / 15

90 / 10

잔여값 동률

업체 1개
업체 여러 개

VAT 계산 시 소수점 발생

사업부 공급가액 합계 검증

사업부 VAT 합계 검증

최종 합계 검증
```

모든 테스트에서 다음 조건을 만족해야 한다.

```text
SUM(사업부 공급가액)
=
업체 공급가액

SUM(사업부 VAT)
=
업체 VAT

SUM(사업부 최종금액)
=
업체 최종금액
```

---

# 39. 향후 실제 양식 적용

현재 Report와 Excel은 개발용 임시 Template을 사용한다.

실제 회사 양식 확보 후 다음 작업을 별도로 수행한다.

### Report

```text
회사 Report 분석
↓
필드 Mapping
↓
Report Template 구현
↓
기존 임시 Template 교체
```

### Excel

```text
회사 Excel Template 분석
↓
대상 Sheet 확인
↓
입력 Cell / Table 영역 확인
↓
Settlement Result Mapping
↓
Template 기반 Excel 생성
```

정산 Engine 자체는 변경하지 않는 것을 원칙으로 한다.

---

# 40. 최종 목표 Architecture

```text
             ┌───────────────────────┐
             │     Company DB        │
             └──────────┬────────────┘
                        │
                 Data Adapter
                        │
             ┌──────────▼────────────┐
             │ Settlement Snapshot   │
             └──────────┬────────────┘
                        │
                Settlement Engine
                        │
       ┌────────────────┼────────────────┐
       │                │                │
       ▼                ▼                ▼
   Price Engine   Allocation Engine   Tax Engine
                       │
                       ▼
                Adjustment Engine
                       │
                       ▼
                Validation Engine
                       │
                       ▼
                 CONFIRMED DATA
                       │
           ┌───────────┼───────────┐
           ▼           ▼           ▼
         Report       Excel       Email
        Adapter      Adapter      Service
```

핵심 원칙:

> 데이터 출처, 계산 로직, 출력 양식을 서로 분리한다.

이를 통해 외부 Mock 환경에서 개발한 기능을 사내 Django 환경으로 최대한 적은 변경으로 이식할 수 있도록 한다.