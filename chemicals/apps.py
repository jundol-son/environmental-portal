from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

class ChemicalsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'chemicals'

    def ready(self):
        # 1. 서버 실행 시 중복 실행 방지 체크
        import os
        if os.environ.get('RUN_MAIN') != 'true':
            # Django runserver는 코드 변경 감지를 위해 프로세스를 두 개 띄우는데,
            # 실제 로직은 하나에서만 돌아가도록 이 조건문이 필요합니다.
            return

        # 2. 스케줄러 설정
        from apscheduler.schedulers.background import BackgroundScheduler
        from .utils import crawl_nics_notices
        from datetime import datetime

        def scheduled_task():
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{now}] APScheduler: 안전원 고시 자동 스캔 시작")
            try:
                count = crawl_nics_notices()
                print(f"[{now}] APScheduler: 스캔 완료 (신규 {count}건)")
            except Exception as e:
                print(f"[{now}] APScheduler 에러 발생: {e}")

        # 3. 백그라운드 스케줄러 시작
        scheduler = BackgroundScheduler()
        # hours=1 (1시간마다), 테스트를 위해선 seconds=60 등으로 바꿔서 확인 가능
        scheduler.add_job(
                    scheduled_task, 
                    'interval', 
                    hours=1, 
                    id='nics_crawl_job',
                    replace_existing=True # 중복 실행 방지
                )
        
        try:
            scheduler.start()
            print(">>> APScheduler가 1초 간격으로 작동 중입니다. 로그를 확인하세요.")
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown()