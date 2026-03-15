import random
from wastes.models import WasteLog
from django.contrib.auth.models import User

def run():
    # 1. 데이터를 관리할 유저(PB) 가져오기 (admin 계정 가정)
    user = User.objects.get(username='admin')
    
    # 2. 가짜 데이터 후보들
    waste_types = ['폐유', '폐산', '폐알칼리', '폐합성수지', '슬러지']
    companies = ['(주)환경사랑', '에코그린', '서진환경', '미래처리', '푸른세상']
    units = ['kg', 'ton', 'L']

    print("데이터 생성을 시작합니다...")

    # 3. 200개의 데이터 생성 루프
    for i in range(200):
        WasteLog.objects.create(
            manager=user,
            waste_type=random.choice(waste_types),
            quantity=random.uniform(10.0, 500.0), # 10~500 사이의 실수
            unit=random.choice(units),
            company=random.choice(companies)
        )

    print(f"성공적으로 200건의 폐기물 데이터를 생성했습니다!")