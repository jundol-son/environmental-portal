from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'), # 홈 화면
    path('assets/', views.asset_list, name='asset_list'), # 자산 현황
    path('assets/export/', views.export_assets_excel, name='export_assets_excel'),
    path('admin-management/', views.admin_management, name='admin_management'),
    path('update-user-status/', views.update_user_status, name='update_user_status'),
    path('download-sample/', views.download_sample_excel, name='download_sample_excel'),
    path('api/events/', views.event_list, name='event_list'),
    path('api/save-event/', views.save_event, name='save_event'),
    path('api/delete-event/', views.delete_event, name='delete_event'),
    path('assets/report/', views.generate_asset_report, name='asset_report'),
]