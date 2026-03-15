import requests
from bs4 import BeautifulSoup
import re
import time
from .models import NicsNotice
from django.utils.dateparse import parse_date

def crawl_nics_notices():
    """안전원 고시를 크롤링하여 DB에 저장하는 함수"""
    BASE_URL = "https://nics.mcee.go.kr/sub.do?menuId=36"
    DETAIL_URL = "https://nics.mcee.go.kr/boardView.do"
    DOMAIN = "https://nics.mcee.go.kr"
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': BASE_URL
    }

    try:
        response = requests.get(BASE_URL, headers=HEADERS)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.select('table.board_list tbody tr')

        new_count = 0

        for row in rows:
            # 1. 목록에서 기본 정보 추출
            title_el = row.select_one('span.ellipsis_tit')
            if not title_el: continue
            
            title = title_el.get_text(strip=True)
            date_str = row.select_one('td.date').get_text(strip=True)
            
            # 2. 고유 ID 추출 (중복 체크용)
            onclick_attr = row.select_one('td.subject a').get('onclick', '')
            match = re.search(r'fnView\(\d+,\s*(\d+)\)', onclick_attr)
            if not match: continue
            post_id = match.group(1)

            # 3. DB 중복 확인 (이미 있으면 건너뜀)
            if NicsNotice.objects.filter(post_id=post_id).exists():
                continue

            # 4. 새로운 고시라면 상세 페이지 접속 (POST)
            payload = {
                'menuId': '36', 'boardMasterId': '4',
                'boardId': post_id, 'viewType': 'list'
            }
            res_detail = requests.post(DETAIL_URL, data=payload, headers=HEADERS)
            res_detail.encoding = 'utf-8'
            detail_soup = BeautifulSoup(res_detail.text, 'html.parser')

            # 본문 및 첨부파일 추출
            content_el = detail_soup.select_one('.board_view_content')
            content = content_el.get_text(separator="\n", strip=True) if content_el else ""
            
            file_list = []
            for f in detail_soup.select('.board_view_filebox dd a'):
                f_link = f.get('href')
                if f_link and f_link.startswith('/'): f_link = DOMAIN + f_link
                file_list.append(f"{f.get_text(strip=True)} ({f_link})")
            
            # 5. DB 저장
            NicsNotice.objects.create(
                post_id=post_id,
                title=title,
                reg_date=parse_date(date_str),
                content=content,
                file_links="\n".join(file_list)
            )
            new_count += 1
            time.sleep(0.5) # 서버 부하 방지 매너

        return new_count

    except Exception as e:
        print(f"크롤링 중 오류: {e}")
        return 0