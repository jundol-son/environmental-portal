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

# 1. 통합 대시보드 (업로드 기능 통합 및 중복 측정 체크)
def dashboard_page(request):
    """선택한 년/월 기준 이행률 대시보드 및 상세 분석"""
    now = timezone.now()
    selected_year = request.GET.get('year', str(now.year))
    selected_month = request.GET.get('month', str(now.month))
    month_str = f"{selected_month}월"

    # A. 상세 로그 데이터 (테이블 출력용)
    logs = DailyLog.objects.filter(
        collection_month=month_str,
        date__year=selected_year 
    ).select_related('facility', 'substance').order_by('-date', 'facility__sec')

    # B. 필수 측정 항목 대비 현황 분석
    configs = MeasurementConfig.objects.select_related('facility', 'substance').all()
    
    compliance_report = []      # 누락(미측정) 항목 담기
    completed_logs_detail = []  # 측정 완료 상세 담기
    
    counts = {
        'total': configs.count(),
        'completed': 0,
        'normal': 0,
        'internal_exceed': 0,
        'legal_exceed': 0      
    }

    for config in configs:
        measured_logs = DailyLog.objects.filter(
            facility=config.facility,
            substance=config.substance,
            collection_month=month_str,
            date__year=selected_year
        )
        
        log_count = measured_logs.count()
        
        if log_count > 0:
            counts['completed'] += 1
            max_val_log = measured_logs.order_by('-value').first()
            val = max_val_log.value
            
            if config.substance.val2 and val > config.substance.val2:
                status_tag, status_cls = "법적초과", "text-danger fw-bold"
                counts['legal_exceed'] += 1
            elif val > config.substance.val1:
                status_tag, status_cls = "사내초과", "text-warning fw-bold"
                counts['internal_exceed'] += 1
            else:
                status_tag, status_cls = "정상", "text-success"
                counts['normal'] += 1

            completed_logs_detail.append({
                'facility_sec': config.facility.sec,
                'facility_no': config.facility.facility_no,
                'substance_name': config.substance.name,
                'value': val,
                'status_tag': status_tag,
                'status_cls': status_cls,
                'log_count': log_count
            })
        else:
            compliance_report.append({
                'facility_sec': config.facility.sec,
                'facility_no': config.facility.facility_no,
                'substance_name': config.substance.name,
                'status_text': '미측정(누락)',
                'status_class': 'text-danger fw-bold'
            })

    completion_rate = round((counts['completed'] / counts['total'] * 100), 1) if counts['total'] > 0 else 0

    return render(request, 'integrated/dashboard.html', {
        'logs': logs,
        'compliance_report': compliance_report,
        'completed_logs_detail': completed_logs_detail,
        'counts': counts,
        'selected_year': selected_year,
        'selected_month': selected_month,
        'completion_rate': completion_rate,
        'total_required': counts['total'],
        'completed_count': counts['completed'],
        'missing_count': counts['total'] - counts['completed'],
        'year_range': range(now.year, now.year - 5, -1),
        'month_range': range(1, 13)
    })

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
            row['substance_status'].append({
                'is_active': is_active,
                'val1': s.val1 if is_active else '-',
                'val2': s.val2 if is_active else '-'
            })
        matrix_data.append(row)
    return render(request, 'integrated/settings.html', {'substances': substances, 'matrix_data': matrix_data})

# 3. [핵심 업데이트] 엑셀 데이터 분석/검증 API (4중 식별 + 행별 기준 체크)
@require_POST
def validate_excel_api(request):
    excel_file = request.FILES.get('file')
    sheet_name = request.POST.get('sheet_name')
    if not excel_file: return JsonResponse({'error': '파일이 없습니다.'}, status=400)
    all_sheets = ExcelValidationService.get_sheet_names(excel_file)
    target_sheet = sheet_name if sheet_name else all_sheets[0]
    
    try:
        df = pd.read_excel(excel_file, sheet_name=target_sheet)
        results = []
        summary = {'total': 0, 'success': 0, 'exceed': 0, 'error': 0}

        for index, row in df.iterrows():
            summary['total'] += 1
            raw_facility = str(row.get('라인 방지시설(SEC)', row.get('세부라인 방지시설', ''))).strip()
            raw_substance = str(row.get('물질', '')).strip()
            try:
                value = float(row.get('농도', 0))
            except:
                value = 0
            
            # 1. 설비 식별 (4종 번호 매칭)
            facility = Facility.objects.filter(
                Q(sec__iexact=raw_facility) | Q(facility_no__iexact=raw_facility) | 
                Q(prevent_no__iexact=raw_facility) | Q(company_no__iexact=raw_facility)
            ).first()
            
            # 2. 물질 식별 (포함 검색을 더 정교하게 하여 기준치가 있는 Substance 매칭)
            substance = Substance.objects.filter(
                Q(name__iexact=raw_substance) | Q(name__icontains=raw_substance)
            ).first()
            
            status, msg = 'success', '정상'
            
            if not facility:
                status, msg = 'error', f'설비[{raw_facility}] 미등록'
                summary['error'] += 1
            elif not substance:
                status, msg = 'error', f'물질[{raw_substance}] 미등록'
                summary['error'] += 1
            else:
                # 3. 정밀 기준 초과 검증 (실제 수치 비교)
                if substance.val2 and value > substance.val2:
                    status, msg = 'danger', f'법적기준 초과 (기준: {substance.val2})'
                    summary['exceed'] += 1
                elif substance.val1 and value > substance.val1:
                    status, msg = 'warning', f'사내기준 초과 (기준: {substance.val1})'
                    summary['exceed'] += 1
                else:
                    summary['success'] += 1

            results.append({
                'row': index + 2,
                'facility_id': facility.id if facility else None,
                'substance_id': substance.id if substance else None,
                'facility_name': facility.sec if facility else raw_facility,
                'substance_name': substance.name if substance else raw_substance,
                'value': value,
                'date': str(row.get('채취일시', ''))[:10],
                'extra_data': {
                    'sampling_time_text': str(row.get('채취시간', '')),
                    'air_flow': row.get('풍량', 0),
                    'weather': str(row.get('날씨', '')),
                    'temp': row.get('기온', 0),
                    'humidity': row.get('습도', 0),
                    'pressure': row.get('대기압', 0),
                    'wind_dir': str(row.get('풍향', '')),
                    'wind_speed': row.get('풍속', 0),
                    'gas_speed': row.get('가스속도m/s', row.get('가스속도(m/s)', 0)),
                    'gas_temp': row.get('가스온도', row.get('가스온도(℃)', 0)),
                    'emission_rate': row.get('배출량(kg/d)', row.get('배출량(kg/day)', 0)),
                    'agency': str(row.get('검사기관', '-')),
                },
                'status': status,
                'msg': msg
            })

        return JsonResponse({'requires_sheet_selection': False, 'results': results, 'summary': summary})
    except Exception as e: return JsonResponse({'error': str(e)}, status=500)

# 4. 최종 데이터 저장 API
@require_POST  
def save_excel_data_api(request):  
    """최종 데이터 저장 API – 성공·오류 정보를 모두 반환"""  
    try:  
        body = json.loads(request.body)  
        final_data_list = body.get('data', [])

        if not final_data_list:  
            return JsonResponse(  
                {'status': 'error',  
                 'message': '저장할 데이터가 없습니다.'},  
                status=400  
            )

        # 서비스 → (성공 건수, 오류 리스트) 반환  
        saved_cnt, error_list = ExcelValidationService.save_final_data(final_data_list)

        # ---------- 여기서 필드명을 반드시 saved_count 로 고정 ----------  
        resp = {  
            'status': 'success',  
            'saved_count': saved_cnt,                 # ← 반드시 이 이름  
            'error_count': len(error_list),  
            'message': f'총 {saved_cnt}건을 저장했습니다.',  
            'errors': error_list[:20]                # 필요 시 전체를 반환하거나 페이지네이션  
        }  
        return JsonResponse(resp)

    except Exception as e:  
        import traceback, logging  
        logging.getLogger('excel_import').error(traceback.format_exc())  
        return JsonResponse(  
            {'status': 'error',  
             'message': f'서버 오류: {str(e)}'},  
            status=500  
        )  

    
# 5. 마스터 정보 일괄 임포트 API
@require_POST
def import_master_api(request):
    data_type = request.POST.get('type')
    excel_file = request.FILES.get('file')
    try:
        if data_type == 'facility': count = ExcelValidationService.import_facilities(excel_file)
        elif data_type == 'substance': count = ExcelValidationService.import_substances(excel_file)
        elif data_type == 'config': count = ExcelValidationService.import_configs(excel_file)
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
        elif data_type == 'config': obj = get_object_or_404(MeasurementConfig, id=data_id)
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
    try:
        data = json.loads(request.body)
        facility = Facility.objects.get(id=data.get('facility_id'))
        with transaction.atomic():
            for item in data.get('items', []):
                substance = Substance.objects.get(id=item['substance_id'])
                substance.val1, substance.val2 = item['val1'], item['val2']
                substance.save()
                if item['is_active']: MeasurementConfig.objects.get_or_create(facility=facility, substance=substance)
                else: MeasurementConfig.objects.filter(facility=facility, substance=substance).delete()
        return JsonResponse({'status': 'success'})
    except Exception as e: return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

# 상세 정보 조회
def get_facility_detail_api(request, facility_id):
    f = get_object_or_404(Facility, id=facility_id)
    return JsonResponse({
        'id': f.id,
        'sec': f.sec,
        'facility_no': f.facility_no,
        'prevent_no': f.prevent_no,
        'company_no': f.company_no, # 업체번호
        'workplace': f.workplace,
        'line': f.line,
        'exhaust': f.exhaust,
        'capacity': f.capacity,
        'diameter': f.diameter,     # 직경
        'tms_yn': f.tms_yn,
        'status': f.status,
    })

# 저장 (신규/수정 통합)
@require_POST
def save_facility_detail_api(request):
    data = json.loads(request.body)
    f_id = data.get('id')
    if f_id:
        f = Facility.objects.get(id=f_id)
    else:
        f = Facility()
    
    f.sec = data.get('sec')
    f.facility_no = data.get('facility_no')
    f.prevent_no = data.get('prevent_no')
    f.company_no = data.get('company_no') # 업체번호 매핑
    f.workplace = data.get('workplace')
    f.line = data.get('line')
    f.exhaust = data.get('exhaust')
    f.capacity = data.get('capacity')
    f.diameter = data.get('diameter')     # 직경 매핑
    f.tms_yn = data.get('tms_yn')
    f.status = data.get('status')
    f.save()
    return JsonResponse({'status': 'success'})

# 8. 대시보드 상세 수정 API (엑셀의 모든 필드 매핑)
def get_log_detail_api(request, log_id):
    log = get_object_or_404(DailyLog, id=log_id)
    return JsonResponse({
        'id': log.id,
        'facility_sec': log.facility.sec,
        'substance_name': log.substance.name,
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
        'moisture': log.moisture or 0,  # [변경] water_content -> moisture
        'emission_rate': log.emission_rate or 0,
        'agency': log.agency or '',
    })

@require_POST
def save_log_edit_api(request):
    try:
        data = json.loads(request.body)
        log = DailyLog.objects.get(id=data.get('id'))
        
        log.date = data.get('date')
        log.sampling_time_text = data.get('sampling_time')
        log.value = data.get('value')
        log.air_flow = data.get('airflow')
        log.weather = data.get('weather')
        log.temp = data.get('temp')
        log.humidity = data.get('humidity')
        log.pressure = data.get('pressure')
        log.wind_dir = data.get('wind_dir')
        log.wind_speed = data.get('wind_speed')
        log.gas_speed = data.get('gas_speed')
        log.gas_temp = data.get('gas_temp')
        log.moisture = data.get('moisture') # [변경] water_content -> moisture
        log.emission_rate = data.get('emission_rate')
        log.agency = data.get('agency')
        log.save()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
def delete_log_api(request):
    try:
        data = json.loads(request.body)
        DailyLog.objects.filter(id=data.get('id')).delete()
        return JsonResponse({'status': 'success'})
    except Exception as e: return JsonResponse({'status': 'error'}, status=500)

# 9. 다운로드 기능
def download_excel_sample(request):
    columns = ['채취월', '라인 방지시설(SEC)', '채취일시', '채취시간', '검사기관', '물질', '농도', '풍량', '날씨', '기온', '습도', '대기압', '풍향', '풍속', '가스속도m/s', '가스온도', '수분함량', '출량(kg/d)']
    df = pd.DataFrame([{'채취월': '3월', '라인 방지시설(SEC)': 'EQP-SCR-01', '채취일시': '2026-03-15', '채취시간': '10:00~11:00', '물질': 'HCL', '농도': 12.5, '풍량': 500, '날씨': '맑음', '기온': 15, '출량(kg/d)': 1.25}], columns=columns)
    with BytesIO() as b:
        with pd.ExcelWriter(b, engine='openpyxl') as writer: df.to_excel(writer, index=False)
        return HttpResponse(b.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename=Integrated_Data_Sample.xlsx'})

def download_settings_sample(request):
    target = request.GET.get('target')
    with BytesIO() as b:
        with pd.ExcelWriter(b, engine='openpyxl') as writer:
            if target == 'facility':
                columns = ['시설번호', '방지시설번호', '업체번호', '세부라인 방지시설(SEC)', '사업장', '라인', '배기', '라인 배기', '라인 세부 방지(공통)', '용량', 'TMS', '운영/폐쇄', '직경']
                df = pd.DataFrame([['F-001', 'P-101', 'C-501', 'EQP-SCR-01', '본사', '1라인', 'SCR', '1라인 SCR', '가스세정시설', '500', 'X', '운영', '1200']], columns=columns)
            else:
                substances = Substance.objects.all().order_by('name')
                columns = ['세부라인 방지시설']
                for s in substances: columns.extend([f'{s.name}_법적', f'{s.name}_사내', f'{s.name}_단위'])
                sample_row = ['EQP-SCR-01']
                for s in substances: sample_row.extend([10.0, 5.0, s.unit])
                df = pd.DataFrame([sample_row], columns=columns)
            df.to_excel(writer, index=False)
        return HttpResponse(b.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename=Sample.xlsx'})

def get_substance_detail_api(request, substance_id):
    s = get_object_or_404(Substance, id=substance_id)
    return JsonResponse({
        'id': s.id,
        'name': s.name,
        'unit': s.unit,
        'formula': s.formula,
        'legal_type': s.legal_type, # 추가
        'cycle': s.cycle,           # 추가
    })     

@require_POST  
def save_substance_api(request):  
    data = json.loads(request.body)

    # [수정] 필수값 검사 (name, unit, formula, legal_type, cycle 모두 포함)
    required = ['name', 'unit', 'formula', 'legal_type', 'cycle']  
    for k in required:  
        if not data.get(k):  
            return JsonResponse({'error': f'"{k}" 필드는 필수입니다.'}, status=400)

    try:  
        with transaction.atomic():  
            if data.get('id'): # 수정 모드
                sub = Substance.objects.select_for_update().get(id=data['id'])  
                sub.name = data['name']  
                sub.unit = data['unit']  
                sub.formula = data['formula']  
                sub.legal_type = data['legal_type']
                sub.cycle = data['cycle']
                sub.save()  
                msg = '물질 정보가 정상적으로 수정되었습니다.'  
            else: # 신규 등록 모드
                Substance.objects.create(  
                    name=data['name'],  
                    unit=data['unit'],  
                    formula=data['formula'],
                    legal_type=data['legal_type'],
                    cycle=data['cycle']
                )  
                msg = '새 물질이 추가되었습니다.'

        return JsonResponse({'status': 'success', 'message': msg})  
    except IntegrityError:  # 중복 이름 방지
        return JsonResponse({'error': '동일한 물질명이 이미 존재합니다.'}, status=409)  
    except Exception as e:  
        return JsonResponse({'error': str(e)}, status=500)  
