from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import (
    AllocationRule,
    Settlement,
    SettlementAllocation,
    SettlementEmail,
    Vendor,
    VendorPrice,
    WasteLog,
)
from .forms import (
    AllocationRuleForm,
    SettlementStartForm,
    VendorForm,
    VendorPriceForm,
)
from django.contrib import messages
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.views.decorators.http import require_POST
from datetime import datetime
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from .services import WasteService
from .settlement_services import (
    SettlementError,
    MockWeighingDataSource,
    apply_manual_adjustment,
    allocate_business_units,
    build_settlement_excel,
    business_unit_totals,
    calculate_vendors,
    compare_sources,
    confirm_settlement,
    create_settlement,
    load_sources,
    mark_report_generated,
    prepare_settlement_emails,
    reopen_settlement,
    send_settlement_email,
    set_vendor_allocation_rule,
    settlement_totals,
    validate_settlement,
    vendor_totals,
)

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

@login_required
def waste_dashboard(request):
    chart_data = WasteService.get_dashboard_data()
    return render(request, 'wastes/waste_dashboard.html', {'chart_data': chart_data})


@login_required
def settlement_home(request):
    if request.method == 'POST':
        form = SettlementStartForm(request.POST)
        if form.is_valid():
            month = form.cleaned_data['settlement_month']
            practice_mode = request.POST.get('mode') == 'practice'
            while practice_mode and Settlement.objects.filter(
                settlement_month=month
            ).exists():
                month = (
                    month.replace(year=month.year + 1, month=1)
                    if month.month == 12
                    else month.replace(month=month.month + 1)
                )
            settlement, created = create_settlement(
                month, request.user
            )
            if not created:
                messages.info(request, '이미 존재하는 정산으로 이동했습니다.')
            else:
                try:
                    data_source = (
                        MockWeighingDataSource(use_database=False)
                        if practice_mode else None
                    )
                    count, is_mock = load_sources(
                        settlement, request.user, data_source=data_source
                    )
                    source_label = '내장 모의 데이터' if is_mock else '폐기물 배출 데이터'
                    messages.success(
                        request,
                        f'{source_label} {count}건을 Snapshot으로 저장했습니다.',
                    )
                except SettlementError as exc:
                    messages.error(request, str(exc))
            return redirect('settlement_detail', pk=settlement.pk)
    else:
        form = SettlementStartForm(initial={
            'settlement_month': timezone.localdate().strftime('%Y-%m')
        })
    active = Settlement.objects.exclude(
        status__in=[
            Settlement.Status.CONFIRMED,
            Settlement.Status.REPORT_GENERATED,
            Settlement.Status.EMAIL_SENT,
        ]
    )
    return render(request, 'wastes/settlement_home.html', {
        'form': form,
        'active_settlements': active,
    })


@login_required
def settlement_detail(request, pk):
    settlement = get_object_or_404(Settlement, pk=pk)
    current_step = {
        Settlement.Status.DRAFT: 1,
        Settlement.Status.SOURCE_LOADED: 1,
        Settlement.Status.VENDOR_CALCULATED: 2,
        Settlement.Status.ALLOCATED: 3,
        Settlement.Status.VALIDATED: 4,
        Settlement.Status.CONFIRMED: 5,
        Settlement.Status.REPORT_GENERATED: 6,
        Settlement.Status.EMAIL_SENT: 6,
    }.get(settlement.status, 1)
    requested_step = request.GET.get('step', '')
    active_step = int(requested_step) if requested_step in set('123456') else current_step
    allocations = settlement.vendor_results.prefetch_related('allocations')
    adjustment_allocations = SettlementAllocation.objects.filter(
        vendor_result__settlement=settlement
    ).select_related('vendor_result__source').order_by(
        'vendor_result_id', 'sort_order'
    )
    vendor_ids = settlement.vendor_results.values_list('vendor_id', flat=True)
    allocation_vendors = Vendor.objects.filter(pk__in=vendor_ids).select_related(
        'allocation_rule'
    ).prefetch_related('allocation_rule__details').distinct()
    available_rules = AllocationRule.objects.filter(
        active=True,
        valid_from__lte=settlement.period_start,
    ).filter(
        Q(valid_to__isnull=True) | Q(valid_to__gte=settlement.period_end)
    ).prefetch_related('details').order_by('rule_code')
    can_work = (
        request.user.has_perm('wastes.change_settlement')
        or settlement.created_by_id == request.user.id
    )
    return render(request, 'wastes/settlement_detail.html', {
        'settlement': settlement,
        'current_step': current_step,
        'active_step': active_step,
        'totals': settlement_totals(settlement),
        'vendor_results': allocations,
        'adjustment_allocations': adjustment_allocations,
        'settlement_emails': settlement.emails.select_related(
            'vendor', 'sent_by'
        ).all(),
        'business_totals': business_unit_totals(settlement),
        'allocation_vendors': allocation_vendors,
        'available_rules': available_rules,
        'can_work': can_work,
        'can_confirm': request.user.has_perm('wastes.change_settlement'),
        'can_manage_rules': request.user.has_perm('wastes.change_vendor'),
    })


@require_POST
@login_required
def settlement_action(request, pk, action):
    settlement = get_object_or_404(Settlement, pk=pk)
    if action == 'set_rule':
        if not request.user.has_perm('wastes.change_vendor'):
            messages.error(request, '업체 분배율 변경 권한이 없습니다.')
            return redirect('settlement_detail', pk=settlement.pk)
        vendor_id = request.POST.get('vendor_id')
        rule_id = request.POST.get('allocation_rule')
        if not vendor_id or not vendor_id.isdigit() or not rule_id or not rule_id.isdigit():
            messages.error(request, '업체와 분배율 규칙을 올바르게 선택하세요.')
            return redirect(f"{reverse('settlement_detail', args=[settlement.pk])}?step=3")
        vendor = Vendor.objects.filter(
            pk=vendor_id,
            pk__in=settlement.vendor_results.values_list('vendor_id', flat=True),
        ).first()
        rule = AllocationRule.objects.filter(pk=rule_id).first()
        try:
            if not vendor or not rule:
                raise SettlementError('업체와 분배율 규칙을 올바르게 선택하세요.')
            set_vendor_allocation_rule(settlement, vendor, rule, request.user)
            messages.success(request, f'{vendor.vendor_name} 분배율을 저장했습니다.')
        except SettlementError as exc:
            messages.error(request, str(exc))
        return redirect(f"{reverse('settlement_detail', args=[settlement.pk])}?step=3")
    can_change = request.user.has_perm('wastes.change_settlement')
    if action in {'confirm', 'reopen', 'prepare_emails', 'send_email'} and not can_change:
        messages.error(request, '정산 확정·재작업·메일 발송 권한이 없습니다.')
        return redirect('settlement_detail', pk=settlement.pk)
    if not can_change and settlement.created_by_id != request.user.id:
        messages.error(request, '본인이 생성한 정산만 진행할 수 있습니다.')
        return redirect('settlement_detail', pk=settlement.pk)
    actions = {
        'apply_reload': lambda: load_sources(settlement, request.user),
        'calculate': lambda: calculate_vendors(settlement, request.user),
        'allocate': lambda: allocate_business_units(settlement, request.user),
        'validate': lambda: validate_settlement(settlement, request.user),
        'report': lambda: mark_report_generated(settlement, request.user),
    }
    try:
        if action == 'compare':
            diff = compare_sources(settlement)
            messages.info(
                request,
                'DB 재조회 비교: '
                f"Snapshot {diff['snapshot_count']}건 / DB {diff['source_count']}건 / "
                f"추가 {diff['added']}건 / 변경 {diff['changed']}건 / 삭제 {diff['deleted']}건",
            )
        elif action == 'confirm':
            confirm_settlement(settlement, request.user)
            messages.success(request, '정산을 확정했습니다.')
        elif action == 'reopen':
            reopen_settlement(
                settlement, request.user, request.POST.get('reason', '')
            )
            messages.success(request, '정산을 재작업 상태로 전환했습니다.')
        elif action == 'manual_adjust':
            source_id = request.POST.get('source_allocation', '')
            target_id = request.POST.get('target_allocation', '')
            amount_text = request.POST.get('amount', '')
            if not source_id.isdigit() or not target_id.isdigit() or not amount_text.isdigit():
                raise SettlementError('보정 항목과 원 단위 금액을 올바르게 입력하세요.')
            rows = SettlementAllocation.objects.filter(
                pk__in=[source_id, target_id],
                vendor_result__settlement=settlement,
            ).in_bulk()
            if len(rows) != 2:
                raise SettlementError('보정 항목을 올바르게 선택하세요.')
            apply_manual_adjustment(
                settlement,
                rows[int(source_id)],
                rows[int(target_id)],
                int(amount_text),
                request.POST.get('reason', ''),
                request.user,
            )
            messages.success(request, '추가 보정을 반영했습니다. 다시 검증하세요.')
        elif action == 'prepare_emails':
            count = prepare_settlement_emails(settlement, request.user)
            messages.success(request, f'업체별 메일 초안 {count}건을 준비했습니다.')
        elif action == 'send_email':
            if request.POST.get('approved') != 'yes':
                raise SettlementError('메일 내용을 확인하고 발송 승인에 체크하세요.')
            email_id = request.POST.get('email_id', '')
            if not email_id.isdigit():
                raise SettlementError('발송할 메일을 선택하세요.')
            email = SettlementEmail.objects.filter(
                pk=email_id, settlement=settlement
            ).select_related('settlement').first()
            if not email:
                raise SettlementError('발송할 메일을 찾을 수 없습니다.')
            send_settlement_email(email, request.user)
            messages.success(request, f'{email.vendor_name} 메일을 발송했습니다.')
        elif action in actions:
            result = actions[action]()
            if action == 'validate':
                if result:
                    messages.success(request, '모든 정산 검증을 통과했습니다.')
                else:
                    messages.error(request, '실패한 검증 항목을 확인하세요.')
            elif action == 'report':
                messages.success(request, '보고서와 Excel 다운로드를 준비했습니다.')
            else:
                messages.success(request, '요청한 단계를 완료했습니다.')
        else:
            messages.error(request, '지원하지 않는 작업입니다.')
    except SettlementError as exc:
        messages.error(request, str(exc))
    return redirect('settlement_detail', pk=settlement.pk)


@login_required
def settlement_history(request):
    settlements = Settlement.objects.annotate(
        total_amount=Sum('vendor_results__total_amount')
    ).order_by('-settlement_month')
    month = request.GET.get('month', '')
    status = request.GET.get('status', '')
    if month:
        try:
            settlements = settlements.filter(
                settlement_month=datetime.strptime(month, '%Y-%m').date()
            )
        except ValueError:
            messages.error(request, '정산월 형식이 올바르지 않습니다.')
    valid_statuses = dict(Settlement.Status.choices)
    if status in valid_statuses:
        settlements = settlements.filter(status=status)
    summary_count = settlements.count()
    summary_total = sum(item.total_amount or 0 for item in settlements)
    page_obj = Paginator(settlements, 20).get_page(request.GET.get('page'))
    return render(request, 'wastes/settlement_history.html', {
        'settlements': page_obj,
        'page_obj': page_obj,
        'month_filter': month,
        'status_filter': status,
        'status_choices': Settlement.Status.choices,
        'summary_count': summary_count,
        'summary_total': summary_total,
        'show_filters': True,
    })


@login_required
def settlement_report(request, pk):
    settlement = get_object_or_404(Settlement, pk=pk)
    if settlement.status not in {
        Settlement.Status.CONFIRMED,
        Settlement.Status.REPORT_GENERATED,
        Settlement.Status.EMAIL_SENT,
    }:
        messages.error(request, '확정된 정산만 보고서를 조회할 수 있습니다.')
        return redirect('settlement_detail', pk=pk)
    return render(request, 'wastes/settlement_report.html', {
        'settlement': settlement,
        'totals': settlement_totals(settlement),
        'business_totals': business_unit_totals(settlement),
        'vendor_totals': vendor_totals(settlement),
        'allocation_rules': settlement.vendor_results.values(
            'vendor_name', 'allocation_rule_code', 'allocation_rule_name'
        ).order_by('vendor_name', 'allocation_rule_code').distinct(),
    })


@login_required
def settlement_excel(request, pk):
    settlement = get_object_or_404(Settlement, pk=pk)
    if settlement.status not in {
        Settlement.Status.REPORT_GENERATED,
        Settlement.Status.EMAIL_SENT,
    }:
        messages.error(request, '먼저 결과물을 생성하세요.')
        return redirect('settlement_detail', pk=pk)
    response = HttpResponse(
        build_settlement_excel(settlement),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    month = settlement.settlement_month.strftime('%Y%m')
    response['Content-Disposition'] = f'attachment; filename=settlement_{month}.xlsx'
    return response


@staff_member_required
def vendor_management(request):
    edit_id = request.POST.get('vendor_id') or request.GET.get('edit')
    instance = get_object_or_404(Vendor, pk=edit_id) if edit_id else None
    form = VendorForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, '업체 정보를 저장했습니다.')
        return redirect('vendor_management')
    return render(request, 'wastes/master_management.html', {
        'title': '업체 관리',
        'kind': 'vendor',
        'form': form,
        'items': Vendor.objects.select_related('allocation_rule').order_by('vendor_name'),
        'edit_id': edit_id,
    })


@staff_member_required
def price_management(request):
    form = VendorPriceForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, '기간별 단가를 저장했습니다.')
        return redirect('price_management')
    return render(request, 'wastes/master_management.html', {
        'title': '단가 관리',
        'kind': 'price',
        'form': form,
        'items': VendorPrice.objects.select_related('vendor'),
    })


@staff_member_required
def allocation_management(request):
    edit_id = request.POST.get('rule_id') or request.GET.get('edit')
    instance = get_object_or_404(AllocationRule, pk=edit_id) if edit_id else None
    form = AllocationRuleForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, '분배율 규칙을 저장했습니다.')
        return redirect('allocation_management')
    return render(request, 'wastes/master_management.html', {
        'title': '분배율 관리',
        'kind': 'allocation',
        'form': form,
        'items': AllocationRule.objects.prefetch_related(
            'details', 'vendors'
        ).order_by('rule_code'),
        'edit_id': edit_id,
    })


@login_required
def report_management(request):
    settlements = Settlement.objects.filter(
        status__in=[
            Settlement.Status.REPORT_GENERATED,
            Settlement.Status.EMAIL_SENT,
        ]
    ).annotate(total_amount=Sum('vendor_results__total_amount'))
    return render(request, 'wastes/settlement_history.html', {
        'settlements': settlements,
        'page_title': '보고서 관리',
    })


@staff_member_required
def settlement_system(request):
    return render(request, 'wastes/settlement_system.html', {
        'vat_rate': '10%',
        'data_source': 'MockWeighingDataSource',
        'email_backend': getattr(
            settings,
            'WASTE_SETTLEMENT_EMAIL_BACKEND',
            'django.core.mail.backends.console.EmailBackend',
        ),
    })
