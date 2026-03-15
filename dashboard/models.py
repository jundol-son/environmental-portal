from django.db import models
from django.contrib.auth.models import User # 장고 기본 유저 모델 불러오기
from django.conf import settings

class CustomerAsset(models.Model):
    manager = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="담당 관리자", null=True, blank=True)    
    name = models.CharField(max_length=100)      # 고객명
    asset_type = models.CharField(max_length=50) # 자산군
    balance = models.DecimalField(max_digits=15, decimal_places=2) # 잔고
    email = models.EmailField()                  # 이메일
    # 추가 추천: 최초 등록 시각 (한 번만 기록됨)
    created_at = models.DateTimeField(auto_now_add=True) 
    # 수정일 (저장할 때마다 자동으로 갱신됨)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
            # f-string 앞에 return이 빠져있어서 추가했습니다.
            return f"{self.name} ({self.asset_type})"
    
class CalendarEvent(models.Model):
    title = models.CharField(max_length=200, verbose_name="일정 제목")
    description = models.TextField(blank=True, null=True, verbose_name="상세 내용")
    start_time = models.DateTimeField(verbose_name="시작 시간")
    end_time = models.DateTimeField(verbose_name="종료 시간")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="등록자")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title    