from background_task import background
from datetime import datetime
from .utils import crawl_nics_notices
import logging

# 터미널 로그를 위한 설정
logger = logging.getLogger(__name__)

@background(schedule=10)  # 서버 실행 10초 후부터 대기
def monitor_nics_notices():
    """안전원 고시를 정기적으로 확인하고 결과를 터미널에 출력하는 태스크"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[{now}] >>> 안전원 고시 자동 스캔 시작")
    
    try:
        # 이전에 만든 크롤링 함수 호출
        new_count = crawl_nics_notices()
        
        if new_count > 0:
            print(f"[{now}] >>> 결과: ★ 신규 고시 {new_count}건 발견 및 DB 저장 완료")
        else:
            print(f"[{now}] >>> 결과: 업데이트된 내용 없음 (정상)")
            
    except Exception as e:
        print(f"[{now}] >>> 에러 발생: {e}")
    
    print(f"[{now}] >>> 스캔 종료\n")