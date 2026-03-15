from django.contrib import admin
from .models import CustomerAsset

@admin.register(CustomerAsset)
class CustomerAssetAdmin(admin.ModelAdmin):
    # 1. 목록 화면에서 보여줄 필드 설정 (자산현황을 한눈에 파악)
    list_display = ('name', 'asset_type', 'balance', 'manager', 'updated_at')
    
    # 2. 우측 필터 사이드바 (자산군별, 담당 PB별로 골라보기 편함)
    list_filter = ('asset_type', 'manager', 'created_at')
    
    # 3. 검색창 (고객명이나 이메일로 빠른 찾기 가능)
    search_fields = ('name', 'email')
    
    # 4. 필드 배치 설정 (수정 화면에서 담당자 정보를 상단에 배치)
    fields = ('manager', 'name', 'asset_type', 'balance', 'email')
    
    # 5. 정렬 기준 (최근 수정된 데이터가 위로 오도록)
    ordering = ('-updated_at',)

    # 금액(balance) 필드에 천 단위 콤마를 넣어 가독성 향상 (선택 사항)
    def get_balance_display(self, obj):
        return f"{obj.balance:,.0f}"
    get_balance_display.short_description = '잔고'