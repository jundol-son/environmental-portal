from django.urls import path
from . import views

urlpatterns = [
    # 기존: /chemicals/ 접속 시 실행
    path('', views.chemical_check, name='chemical_check'),
    
    # 추가: /chemicals/nics/ 접속 시 실행
    path('nics/', views.nics_notice_list, name='nics_notice_list'),
]