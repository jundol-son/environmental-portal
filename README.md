
• 회사 환경에서 필수로 확인할 것은 세 가지입니다: 실제 SSO의 knoxid 연결, 운영 DB migration, 교육담당자 권한입니다.

  ## 1. SSO 연결

  현재 chemicals/views.py:44는 다음처럼 Django username을 임시 knoxid로 사용합니다.

  def _mock_knoxid(user):
      return user.username

  먼저 회사 환경에서 확인하세요.

  - request.user.username이 이미 실제 knoxid라면 코드 수정 불필요
  - 아니라면 user.sso_profile의 실제 필드명을 확인해 이 함수만 교체
  - 현재 템플릿상 deptname, full_name 필드는 존재하지만 knoxid 필드명은 아직 확인되지 않음
  - SSO 값과 엑셀의 knoxid 대소문자 형식도 반드시 동일해야 함

  예시는 다음과 같습니다. 실제 필드명 확인 후 적용해야 합니다.

  def _user_knoxid(user):
      try:
          return str(user.sso_profile.knoxid).strip()
      except (AttributeError, TypeError):
          return ""

  SSO 값이 없을 때 username으로 자동 대체하는 방식은 운영환경에서는 피하는 것이 안전합니다. 매칭에 실패하면 본인 자료가
  보이지 않는 쪽으로 실패해야 합니다.

  부서는 현재 공식 엑셀의 HandlerProfile.department를 화면과 통계에 사용합니다. SSO 부서는 상단 사용자 표시나 데이터 비
  교에는 쓸 수 있지만, 공식 원본이 엑셀이라는 현재 정책대로라면 교육 데이터의 부서를 SSO로 덮어쓸 필요는 없습니다.

  ## 2. SSO와 Django 권한 연동

  교육담당자 여부는 다음 권한으로 판단합니다.

  chemicals.change_trainingcompletion

  회사 환경의 AUTHENTICATION_BACKENDS도 확인해야 합니다.

  - Django 기본 ModelBackend가 유지되어 있으면 관리자에서 권한 부여 가능
  - SSO 백엔드만 사용한다면 user.has_perm()이 Django DB 권한을 인식하는지 확인
  - 로그인할 때 그룹을 자동 동기화한다면 수동으로 부여한 권한이 제거되지 않는지도 확인

  권장 방식은 교육담당자 Django 그룹을 만들고 해당 권한을 그룹에 부여하는 것입니다.

  ## 3. 운영 DB 반영

  이번 migration은 기존 테이블을 수정하지 않고 아래 테이블 세 개를 새로 만듭니다.

  - 취급자교육 대상자
  - 연도별 수료 현황
  - 수료코드 제출 이력

  배포 순서는 다음이 안전합니다.

  git status
  git fetch origin --tags
  git switch main
  git pull --ff-only origin main
  git describe --tags --exact-match

  마지막 명령 결과가 v0.1.0인지 확인합니다. 회사 PC에 미커밋 변경이 있다면 git pull 전에 반드시 내용을 비교하고, reset
  --hard는 사용하지 마세요.

  그다음:

  python -c "import openpyxl; print(openpyxl.__version__)"
  python manage.py check
  python manage.py migrate chemicals --plan

  운영 DB 백업 후 실행합니다.

  python manage.py migrate chemicals

  이후 기존 운영 방식에 맞춰 웹 서버 프로세스를 재시작합니다. 새 정적 파일은 없으므로 이번 변경만 놓고 보면
  collectstatic은 필수는 아닙니다.

  전체 엑셀을 바로 올리기 전에 실제 사용자 2~3명으로 검증하는 것이 좋습니다.

  - 엑셀 열 이름: knoxid, 이름, 부서
  - SSO knoxid와 엑셀 값이 정확히 일치하는지
  - 일반 사용자가 본인 한 명만 보는지
  - 코드 등록 후 즉시 수료로 바뀌는지
  - 관리자가 이름 검색과 CSV 다운로드를 할 수 있는지
  - 일반 사용자가 다른 대상자의 코드를 등록할 수 없는지

  특히 현재 업로드는 파일에서 빠진 기존 대상자를 삭제하거나 비활성화하지 않습니다. 퇴직·전배 등으로 제외할 대상자는
  Django 관리자에서 교육 대상을 해제해야 합니다.

  ## 5. 운영 데이터 관련 주의점

  - 수료코드는 합의한 대로 DB에 원문 저장되고 본인 화면·관리자 목록·CSV에 노출됩니다.
  - 잘못된 knoxid로 업로드하면 별도 대상자로 생성되어 수료율 분모가 틀어질 수 있습니다.
  - 롤백 시 코드는 이전 버전으로 되돌릴 수 있지만, 입력된 데이터를 보존하려면 migration을 역적용하지 않는 편이 안전합니
    다.

  - 회사 Django/Python 버전과 현재 릴리즈의 Django 5.2 계열 호환성도 확인하세요.

  결론적으로 실제 코드 수정 가능성이 가장 높은 곳은 chemicals/views.py:44입니다. 회사에서 username 및 sso_profile의 실제
  필드 구조를 확인해 알려주면 정확한 운영용 수정안을 바로 만들 수 있습니다.
