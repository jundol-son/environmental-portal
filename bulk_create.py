import os
import django
import random

# 1. 장고 환경 설정
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings') # 본인의 프로젝트 설정명 확인
django.setup()

from dashboard.models import CustomerAsset
from django.contrib.auth.models import User

def create_bulk_assets(count=200):
    # 기존 관리자(PB) 가져오기
    managers = list(User.objects.all())
    if not managers:
        print("❌ 관리자 계정이 없습니다. 먼저 슈퍼유저를 생성하세요.")
        return

    asset_types = ['국내주식', '해외채권', '가상자산', '예적금', '펀드', 'ETF']
    last_names = ['김', '이', '박', '최', '정', '강', '조', '윤', '장', '임']
    first_names = ['민준', '서준', '도윤', '예준', '시우', '하준', '지호', '서윤', '서연', '지우']

    assets_to_create = []

    for i in range(count):
        name = random.choice(last_names) + random.choice(first_names)
        asset_type = random.choice(asset_types)
        balance = random.randint(1000, 1000000000) # 1천원 ~ 10억원
        email = f"user{i}@example.com"
        manager = random.choice(managers)

        assets_to_create.append(CustomerAsset(
            manager=manager,
            name=name,
            asset_type=asset_type,
            balance=balance,
            email=email
        ))

    # 한 번에 200명 밀어넣기 (성능 최적화)
    CustomerAsset.objects.bulk_create(assets_to_create)
    print(f"✅ 성공적으로 {count}명의 고객 데이터가 생성되었습니다!")

if __name__ == "__main__":
    create_bulk_assets(200)