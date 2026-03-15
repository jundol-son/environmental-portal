from django.urls import path
from . import views

app_name = 'integrated'

urlpatterns = [
    # 기존 upload_page 대신 dashboard_page를 기본 경로로 설정
    path('', views.dashboard_page, name='upload_page'), 
    path('dashboard/', views.dashboard_page, name='dashboard'),
    path('settings/', views.settings_page, name='settings_page'),
    
    # API 경로들
    path('api/validate-excel/', views.validate_excel_api, name='validate_excel'),
    path('api/save-excel-data/', views.save_excel_data_api, name='save_excel_data'),
    path('api/import-master/', views.import_master_api, name='import_master'),
    path('api/delete-master/', views.delete_master_api, name='delete_master'),
    path('download-sample/', views.download_excel_sample, name='download_sample'),
    path('settings/download-sample/', views.download_settings_sample, name='download_settings_sample'),
    # 대시보드 로그 개별 수정 및 삭제 API
    path('api/get-log-detail/<int:log_id>/', views.get_log_detail_api, name='get_log_detail'),
    path('api/save-log-edit/', views.save_log_edit_api, name='save_log_edit'),
    path('api/delete-log/', views.delete_log_api, name='delete_log'),
    path('api/get-facility-config/<int:facility_id>/', views.get_facility_config_api, name='get_facility_config'),
    path('api/save-facility-config/', views.save_facility_config_api, name='save_facility_config'),
    path('api/get-facility-detail/<int:facility_id>/', views.get_facility_detail_api, name='get_facility_detail'),
    path('api/save-facility-detail/', views.save_facility_detail_api, name='save_facility_detail'),    
]