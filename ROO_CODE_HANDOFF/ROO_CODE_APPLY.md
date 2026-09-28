# Roo Code 작업 지시서 — 폐기물 월 정산 시스템 이관

## 목표

GitHub `https://github.com/jundol-son/environmental-portal.git`의 `main` 브랜치에 있는 폐기물 월 정산 기능을 사내 Django 프로젝트에 적용한다.

- 기준 기능 커밋: `ab9c724` (`feat: add complete waste settlement workflow`)
- 먼저 `git fetch origin` 후 위 커밋의 파일을 확인한다.

## 권장 폴더 배치

기준 구현과 사내 프로젝트를 같은 폴더에 섞지 않는다. Roo Code에서는 두 폴더의 **상위 폴더**를 workspace로 연다.

```text
roo_workspace/
├─ internal_project/   # 실제 적용 대상인 사내 Django 프로젝트
└─ test/               # 이 Git 저장소를 받은 읽기 전용 기준 구현
```

예시:

```powershell
mkdir roo_workspace
cd roo_workspace
git clone https://github.com/jundol-son/environmental-portal.git test
cd test
git checkout ab9c724
```

`test`는 Django 앱 이름이 아니며 `INSTALLED_APPS`에 추가하지 않는다. Roo Code가 비교·복사할 기준 폴더일 뿐이다. migration, 테스트, 서버 실행은 모두 `internal_project`에서 수행한다.

기능 범위:

- 사내 DB 계근 데이터 Snapshot
- 월 정산 6단계 Workflow
- 업체·기간별 단가·업체별 분배율 관리
- 업체별 정산, 사업부 배분, 원 단위/VAT 보정
- 검증, 확정, 완료 정산 재오픈, 추가 수동 보정
- 보고서와 Excel
- 업체별 이메일 미리보기, 사용자 승인 발송, 발송이력
- Audit Log와 정산 이력

## Roo Code에게 그대로 전달할 요청

workspace에는 `internal_project`와 `test`가 나란히 있다. `test`는 기준 구현이므로 수정하지 말고, `internal_project`만 변경해 줘. 아래 지시를 순서대로 실행하고, 안전하게 진행 가능한 작업은 중간에 묻지 말고 끝까지 수행한 후 결과를 보고해 줘.

1. `internal_project`를 적용 대상, `test`를 기준 구현으로 확정하고 각각의 절대경로를 기록한다. 경로가 불명확하면 파일 변경을 시작하지 않는다.
2. `internal_project`의 Git 상태와 백업 지점을 확인한다. 기존 미커밋 변경, 운영 설정, 비밀정보, 기존 DB 데이터는 삭제하거나 덮어쓰지 않는다.
3. `test`의 다음 파일을 기준 구현으로 사용한다.
   - `test/wastes/admin.py`
   - `test/wastes/forms.py`
   - `test/wastes/models.py`
   - `test/wastes/settlement_services.py`
   - `test/wastes/urls.py`
   - `test/wastes/views.py`
   - `test/wastes/tests.py`
   - `test/wastes/templates/wastes/master_management.html`
   - `test/wastes/templates/wastes/settlement_detail.html`
   - `test/wastes/templates/wastes/settlement_history.html`
   - `test/wastes/templates/wastes/settlement_home.html`
   - `test/wastes/templates/wastes/settlement_report.html`
   - `test/wastes/templates/wastes/settlement_system.html`
   - `test/wastes/migrations/0002_allocationrule_settlement_settlementauditlog_and_more.py`
   - `test/wastes/migrations/0003_settlementvendor_allocation_rule_code_and_more.py`
   - `test/wastes/migrations/0004_settlementemail.py`
   - 선택 사항: `test/scripts/seed_wastes.py`는 개발·검증 환경에서만 사용한다.
4. `internal_project/wastes`가 기준 구현과 같은 기반이면 위 파일을 대응 경로에 덮어쓴다. 기존 사내 코드가 다르면 URL, 모델, 뷰, 권한을 먼저 비교한 뒤 기능 단위로 병합한다. `internal_project/wastes/services.py`와 기존 배출내역 화면은 제거하지 않는다.
5. `internal_project/config/settings.py` 전체를 덮어쓰지 말고 다음 설정만 기존 환경변수 방식에 맞춰 병합한다.

   ```python
   WASTE_SETTLEMENT_EMAIL_BACKEND = os.environ.get(
       'WASTE_SETTLEMENT_EMAIL_BACKEND',
       'django.core.mail.backends.console.EmailBackend',
   )
   WASTE_SETTLEMENT_FROM_EMAIL = os.environ.get(
       'WASTE_SETTLEMENT_FROM_EMAIL',
       'waste-settlement@localhost',
   )
   ```

   개발·검증 중에는 console 또는 locmem backend를 유지한다. 운영 SMTP 주소와 자격정보는 소스에 기록하지 않는다.
6. `internal_project`의 루트 URL에 `path('wastes/', include('wastes.urls'))`가 없을 때만 추가한다.
7. `internal_project/templates/base.html`의 폐기물 메뉴에 다음 링크를 병합한다. 파일 전체를 덮어쓰지 않는다.
   - `settlement_home`: 월 정산
   - `settlement_history`: 정산 이력
   - `vendor_management`: 업체 관리, staff 전용
   - `price_management`: 단가 관리, staff 전용
   - `allocation_management`: 분배율 관리, staff 전용
   - `report_management`: 보고서 관리
   - `settlement_system`: 시스템 관리, staff 전용
   Django messages 출력 영역이 없으면 Bootstrap alert 영역도 추가한다.
8. `MockWeighingDataSource`를 바로 제거하지 않는다. 사내 계근 테이블 구조를 확인한 뒤 같은 `get_weighing_data(start_date, end_date)` 반환 규격을 구현하는 Company DB Adapter를 추가하고, 운영에서 그 Adapter를 주입한다. 반환 필드는 `source_id`, `weigh_date`, `waste_type`, `transport_company`, `disposal_company`, `weight`, `weight_unit`이며 `vehicle_no`, `slip_no`, `source_reference`는 선택이다.
9. 사내 기존 업체·단가 테이블이 있으면 중복 Master를 만들지 말고 Adapter 또는 명시적인 Mapping으로 연결한다. 공식 업체 식별키와 분배율 기준을 추측하지 않는다.
10. `internal_project`의 migration 번호와 충돌하는지 검사한다. 충돌하면 `test`의 migration 파일을 임의 적용하지 말고 현재 모델 기준으로 새 migration을 생성한다. 운영 적용 전 `migrate --plan`을 확인하며 기존 테이블이나 데이터를 drop/reset하지 않는다.
11. `internal_project`에 `openpyxl`이 이미 설치돼 있는지 확인하고 없을 때만 프로젝트 의존성 관리 방식으로 추가한다.
12. 현재 경로가 `internal_project`인지 확인한 뒤 다음 순서로 검증하고 오류가 있으면 원인을 수정한 후 다시 실행한다.

    ```powershell
    python manage.py makemigrations --check --dry-run
    python manage.py migrate --plan
    python manage.py check
    python manage.py test wastes
    ```

13. `internal_project`의 개발 DB에서 새 연습 정산을 생성해 다음 흐름을 수동 확인한다.
    - 데이터 불러오기
    - 업체 정산 계산
    - 업체별 분배율 선택 및 사업부 배분
    - 추가 보정 후 합계 보존
    - 검증 및 확정
    - 완료 정산 재오픈 후 분배율 변경·재검증
    - 보고서·Excel 생성
    - 이메일 초안 미리보기
    - 승인 체크 없이는 발송 차단
    - 업체별 Excel에 다른 업체 데이터가 포함되지 않음
14. 운영 SMTP, 공식 Report/Excel 양식, 사내 DB Mapping은 관련 정보가 제공된 범위에서만 적용한다. 정보가 없으면 안전한 개발용 구현을 유지하고 남은 항목으로 보고한다.
15. 마지막 보고에는 `test`에서 참조한 파일, `internal_project`에서 변경한 파일, 생성 migration, 테스트 결과, 실제 적용하지 못한 외부 연동, rollback 방법을 포함한다.

## 적용 전 필수 확인

- Python/Django 버전과 `openpyxl` 호환성
- 사내 `wastes` 모델 및 migration 충돌
- 사용자 권한: `change_settlement`, `change_vendor`, staff 권한
- 계근 데이터의 공식 업체키·폐기물 종류·단위
- 업체 단가와 분배율의 공식 적용기간
- 운영 SMTP의 FROM/TO/CC 정책
- 공식 Report/Excel 원본 양식

## 완료 기준

- 기존 사내 데이터와 기능을 보존한다.
- 정산 합계와 사업부 배분 합계가 공급가액·VAT·총액 모두 일치한다.
- 확정 이후 일반 수정은 차단되고 재오픈 사유가 Audit에 남는다.
- 사용자 승인 없이 이메일이 발송되지 않는다.
- 관련 테스트와 Django system check가 통과한다.
