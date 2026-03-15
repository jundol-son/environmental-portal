from django.db import models
from django.contrib.auth.models import User

class WasteLog(models.Model):
    manager = models.ForeignKey(User, on_delete=models.CASCADE)
    waste_type = models.CharField(max_length=100) # 폐기물 종류 (예: 폐유, 폐산)
    quantity = models.FloatField()               # 배출량
    unit = models.CharField(max_length=10, default='kg')
    company = models.CharField(max_length=100)   # 수거 업체
    created_at = models.DateTimeField(auto_now_add=True)