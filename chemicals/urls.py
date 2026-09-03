from django.urls import path
from . import views

urlpatterns = [
    # 기존: /chemicals/ 접속 시 실행
    path('', views.chemical_check, name='chemical_check'),
    
    # 추가: /chemicals/nics/ 접속 시 실행
    path('nics/', views.nics_notice_list, name='nics_notice_list'),
    path('training/', views.training_dashboard, name='training_dashboard'),
    path('training/submit/<int:completion_id>/', views.training_submit, name='training_submit'),
    path('training/upload/', views.training_upload, name='training_upload'),
    path('training/export/', views.training_export_csv, name='training_export_csv'),
]
