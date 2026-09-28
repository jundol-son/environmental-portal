from django.urls import path
from . import views

urlpatterns = [
    # 폐기물 배출 목록 메인 화면
    path('', views.waste_list, name='waste_list'),
    
    # 엑셀 다운로드 (전체 및 선택)
    path('export/', views.export_waste_excel, name='export_waste_excel'),
    
    # 분석 보고서 생성 화면
    path('report/', views.generate_waste_report, name='generate_waste_report'),
    
    # 데이터 일괄 관리 및 업로드 (Admin 전용)
    path('management/', views.waste_admin, name='waste_admin'),

    path('dashboard/', views.waste_dashboard, name='waste_dashboard'),

    path('settlements/', views.settlement_home, name='settlement_home'),
    path('settlements/<int:pk>/', views.settlement_detail, name='settlement_detail'),
    path(
        'settlements/<int:pk>/action/<str:action>/',
        views.settlement_action,
        name='settlement_action',
    ),
    path('settlements/<int:pk>/report/', views.settlement_report, name='settlement_report'),
    path('settlements/<int:pk>/excel/', views.settlement_excel, name='settlement_excel'),
    path('history/', views.settlement_history, name='settlement_history'),
    path('vendors/', views.vendor_management, name='vendor_management'),
    path('prices/', views.price_management, name='price_management'),
    path('allocations/', views.allocation_management, name='allocation_management'),
    path('reports/', views.report_management, name='report_management'),
    path('system/', views.settlement_system, name='settlement_system'),
]
