import pandas as pd
import numpy as np
from django.db.models import Q
from django.db import transaction
from .models import Facility, Substance, DailyLog, MeasurementConfig

class ExcelValidationService:
    @staticmethod
    def get_sheet_names(file):
        try:
            xl = pd.ExcelFile(file)
            return xl.sheet_names
        except Exception as e: return None

    @staticmethod
    def validate_excel_upload(file, sheet_name=0):
        # 기존의 19개 컬럼 검증 로직 그대로 유지
        try:
            df = pd.read_excel(file, sheet_name=sheet_name)
            df.columns = [c.strip() for c in df.columns]
            df['채취일시'] = pd.to_datetime(df['채취일시'], errors='coerce')
        except Exception as e: return {"error": f"엑셀 읽기 실패: {str(e)}"}, {}, []

        results, summary, uploaded_pairs = [], {"total": 0, "success": 0, "warning": 0, "duplicate": 0, "error": 0}, set()
        def clean_float(val):
            try: return float(val) if not pd.isna(val) and str(val).strip() != '' else 0.0
            except: return 0.0

        for index, row in df.iterrows():
            if pd.isna(row['채취일시']): 
                summary["error"] += 1
                continue
            
            summary["total"] += 1
            f_sec = str(row.get('세부라인 방지시설', '')).strip()
            s_name = str(row.get('물질', '')).strip()
            facility = Facility.objects.filter(sec=f_sec).first()
            substance = Substance.objects.filter(name=s_name).first()

            if not facility or not substance:
                summary["error"] += 1
                continue

            raw_date = row['채취일시'].date()
            raw_value = clean_float(row.get('농도'))
            uploaded_pairs.add((facility.id, substance.id))

            # 중복/기준체크 로직 (기존 유지)
            is_valid = ExcelValidationService.check_value_range_precise(substance, raw_value)
            existing = DailyLog.objects.filter(facility=facility, date=raw_date, substance=substance).first()
            status = 'duplicate' if existing else ('warning' if not is_valid else 'success')
            summary[status] += 1

            results.append({
                'row': index + 2, 'facility_id': facility.id, 'substance_id': substance.id,
                'facility_name': facility.sec, 'manage_no': facility.facility_no,
                'date': raw_date.strftime('%Y-%m-%d'), 'substance_name': substance.name,
                'value': raw_value, 'status': status, 'msg': '정상' if status=='success' else status,
                'extra_data': {
                    'collection_month': str(row.get('채취월', '3월')).strip(),
                    'sampling_time_text': str(row.get('채취시간', '')),
                    'inspection_agency': str(row.get('검사기관', '')),
                    'air_flow': clean_float(row.get('풍량')),
                    'weather': str(row.get('날씨', '')),
                    'temp': clean_float(row.get('기온')),
                    'emission_rate': clean_float(row.get('배출량(kg/day)'))
                }
            })
        return results, summary, ExcelValidationService.check_missing_entries(uploaded_pairs)

    @staticmethod
    def check_value_range_precise(substance, value):
        try:
            val = float(value)
            op, v1, v2 = substance.operator, substance.val1, substance.val2
            if op == '<=': return val <= v1
            if op == '>=': return val >= v1
            if op == '<':  return val < v1
            if op == '>':  return val > v1
            if op == '[]' and v2: return v1 <= val <= v2
            return False
        except: return False

    @staticmethod
    def check_missing_entries(uploaded_pairs):
        configs = MeasurementConfig.objects.select_related('facility', 'substance').all()
        return [{'facility': c.facility.sec, 'substance': c.substance.name} for c in configs if (c.facility_id, c.substance_id) not in uploaded_pairs]

    @staticmethod
    @transaction.atomic
    def save_final_data(data_list):
        saved_count = 0
        for item in data_list:
            # 1. 대상 객체 확보
            facility = Facility.objects.get(id=item['facility_id'])
            substance = Substance.objects.get(id=item['substance_id'])
            extra = item.get('extra_data', {})
            
            # 2. 채취월 문자열 생성 (예: 3 -> 3월)
            date_obj = pd.to_datetime(item['date'])
            month_str = f"{date_obj.month}월"

            # 3. 데이터 생성 또는 업데이트
            DailyLog.objects.update_or_create(
                facility=facility,
                substance=substance,
                date=item['date'],
                defaults={
                    'collection_month': month_str,
                    'sampling_time_text': extra.get('sampling_time_text', ''),
                    'value': item['value'],
                    'air_flow': extra.get('air_flow', 0),
                    'weather': extra.get('weather', ''),
                    'temp': extra.get('temp', 0),
                    'humidity': extra.get('humidity', 0),
                    'pressure': extra.get('pressure', 0),
                    'wind_dir': extra.get('wind_dir', ''),
                    'wind_speed': extra.get('wind_speed', 0),
                    'gas_speed': extra.get('gas_speed', 0),
                    'gas_temp': extra.get('gas_temp', 0),
                    'emission_rate': extra.get('emission_rate', 0),
                    'agency': extra.get('agency', '-'),
                }
            )
            saved_count += 1
        return saved_count

    @staticmethod
    @transaction.atomic
    def import_configs(file):
        """[최종 보완] 통합 매트릭스 업로드: 설비가 없으면 자동 생성 후 매핑"""
        df = pd.read_excel(file)
        df.columns = [c.strip() for c in df.columns]
        substances = Substance.objects.all()
        count = 0

        for _, row in df.iterrows():
            f_sec = str(row.get('세부라인 방지시설', '')).strip()
            if not f_sec or f_sec == 'nan': continue

            # 1. 설비가 DB에 없으면 자동으로 마스터에 등록
            # (시설번호 등 상세 정보는 나중에 설비관리에서 수정 가능)
            facility, created = Facility.objects.get_or_create(
                sec=f_sec,
                defaults={
                    'facility_no': f'NEW-{f_sec[:5]}', # 임시 번호 부여
                    'workplace': '본사',
                    'status': '운영'
                }
            )

            for s in substances:
                val_internal = row.get(f'{s.name}_사내')
                val_legal = row.get(f'{s.name}_법적')
                
                # 엑셀 칸에 사내기준이 적혀있는 경우에만 매핑
                if not pd.isna(val_internal) and str(val_internal).strip() != '':
                    # 물질 기준치 동기화
                    s.val1 = float(val_internal)
                    if not pd.isna(val_legal): 
                        s.val2 = float(val_legal)
                    s.save()
                    
                    # 필수 측정 매핑 생성
                    MeasurementConfig.objects.get_or_create(facility=facility, substance=s)
                    count += 1
                else:
                    # 빈칸이면 매핑 삭제
                    MeasurementConfig.objects.filter(facility=facility, substance=s).delete()
        return count

    @staticmethod
    @transaction.atomic
    def import_facilities(file):
        """설비 마스터 엑셀 일괄 임포트 (13개 컬럼 대응)"""
        df = pd.read_excel(file)
        df.columns = [c.strip() for c in df.columns]
        for _, row in df.iterrows():
            sec_name = str(row.get('세부라인 방지시설(SEC)', '')).strip()
            if not sec_name or sec_name == 'nan': continue
            
            Facility.objects.update_or_create(
                sec=sec_name,
                defaults={
                    'facility_no': row.get('시설번호'),
                    'prevent_no': row.get('방지시설번호'),
                    'company_no': row.get('업체번호'),
                    'workplace': row.get('사업장', '본사'),
                    'line': row.get('라인'),
                    'exhaust': row.get('배기'),
                    'line_exhaust': row.get('라인 배기'),
                    'common_name': row.get('라인 세부 방지(공통)'),
                    'capacity': row.get('용량'),
                    'tms_yn': row.get('TMS', 'X'),
                    'status': row.get('운영/폐쇄', '운영'),
                    'diameter': row.get('직경'),
                }
            )
        return len(df)

    @staticmethod
    @transaction.atomic
    def import_substances(file):
        df = pd.read_excel(file)
        for _, row in df.iterrows():
            Substance.objects.update_or_create(
                name=str(row['물질명']).strip(),
                defaults={'val1': float(row['사내기준']), 'val2': float(row.get('법적기준', 0)), 'unit': row.get('단위', 'ppm')}
            )
        return len(df)