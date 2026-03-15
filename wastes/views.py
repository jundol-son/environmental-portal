from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import WasteLog  # wastes 앱의 모델로 변경
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
import pandas as pd
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from datetime import datetime
from io import BytesIO
from .services import WasteService

@login_required
def waste_list(request):
    """폐기물 배출 내역 리스트 및 필터링"""
    # 필터용 데이터 추출
    managers = User.objects.all()
    # 중복 제거된 폐기물 종류 리스트 (콤보박스용)
    waste_types = WasteLog.objects.values_list('waste_type', flat=True).distinct()

    # 필터 값 가져오기
    selected_manager = request.GET.get('manager')
    selected_waste_type = request.GET.get('waste_type')
    search_company = request.GET.get('search_company') # 업체명 검색으로 변경
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')      
    per_page = request.GET.get('per_page', 20)

    # 기본 쿼리셋 (최신 배출순 정렬)
    wastes = WasteLog.objects.all().order_by('-created_at')

    # 필터 적용 로직
    if selected_manager:
        wastes = wastes.filter(manager_id=selected_manager)
    if selected_waste_type:
        wastes = wastes.filter(waste_type=selected_waste_type)
    if search_company:
        wastes = wastes.filter(company__icontains=search_company)
    if start_date:
        wastes = wastes.filter(created_at__date__gte=start_date)
    if end_date:
        wastes = wastes.filter(created_at__date__lte=end_date)

    # 페이징 처리
    paginator = Paginator(wastes, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'wastes': page_obj,
        'managers': managers,
        'waste_types': waste_types,
        'per_page': int(per_page),
    }    
    return render(request, 'wastes/waste_list.html', context)

@login_required
def export_waste_excel(request):
    selected_ids = request.GET.getlist('ids')
    wastes = WasteLog.objects.filter(id__in=selected_ids) if selected_ids else WasteLog.objects.all()
    
    # 실무 로직은 서비스에게 맡깁니다.
    excel_data = WasteService.export_wastes_to_excel(wastes)
    
    response = HttpResponse(excel_data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename=waste_report_{datetime.now().strftime("%Y%m%d")}.xlsx'
    return response

@login_required
def generate_waste_report(request):
    selected_ids = request.GET.getlist('ids')
    wastes = WasteLog.objects.filter(id__in=selected_ids)
    
    # 분석 로직은 서비스에게 맡깁니다.
    reports = WasteService.generate_analysis_report(wastes)
    
    return render(request, 'wastes/waste_report.html', {'reports': reports})
@staff_member_required
def waste_admin(request):
    """폐기물 데이터 일괄 업로드 및 관리 (자산 관리의 admin_management 이식)"""
    users = User.objects.all().order_by('-date_joined')
    preview_data = None

    if request.method == 'POST':
        if 'add_single' in request.POST:
            WasteLog.objects.create(
                manager=request.user,
                waste_type=request.POST.get('waste_type'),
                quantity=request.POST.get('quantity'),
                unit=request.POST.get('unit', 'kg'),
                company=request.POST.get('company')
            )
            messages.success(request, "폐기물 배출 내역이 등록되었습니다.")
            return redirect('waste_admin')

    return render(request, 'wastes/waste_admin.html', {'users': users})

def waste_dashboard(request):
    chart_data = WasteService.get_dashboard_data()
    return render(request, 'wastes/waste_dashboard.html', {'chart_data': chart_data})