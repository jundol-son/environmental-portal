import json
import pandas as pd
from io import BytesIO
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.shortcuts import render, get_object_or_404
from django.db import transaction, IntegrityError
from django.db.models import Max, Q
from django.utils import timezone
from .services import ExcelValidationService
from .models import Facility, Substance, MeasurementConfig, DailyLog

# 1. 통합 대시보드 (탭 3종 데이터 가공 및 필터 통합)
# dashboard_page 함수만 업데이트 하거나 전체 교체하세요.
def dashboard_page(request):
    """탭별 필터링과 활성 탭 상태 유지를 반영한 대시보드 뷰"""
    now = timezone.now()
    selected_year = request.GET.get('year', str(now.year))
    selected_month = request.GET.get('month', str(now.month))
    selected_substances = request.GET.getlist('substances')
    active_tab = request.GET.get('tab', 'summary-content')
    month_str = f"{selected_month}월"
    selected_year_int = int(selected_year)
    selected_month_int = int(selected_month)

    # 1. 공통 쿼리셋 및 기본 변수
    all_substances = Substance.objects.all().order_by('name')
    logs_qs = DailyLog.objects.filter(
        collection_month=month_str,
        date__year=selected_year 
    ).select_related('facility', 'substance')
    
    # "법적" 항목 중 "제출용" 데이터만 필터링하기 위한 기준 설정
    legal_configs = MeasurementConfig.objects.select_related('substance').filter(substance__legal_type='법적')

    # 2. 연간 이행률 계산 (법적, 제출용 기준)
    annual_total_required = 0
    annual_completed_count = 0
    cycle_to_count = {'매월': 12, '분기': 4, '반기': 2}

    for config in legal_configs:
        required_count = cycle_to_count.get(config.substance.cycle)
        if not required_count:
            continue
        annual_total_required += required_count

        logs_for_year = DailyLog.objects.filter(
            facility=config.facility, substance=config.substance,
            date__year=selected_year_int, is_report_data=True
        )

        if config.substance.cycle == '매월':
            annual_completed_count += logs_for_year.values('date__month').distinct().count()
        elif config.substance.cycle == '분기':
            q1 = logs_for_year.filter(date__month__in=[1, 2, 3]).exists()
            q2 = logs_for_year.filter(date__month__in=[4, 5, 6]).exists()
            q3 = logs_for_year.filter(date__month__in=[7, 8, 9]).exists()
            q4 = logs_for_year.filter(date__month__in=[10, 11, 12]).exists()
            annual_completed_count += sum([q1, q2, q3, q4])
        elif config.substance.cycle == '반기':
            h1 = logs_for_year.filter(date__month__in=range(1, 7)).exists()
            h2 = logs_for_year.filter(date__month__in=range(7, 13)).exists()
            annual_completed_count += sum([h1, h2])
            
    annual_completion_rate = round((annual_completed_count / annual_total_required * 100), 1) if annual_total_required > 0 else 0

    # 3. 당월 측정 현황 계산 (법적, 제출용 기준) + 풍량 상태 추가
    due_this_month = {
        'total': 0, 'completed': 0, 'normal': 0, 
        'conc_internal_exceed': 0, 'conc_legal_exceed': 0,
        'af_internal_exceed': 0, 'af_legal_exceed': 0,
        'missing_list': [], 'completed_list': []
    }
    
    current_quarter = (selected_month_int - 1) // 3 + 1
    quarter_months = range(current_quarter * 3 - 2, current_quarter * 3 + 1)
    current_half = 1 if selected_month_int <= 6 else 2
    half_year_months = range(1, 7) if current_half == 1 else range(7, 13)

    for config in legal_configs:
        cycle = config.substance.cycle
        
        if cycle == '매월':
            due_this_month['total'] += 1
            log = DailyLog.objects.filter(
                facility=config.facility, substance=config.substance,
                date__year=selected_year_int, date__month=selected_month_int,
                is_report_data=True
            ).order_by('-value').first()
            
            if log:
                due_this_month['completed'] += 1
                
                # 농도 상태 집계
                if log.substance_status == '사내초과':
                    due_this_month['conc_internal_exceed'] += 1
                elif log.substance_status == '법적초과':
                    due_this_month['conc_legal_exceed'] += 1
                
                # 풍량 상태 집계
                if log.airflow_status == '사내초과':
                    due_this_month['af_internal_exceed'] += 1
                elif log.airflow_status == '법적초과':
                    due_this_month['af_legal_exceed'] += 1
                
                # 둘 다 정상일 때만 정상으로 집계
                if log.substance_status == '정상' and log.airflow_status == '정상':
                    due_this_month['normal'] += 1
                    
                due_this_month['completed_list'].append({'config': config, 'log': log})
            else:
                due_this_month['missing_list'].append({'config': config})

        elif cycle == '분기' and selected_month_int % 3 == 0:
            is_measured = DailyLog.objects.filter(
                facility=config.facility, substance=config.substance,
                date__year=selected_year_int, date__month__in=quarter_months,
                is_report_data=True
            ).exists()
            if not is_measured:
                due_this_month['total'] += 1
                due_this_month['missing_list'].append({'config': config})
        
        elif cycle == '반기' and selected_month_int % 6 == 0:
            is_measured = DailyLog.objects.filter(
                facility=config.facility, substance=config.substance,
                date__year=selected_year_int, date__month__in=half_year_months,
                is_report_data=True
            ).exists()
            if not is_measured:
                due_this_month['total'] += 1
                due_this_month['missing_list'].append({'config': config})

    due_this_month['missing_count'] = len(due_this_month['missing_list'])
    due_this_month['completion_rate'] = round((due_this_month['completed'] / due_this_month['total'] * 100), 1) if due_this_month['total'] > 0 else 0
    due_this_month['conc_total_exceed'] = due_this_month['conc_internal_exceed'] + due_this_month['conc_legal_exceed']
    due_this_month['af_total_exceed'] = due_this_month['af_internal_exceed'] + due_this_month['af_legal_exceed']

    # 모달 필터용 전체 초과 건수 계산 (중복제거)
    overall_internal_exceed = 0
    overall_legal_exceed = 0
    for item in due_this_month['completed_list']:
        log = item['log']
        is_legal_exceed = log.substance_status == '법적초과' or log.airflow_status == '법적초과'
        is_internal_exceed = log.substance_status == '사내초과' or log.airflow_status == '사내초과'

        if is_legal_exceed:
            overall_legal_exceed += 1
        elif is_internal_exceed:
            overall_internal_exceed += 1
            
    due_this_month['overall_internal_exceed'] = overall_internal_exceed
    due_this_month['overall_legal_exceed'] = overall_legal_exceed

    # 4. 차트 데이터 가공 (물질별 그룹핑 및 스타일링)
    chart_qs = logs_qs
    if selected_substances:
        chart_qs = chart_qs.filter(Q(substance__name__in=selected_substances) | Q(raw_substance_name__in=selected_substances))
    
    chart_data = {}
    lines = chart_qs.values_list('facility__line', flat=True).distinct()
    
    # 물질별 색상 팔레트
    colors = ['#0d6efd', '#198754', '#6f42c1', '#fd7e14', '#20c997', '#d63384', '#ffc107', '#dc3545']
    color_map = {sub_name: colors[i % len(colors)] for i, sub_name in enumerate(selected_substances)}

    for line in lines:
        line_name = line if line else "라인 미지정"
        line_logs = chart_qs.filter(facility__line=line).order_by('facility__sec')
        
        if line_logs.exists():
            # 해당 라인의 모든 설비(SEC)를 X축 레이블로 사용
            all_labels = sorted(list(line_logs.values_list('facility__sec', flat=True).distinct()))
            datasets = []
            
            for sub_name in selected_substances:
                sub_logs = line_logs.filter(Q(substance__name=sub_name) | Q(raw_substance_name=sub_name))
                if not sub_logs.exists():
                    continue

                color = color_map.get(sub_name, '#6c757d') # color_map에 없는 경우 기본값
                
                # 물질의 기준값을 찾기 위해 대표 로그 하나를 선택
                rep_log = sub_logs.filter(substance__isnull=False).first()
                if not rep_log: continue

                val1 = rep_log.substance.val1
                val2 = rep_log.substance.val2
                
                # 1. 측정값 (점 형태)
                datasets.append({
                    'label': f'{sub_name} 측정값',
                    'data': [{'x': log.facility.sec, 'y': log.value} for log in sub_logs],
                    'backgroundColor': color,
                    'type': 'scatter',
                    'pointRadius': 6,
                    'order': 0 # 선보다 위에 표시
                })
                
                # 2. 사내기준 (점선)
                if val1 is not None:
                    datasets.append({
                        'label': f'{sub_name} 사내기준',
                        'data': [{'x': label, 'y': val1} for label in all_labels],
                        'borderColor': color,
                        'borderWidth': 2,
                        'type': 'line',
                        'borderDash': [5, 5],
                        'pointRadius': 0,
                        'fill': False,
                        'order': 1
                    })

                # 3. 법적기준 (실선)
                if val2 is not None:
                    datasets.append({
                        'label': f'{sub_name} 법적기준',
                        'data': [{'x': label, 'y': val2} for label in all_labels],
                        'borderColor': color,
                        'borderWidth': 2.5,
                        'type': 'line',
                        'pointRadius': 0,
                        'fill': False,
                        'order': 2
                    })

            chart_data[line_name] = {
                'labels': all_labels,
                'datasets': json.dumps(datasets)
            }
            
    # 5. 레거시 통계 (UI에서 제거되어 계산 불필요)
    # UI가 복구될 경우 이 부분도 '제출용' 기준으로 재계산 필요
    compliance_report = []
    completed_logs_detail = []
    counts = {'total': 0, 'completed': 0, 'normal': 0, 'internal_exceed': 0, 'legal_exceed': 0}

    context = {
        'logs': logs_qs.order_by('-date'),
        'all_substances': all_substances,
        'selected_substances': selected_substances,
        'selected_year': selected_year,
        'selected_month': selected_month,
        'year_range': range(now.year, now.year - 5, -1),
        'month_range': range(1, 13),
        'chart_data': chart_data,
        'active_tab': active_tab,

        'annual_total_required': annual_total_required,
        'annual_completion_rate': annual_completion_rate,
        'due_this_month': due_this_month,
        
        # 레거시 데이터 (호환성 유지)
        'compliance_report': compliance_report,
        'completed_logs_detail': completed_logs_detail,
        'counts': counts,
        'completed_count': counts['completed'],
        'missing_count': max(0, counts['total'] - counts['completed']),
    }
    return render(request, 'integrated/dashboard.html', context)

# 2. 기준 정보 설정 페이지
def settings_page(request):
    facilities = Facility.objects.all().order_by('sec')
    substances = Substance.objects.all().order_by('name')
    configs = MeasurementConfig.objects.select_related('facility', 'substance').all()
    active_configs = {(c.facility_id, c.substance_id) for c in configs}
    
    matrix_data = []
    for f in facilities:
        row = {'facility': f, 'substance_status': []}
        for s in substances:
            is_active = (f.id, s.id) in active_configs
            row['substance_status'].append({'is_active': is_active, 'val1': s.val1 if is_active else '-', 'val2': s.val2 if is_active else '-'})
        matrix_data.append(row)
    return render(request, 'integrated/settings.html', {'substances': substances, 'matrix_data': matrix_data})

# 3. 엑셀 데이터 분석/검증 API (데이터 유실 방지 강화)
@require_POST
def validate_excel_api(request):
    excel_file = request.FILES.get('file')
    if not excel_file: return JsonResponse({'error': '파일이 없습니다.'}, status=400)
    
    try:
        df = pd.read_excel(excel_file)
        results = []
        summary = {'total': 0, 'success': 0, 'warning': 0, 'error': 0}

        for index, row in df.iterrows():
            summary['total'] += 1
            raw_f = str(row.get('라인 방지시설(SEC)', row.get('세부라인 방지시설', ''))).strip()
            raw_s = str(row.get('물질', '')).strip()
            
            facility = Facility.objects.filter(Q(sec__iexact=raw_f) | Q(facility_no__iexact=raw_f)).first()
            substance = Substance.objects.filter(
                Q(name__iexact=raw_s) | Q(name__icontains=raw_s)
            ).first()
            
            try: val = float(row.get('농도', 0))
            except: val = 0
            try: af = float(row.get('풍량', 0))
            except: af = 0

            extra = {
                'sampling_time_text': str(row.get('채취시간', '')),
                'air_flow': af,
                'weather': str(row.get('날씨', '')),
                'temp': row.get('기온', 0),
                'humidity': row.get('습도', 0),
                'pressure': row.get('대기압', 0),
                'wind_dir': str(row.get('풍향', '')),
                'wind_speed': row.get('풍속', 0),
                'gas_speed': row.get('가스속도m/s', row.get('가스속도(m/s)', 0)),
                'gas_temp': row.get('가스온도', row.get('가스온도(℃)', 0)),
                'moisture': row.get('수분함량', row.get('수분(%)', 0)),
                'agency': str(row.get('검사기관', '-')),
            }

            status, msg = 'success', '정상'
            conc_status, af_status, legal_ref_status = '정상', '정상', '참고'

            if not facility:
                status, msg = 'error', f'설비[{raw_f}] 미등록'
                summary['error'] += 1
            else:
                # 풍량 상태 계산
                capacity = max(facility.capacity_ncmm or 0, facility.capacity_acmm or 0)
                if capacity > 0:
                    if af > capacity:
                        af_status = '법적초과'
                    elif af > (capacity * 0.9):
                        af_status = '사내초과'

                if not substance:
                    status, msg = 'warning', f'물질[{raw_s}] 미등록'
                    summary['warning'] += 1 # 미등록도 일단 성공으로 집계 가능
                else:
                    legal_ref_status = substance.legal_type or '법적'
                    summary['success'] += 1
                    # 농도 상태 계산
                    if substance.val2 is not None and val > substance.val2:
                        conc_status = '법적초과'
                    elif substance.val1 is not None and val > substance.val1:
                        conc_status = '사내초과'

            results.append({
                'row': index + 2,
                'facility_id': facility.id if facility else None,
                'substance_id': substance.id if substance else None,
                'facility_name': facility.sec if facility else raw_f,
                'substance_name': substance.name if substance else raw_s,
                'value': val,
                'date': str(row.get('채취일시', ''))[:10],
                'extra_data': extra,
                'status': status, # 행 전체의 유효성 (error, warning, success)
                'conc_status': conc_status,
                'af_status': af_status,
                'legal_ref_status': legal_ref_status,
                'msg': msg
            })
        return JsonResponse({'results': results, 'summary': summary})
    except Exception as e: return JsonResponse({'error': str(e)}, status=500)

# 4. 최종 데이터 저장 API
@require_POST  
def save_excel_data_api(request):  
    try:  
        body = json.loads(request.body)  
        final_data_list = body.get('data', [])
        saved_cnt, error_list = ExcelValidationService.save_final_data(final_data_list)
        return JsonResponse({'status': 'success', 'saved_count': saved_cnt, 'error_count': len(error_list)})
    except Exception as e: return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

# 5. [수정됨] 마스터 정보 일괄 임포트 API (urls.py 에러 해결)
@require_POST
def import_master_api(request):
    data_type = request.POST.get('type')
    excel_file = request.FILES.get('file')
    try:
        if data_type == 'facility': count = ExcelValidationService.import_facilities(excel_file)
        elif data_type == 'substance': count = ExcelValidationService.import_substances(excel_file)
        elif data_type == 'config': count = ExcelValidationService.import_configs(excel_file)
        else: return JsonResponse({'error': '잘못된 타입입니다.'}, status=400)
        return JsonResponse({'message': f'{count}건 반영 완료'})
    except Exception as e: return JsonResponse({'error': str(e)}, status=500)

# 6. 개별 마스터 데이터 삭제 API
@require_POST
def delete_master_api(request):
    data_type = request.POST.get('type')
    data_id = request.POST.get('id')
    try:
        if data_type == 'facility': obj = get_object_or_404(Facility, id=data_id)
        elif data_type == 'substance': obj = get_object_or_404(Substance, id=data_id)
        else: return JsonResponse({'error': '잘못된 타입입니다.'}, status=400)
        obj.delete()
        return JsonResponse({'status': 'success'})
    except Exception as e: return JsonResponse({'error': str(e)}, status=500)

# 7. 설정 및 상세 조회 API
def get_facility_config_api(request, facility_id):
    facility = get_object_or_404(Facility, id=facility_id)
    substances = Substance.objects.all().order_by('name')
    configs = MeasurementConfig.objects.filter(facility=facility).values_list('substance_id', flat=True)
    substance_list = [{'id': s.id, 'name': s.name, 'unit': s.unit, 'val1': s.val1, 'val2': s.val2, 'is_active': s.id in configs} for s in substances]
    return JsonResponse({'facility_name': facility.sec, 'substances': substance_list})

@require_POST
def save_facility_config_api(request):
    data = json.loads(request.body)
    facility = Facility.objects.get(id=data.get('facility_id'))
    for item in data.get('items', []):
        sub = Substance.objects.get(id=item['substance_id'])
        if item['is_active']: MeasurementConfig.objects.get_or_create(facility=facility, substance=sub)
        else: MeasurementConfig.objects.filter(facility=facility, substance=sub).delete()
    return JsonResponse({'status': 'success'})

def get_facility_detail_api(request, facility_id):
    f = get_object_or_404(Facility, id=facility_id)
    return JsonResponse({'id': f.id, 'sec': f.sec, 'facility_no': f.facility_no, 'prevent_no': f.prevent_no, 'company_no': f.company_no, 'workplace': f.workplace, 'line': f.line, 'exhaust': f.exhaust, 'capacity': f.capacity, 'diameter': f.diameter, 'tms_yn': f.tms_yn, 'status': f.status})

@require_POST
def save_facility_detail_api(request):
    data = json.loads(request.body)
    f = Facility.objects.get(id=data['id']) if data.get('id') else Facility()
    for key, val in data.items(): 
        if hasattr(f, key): setattr(f, key, val)
    f.save()
    return JsonResponse({'status': 'success'})

# 8. 로그 상세 수정 및 삭제 API (제출용 플래그 포함)
def get_log_detail_api(request, log_id):
    log = get_object_or_404(DailyLog, id=log_id)
    capa = max(log.facility.capacity_ncmm or 0, log.facility.capacity_acmm or 0)
    return JsonResponse({
        'id': log.id,
        'facility_sec': log.facility.sec,
        'substance_name': log.substance.name if log.substance else log.raw_substance_name,
        'sub_val1': log.substance.val1 if log.substance else '-',
        'sub_val2': log.substance.val2 if log.substance else '-',
        'capa_max': capa,
        'date': log.date.strftime('%Y-%m-%d'),
        'sampling_time': log.sampling_time_text or '',
        'value': log.value,
        'airflow': log.air_flow or 0,
        'weather': log.weather or '',
        'temp': log.temp or 0,
        'humidity': log.humidity or 0,
        'pressure': log.pressure or 0,
        'wind_dir': log.wind_dir or '',
        'wind_speed': log.wind_speed or 0,
        'gas_speed': log.gas_speed or 0,
        'gas_temp': log.gas_temp or 0,
        'moisture': log.moisture or 0,
        'emission_rate': log.emission_rate or 0,
        'agency': log.agency or '',
        'is_report_data': log.is_report_data,
    })

@require_POST
def save_log_edit_api(request):
    try:
        data = json.loads(request.body)
        log = DailyLog.objects.get(id=data.get('id'))
        log.date, log.sampling_time_text = data.get('date'), data.get('sampling_time')
        log.value, log.air_flow = float(data.get('value', 0)), float(data.get('airflow', 0))
        log.weather, log.temp, log.humidity = data.get('weather'), float(data.get('temp', 0)), float(data.get('humidity', 0))
        log.pressure, log.wind_dir, log.wind_speed = float(data.get('pressure', 0)), data.get('wind_dir'), float(data.get('wind_speed', 0))
        log.gas_speed, log.gas_temp, log.moisture = float(data.get('gas_speed', 0)), float(data.get('gas_temp', 0)), float(data.get('moisture', 0))
        log.agency = data.get('agency')
        log.is_report_data = data.get('is_report_data', False)
        log.save()
        return JsonResponse({'status': 'success'})
    except Exception as e: return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
def delete_log_api(request):
    DailyLog.objects.filter(id=json.loads(request.body).get('id')).delete()
    return JsonResponse({'status': 'success'})

@require_POST
def delete_selected_items_api(request):
    data = json.loads(request.body)
    count = DailyLog.objects.filter(id__in=data.get('ids', [])).delete()[0]
    return JsonResponse({'status': 'success', 'message': f'{count}건 삭제 완료'})

# 9. 다운로드 기능 (배출량 제거 버전)
def download_excel_sample(request):
    columns = ['채취월', '라인 방지시설(SEC)', '채취일시', '채취시간', '검사기관', '물질', '농도', '풍량', '날씨', '기온', '습도', '대기압', '풍향', '풍속', '가스속도m/s', '가스온도', '수분함량']
    df = pd.DataFrame([['3월', 'EQP-SCR-01', '2026-03-15', '10:00~11:00', '(주)세이프', 'NOx', 25.1, 500, '맑음', 15, 45, 1013, '남서', 2.1, 12, 35, 1.2]], columns=columns)
    with BytesIO() as b:
        with pd.ExcelWriter(b, engine='openpyxl') as writer: df.to_excel(writer, index=False)
        return HttpResponse(b.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename=Integrated_Sample.xlsx'})

def download_settings_sample(request):
    """DB 데이터 기반의 최신 양식을 생성하여 다운로드합니다."""
    target = request.GET.get('target')
    
    with BytesIO() as b:
        with pd.ExcelWriter(b, engine='openpyxl') as writer:
            if target == 'facility':
                # Facility 모델의 모든 필드를 반영한 최신 양식
                columns = [
                    '시설번호', '방지시설번호', '업체번호', '세부라인 방지시설(SEC)', '사업장', 
                    '라인', '배기', '용량', '용량(NCMM)', '용량(ACMM)', 'TMS', '운영/폐쇄', '직경'
                ]
                sample_data = [[
                    'F-001', 'P-101', 'C-001', 'EQP-SCR-01', '본사', 'A-LINE', 'E-01', 
                    '1000', 650, 600, 'X', '운영', '1200'
                ]]
                df = pd.DataFrame(sample_data, columns=columns)
                df.to_excel(writer, index=False, sheet_name='설비마스터_양식')

            elif target == 'config':
                # DB의 시설/물질 기준으로 통합 기준 관리 양식 생성
                facilities = Facility.objects.all().order_by('sec')
                substances = Substance.objects.all().order_by('name')
                
                # 활성화된 설정(필수 측정 항목) 미리 로드
                active_configs = set(MeasurementConfig.objects.values_list('facility_id', 'substance_id'))
                
                header = ['세부라인 방지시설(SEC)']
                for sub in substances:
                    header.append(f'{sub.name}_사내')
                    header.append(f'{sub.name}_법적')
                
                data_rows = []
                for fac in facilities:
                    row = {'세부라인 방지시설(SEC)': fac.sec}
                    for sub in substances:
                        # 해당 시설-물질 조합이 활성화된 경우에만 기준값 표시
                        if (fac.id, sub.id) in active_configs:
                            row[f'{sub.name}_사내'] = sub.val1 if sub.val1 is not None else ''
                            row[f'{sub.name}_법적'] = sub.val2 if sub.val2 is not None else ''
                        else:
                            row[f'{sub.name}_사내'] = ''
                            row[f'{sub.name}_법적'] = ''
                    data_rows.append(row)
                
                df = pd.DataFrame(data_rows)
                df.to_excel(writer, index=False, sheet_name='통합기준관리_양식')

        filename = f"Settings_Sample_{target}.xlsx"
        return HttpResponse(
            b.getvalue(), 
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 
            headers={'Content-Disposition': f'attachment; filename*=UTF-8\'\'{filename}'}
        )

def get_substance_detail_api(request, substance_id):
    s = get_object_or_404(Substance, id=substance_id)
    return JsonResponse({'id': s.id, 'name': s.name, 'unit': s.unit, 'formula': s.formula, 'legal_type': s.legal_type, 'cycle': s.cycle})

@require_POST  
def save_substance_api(request):  
    data = json.loads(request.body)
    try:  
        with transaction.atomic():  
            sub = Substance.objects.get(id=data['id']) if data.get('id') else Substance()
            sub.name, sub.unit, sub.formula = data['name'], data['unit'], data['formula']
            sub.legal_type, sub.cycle = data['legal_type'], data['cycle']
            sub.save()
        return JsonResponse({'status': 'success'})  
    except Exception as e: return JsonResponse({'error': str(e)}, status=500)