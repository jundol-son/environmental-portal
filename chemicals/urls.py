from django.urls import path
from . import views

urlpatterns = [
    # 기존: /chemicals/ 접속 시 실행
    path('', views.chemical_check, name='chemical_check'),
    
    # 추가: /chemicals/nics/ 접속 시 실행
    path('nics/', views.nics_notice_list, name='nics_notice_list'),
    path('training/', views.training_dashboard, name='training_dashboard'),
    path('training/status/', views.training_status, name='training_status'),
    path('training/manage/', views.training_manage, name='training_manage'),
    path('training/submit/<int:completion_id>/', views.training_submit, name='training_submit'),
    path('training/upload/', views.training_upload, name='training_upload'),
    path('training/manage/excel/template/', views.training_excel_template, name='training_excel_template'),
    path('training/manage/excel/upload/', views.training_status_upload, name='training_status_upload'),
    path('training/export/', views.training_export_csv, name='training_export_csv'),
    path('training/worker/', views.worker_training, name='worker_training'),
]
