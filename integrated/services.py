import pandas as pd  
import numpy as np  
import re  
import datetime  
from django.db.models import Q  
from django.db import transaction  
from .models import Facility, Substance, DailyLog, MeasurementConfig


class ExcelValidationService:  
    """  
    엑셀 파일 검증·저장·마스터 임포트 전용 서비스.  
    - 날짜 파싱 로직을 강화해 `20250102`, `2025-01-02`, `2025/01/02`, `250102` 등  
      다양한 포맷을 지원합니다.  
    - `save_final_data()` 가 개별 레코드 오류를 누적하고 전체 성공 건수를  
      반환하도록 설계되었습니다.  
    - 물질 마스터 임포트 시 `계산식(formula)` 컬럼을 지원합니다.  
    """

    # -----------------------------------------------------------------  
    # 0️⃣ 공통 헬퍼  
    # -----------------------------------------------------------------  
    @staticmethod  
    def _clean_float(val):  
        """  
        빈값·NaN 을 0.0 으로 변환하고, 문자열이면 float 로 캐스팅합니다.  
        """  
        try:  
            return float(val) if not pd.isna(val) and str(val).strip() != '' else 0.0  
        except Exception:  
            return 0.0

    @staticmethod  
    def _parse_date(raw):  
        """  
        엑셀 혹은 프론트엔드에서 받은 날짜 문자열을 datetime.date 로 변환합니다.  
        지원 포맷  
            - YYYYMMDD (예: 20250102)  
            - YYMMDD   (70~99 → 19xx, 00~69 → 20xx)  
            - YYYY‑MM‑DD  
            - YYYY/MM/DD  
            - datetime/date 객체 자체  
        파싱에 실패하면 None 을 반환합니다.  
        """  
        if not raw:  
            return None

        # 이미 datetime/date 객체이면 그대로 반환  
        if isinstance(raw, (datetime.date, datetime.datetime)):  
            return raw if isinstance(raw, datetime.date) else raw.date()

        raw = str(raw).strip()

        # 1) 8자리 연속 숫자 (YYYYMMDD)  
        if re.fullmatch(r'\d{8}', raw):  
            try:  
                return datetime.datetime.strptime(raw, "%Y%m%d").date()  
            except ValueError:  
                pass

        # 2) 10자리 형식 (YYYY‑MM‑DD or YYYY/MM/DD)  
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):  
            try:  
                return datetime.datetime.strptime(raw, fmt).date()  
            except ValueError:  
                continue

        # 3) 6자리 YYMMDD (00‑69 → 2000‑2069, 70‑99 → 1970‑1999)  
        if re.fullmatch(r'\d{6}', raw):  
            yy = int(raw[:2])  
            year = (2000 + yy) if yy < 70 else (1900 + yy)  
            try:  
                return datetime.date(year,  
                                     int(raw[2:4]),  
                                     int(raw[4:6]))  
            except ValueError:  
                pass

        # 파싱 불가  
        return None

    # -----------------------------------------------------------------  
    # 1️⃣ 엑셀 시트 이름 조회  
    # -----------------------------------------------------------------  
    @staticmethod  
    def get_sheet_names(file):  
        try:  
            xl = pd.ExcelFile(file)  
            return xl.sheet_names  
        except Exception:  
            return None

    # -----------------------------------------------------------------  
    # 2️⃣ 업로드 검증 (기존 19개 컬럼 검증 로직 – 크게 변동 없음)  
    # -----------------------------------------------------------------  
    @staticmethod  
    def validate_excel_upload(file, sheet_name=0):  
        """  
        엑셀 파일을 읽고, 기본 검증(설비·물질 매핑, 값 범위, 중복) 후  
        `results`, `summary`, `missing_entries` 를 반환합니다.  
        """  
        try:  
            df = pd.read_excel(file, sheet_name=sheet_name)  
            df.columns = [c.strip() for c in df.columns]  
            # 채취일시 컬럼을 pandas 가 자동 파싱하도록 시도  
            df['채취일시'] = pd.to_datetime(df['채취일시'], errors='coerce')  
        except Exception as e:  
            return {"error": f"엑셀 읽기 실패: {str(e)}"}, {}, []

        results, summary = [], {"total": 0, "success": 0,  
                                 "warning": 0, "duplicate": 0, "error": 0}  
        uploaded_pairs = set()

        for index, row in df.iterrows():  
            # ---------- 날짜 존재 여부 ----------  
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

            raw_date = row['채취일시'].date()          # pandas 가 만든 datetime.date  
            raw_value = ExcelValidationService._clean_float(row.get('농도'))  
            uploaded_pairs.add((facility.id, substance.id))

            # ---------- 범위·중복 체크 ----------  
            is_valid = ExcelValidationService.check_value_range_precise(substance, raw_value)  
            existing = DailyLog.objects.filter(  
                facility=facility, date=raw_date, substance=substance  
            ).first()  
            status = 'duplicate' if existing else ('warning' if not is_valid else 'success')  
            summary[status] += 1

            results.append({  
                'row': index + 2,  
                'facility_id': facility.id,  
                'substance_id': substance.id,  
                'facility_name': facility.sec,  
                'manage_no': facility.facility_no,  
                'date': raw_date.strftime('%Y-%m-%d'),  
                'substance_name': substance.name,  
                'value': raw_value,  
                'status': status,  
                'msg': '정상' if status == 'success' else status,  
                'extra_data': {  
                    'collection_month': str(row.get('채취월', '3월')).strip(),  
                    'sampling_time_text': str(row.get('채취시간', '')),  
                    'inspection_agency': str(row.get('검사기관', '')),  
                    'air_flow': ExcelValidationService._clean_float(row.get('풍량')),  
                    'weather': str(row.get('날씨', '')),  
                    'temp': ExcelValidationService._clean_float(row.get('기온')),  
                    'emission_rate': ExcelValidationService._clean_float(row.get('배출량(kg/day)')),  
                }  
            })  
        # 누락(미측정) 항목 반환  
        missing = ExcelValidationService.check_missing_entries(uploaded_pairs)  
        return results, summary, missing

    # -----------------------------------------------------------------  
    # 3️⃣ 값 범위 검증 (기존 로직 그대로)  
    # -----------------------------------------------------------------  
    @staticmethod  
    def check_value_range_precise(substance, value):  
        try:  
            val = float(value)  
            op, v1, v2 = substance.operator, substance.val1, substance.val2  
            if op == '<=': return val <= v1  
            if op == '>=': return val >= v1  
            if op == '<':  return val < v1  
            if op == '>':  return val > v1  
            if op == '[]' and v2 is not None: return v1 <= val <= v2  
            return False  
        except Exception:  
            return False

    # -----------------------------------------------------------------  
    # 4️⃣ 누락된 측정 항목 추출 (기존 로직)  
    # -----------------------------------------------------------------  
    @staticmethod  
    def check_missing_entries(uploaded_pairs):  
        configs = MeasurementConfig.objects.select_related('facility', 'substance').all()  
        return [  
            {'facility': c.facility.sec, 'substance': c.substance.name}  
            for c in configs  
            if (c.facility_id, c.substance_id) not in uploaded_pairs  
        ]

    # -----------------------------------------------------------------  
    # 5️⃣ 최종 데이터 저장 (날짜 파싱 강화 & 오류 누적)  
    # -----------------------------------------------------------------  
    @staticmethod
    def calculate_log_status(facility, substance, value, air_flow):
        """농도 및 풍량 상태 자동 계산 로직"""
        # 1. 농도 초과 판별
        is_legal = (substance.val2 is not None and value > substance.val2)
        is_internal = (substance.val1 is not None and value > substance.val1)

        # 2. 풍량 초과 판별 (NCMM, ACMM 중 큰 값 기준)
        ncmm = facility.capacity_ncmm or 0
        acmm = facility.capacity_acmm or 0
        max_capacity = max(ncmm, acmm)
        
        airflow_status = 'normal'
        if max_capacity > 0:
            if air_flow > max_capacity:
                airflow_status = 'legal'    # 용량 초과 (법적)
            elif air_flow > (max_capacity * 0.9):
                airflow_status = 'internal' # 90% 초과 (사내)

        return is_legal, is_internal, airflow_status    
    @staticmethod
    @transaction.atomic
    def save_final_data(data_list):
        """
        데이터 저장 시 다음 항목을 자동 처리합니다:
        1. 물질 미등록 시: substance=None, substance_status='참고', raw_substance_name 저장
        2. 농도 상태 판별 (정상, 사내초과, 법적초과)
        3. 풍량 상태 판별 (정상, 사내초과, 법적초과) - 90%/100% 로직
        4. 배출량 자동 계산 (수식 존재 시 계산, 미등록 물질은 엑셀값 유지)
        5. 제출용 데이터(is_report_data) 최신화
        """
        saved_count = 0
        errors = []
        # (시설ID, 물질ID 혹은 0, 년, 월)
        affected_groups = set() 

        for idx, item in enumerate(data_list, start=1):
            try:
                # ---------- 1) 객체 및 기본값 확보 ----------
                facility = Facility.objects.get(id=item['facility_id'])
                
                # 물질 식별 (없을 경우 None 반환)
                substance_id = item.get('substance_id')
                substance = Substance.objects.filter(id=substance_id).first() if substance_id else None
                
                date_obj = ExcelValidationService._parse_date(item.get('date'))
                if not date_obj:
                    errors.append({'row': idx, 'msg': f"날짜 형식 오류: {item.get('date')}"})
                    continue

                value = float(item.get('value', 0))
                extra = item.get('extra_data', {})
                air_flow = float(extra.get('air_flow', 0))
                month_str = f"{date_obj.month}월"

                # ---------- 2) 농도 상태 판별 (물질 미등록 시 '참고') ----------
                sub_status = '정상'
                if substance:
                    if substance.val2 is not None and value > substance.val2:
                        sub_status = '법적초과'
                    elif substance.val1 is not None and value > substance.val1:
                        sub_status = '사내초과'
                else:
                    sub_status = '참고' # 물질 마스터에 없을 때

                # ---------- 3) 풍량 상태 판별 (90% 사내, 100% 법적) ----------
                ncmm = facility.capacity_ncmm or 0
                acmm = facility.capacity_acmm or 0
                max_capa = max(ncmm, acmm)
                
                af_status = '정상'
                if max_capa > 0:
                    if air_flow > max_capa:
                        af_status = '법적초과'
                    elif air_flow > (max_capa * 0.9):
                        af_status = '사내초과'

                # ---------- 4) 배출량 자동 계산 ----------
                final_emission_rate = 0
                raw_formula = substance.formula.strip() if (substance and substance.formula) else ""
                
                if substance and raw_formula and raw_formula != "-":
                    try:
                        safe_formula = raw_formula.replace('^', '**')
                        formula_factor = eval(safe_formula, {"__builtins__": None}, {})
                        final_emission_rate = round(formula_factor * value * air_flow, 4)
                    except:
                        final_emission_rate = float(extra.get('emission_rate', 0))
                else:
                    # 물질이 없거나 수식이 없으면 엑셀에 적힌 값 그대로 사용
                    final_emission_rate = float(extra.get('emission_rate', 0))

                # ---------- 5) DB 저장 ----------
                # 물질이 없을 경우 unique_together ('facility', 'substance', 'date') 충돌 방지를 위해 
                # 필터 조건을 주의 깊게 설정해야 합니다. (substance=None 대응)
                
                update_fields = {
                    'collection_month': month_str,
                    'raw_substance_name': item.get('substance_name'),
                    'sampling_time_text': extra.get('sampling_time_text', ''),
                    'value': value,
                    'air_flow': air_flow,
                    'substance_status': sub_status,
                    'airflow_status': af_status,
                    'emission_rate': final_emission_rate,
                    'weather': extra.get('weather', ''),
                    'temp': ExcelValidationService._clean_float(extra.get('temp', 0)),
                    'humidity': ExcelValidationService._clean_float(extra.get('humidity', 0)),
                    'pressure': ExcelValidationService._clean_float(extra.get('pressure', 0)),
                    'wind_dir': extra.get('wind_dir', ''),
                    'wind_speed': ExcelValidationService._clean_float(extra.get('wind_speed', 0)),
                    'gas_speed': ExcelValidationService._clean_float(extra.get('gas_speed', 0)),
                    'gas_temp': ExcelValidationService._clean_float(extra.get('gas_temp', 0)),
                    'moisture': ExcelValidationService._clean_float(extra.get('moisture', 0)),
                    'agency': extra.get('agency', '-'),
                }

                obj, created = DailyLog.objects.update_or_create(
                    facility=facility,
                    substance=substance, # None 일 수 있음
                    date=date_obj,
                    defaults=update_fields
                )
                
                # 갱신 그룹에 추가 (substance가 None이면 0으로 처리하여 관리)
                s_key = substance.id if substance else 0
                affected_groups.add((facility.id, s_key, date_obj.year, month_str))
                saved_count += 1

            except Exception as e:
                errors.append({'row': idx, 'msg': f"저장 중 오류 발생: {str(e)}"})

        # ---------- 6) 제출용 데이터(is_report_data) 플래그 갱신 ----------
        for f_id, s_id, year, m_str in affected_groups:
            # 필터 조건 설정 (ID 0은 None을 의미)
            filter_kwargs = {
                'facility_id': f_id,
                'date__year': year,
                'collection_month': m_str
            }
            if s_id == 0:
                filter_kwargs['substance__isnull'] = True
            else:
                filter_kwargs['substance_id'] = s_id

            # 해당 그룹 초기화 후 최신 데이터 마킹
            DailyLog.objects.filter(**filter_kwargs).update(is_report_data=False)
            
            latest = DailyLog.objects.filter(**filter_kwargs).order_by('-date', '-id').first()
            if latest:
                latest.is_report_data = True
                latest.save()

        return saved_count, errors

    # -----------------------------------------------------------------  
    # 6️⃣ 통합 매트릭스(설비·물질) 임포트  
    # -----------------------------------------------------------------  
    @staticmethod  
    @transaction.atomic  
    def import_configs(file):  
        """  
        통합 매트릭스 엑셀 업로드.  
        - 설비가 존재하지 않으면 자동 생성(기본값 채움)  
        - 각 물질에 대한 사내·법적 기준을 업데이트하고  
          `MeasurementConfig` (필수 측정 매핑)를 동기화합니다.  
        """  
        df = pd.read_excel(file)  
        df.columns = [c.strip() for c in df.columns]  
        substances = Substance.objects.all()  
        count = 0

        for _, row in df.iterrows():  
            f_sec = str(row.get('세부라인 방지시설', '')).strip()  
            if not f_sec or f_sec.lower() == 'nan':  
                continue

            # 설비가 없으면 자동 생성(기본값은 추후 UI에서 수정)  
            facility, _ = Facility.objects.get_or_create(  
                sec=f_sec,  
                defaults={  
                    'facility_no': f'NEW-{f_sec[:5]}',  
                    'workplace': '본사',  
                    'status': '운영',  
                }  
            )

            for sub in substances:  
                val_internal = row.get(f'{sub.name}_사내')  
                val_legal = row.get(f'{sub.name}_법적')

                # 사내 기준이 존재하면 매핑·기준 동기화  
                if not pd.isna(val_internal) and str(val_internal).strip() != '':  
                    sub.val1 = float(val_internal)  
                    if not pd.isna(val_legal):  
                        sub.val2 = float(val_legal)  
                    sub.save()

                    MeasurementConfig.objects.get_or_create(  
                        facility=facility,  
                        substance=sub  
                    )  
                    count += 1  
                else:  
                    # 빈칸이면 매핑 삭제  
                    MeasurementConfig.objects.filter(  
                        facility=facility,  
                        substance=sub  
                    ).delete()  
        return count

    # -----------------------------------------------------------------  
    # 7️⃣ 설비 마스터 일괄 임포트 (13개 컬럼)  
    # -----------------------------------------------------------------  
    @staticmethod  
    @transaction.atomic  
    def import_facilities(file):  
        df = pd.read_excel(file)  
        df.columns = [c.strip() for c in df.columns]

        for _, row in df.iterrows():  
            sec_name = str(row.get('세부라인 방지시설(SEC)', '')).strip()  
            if not sec_name or sec_name.lower() == 'nan':  
                continue

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

    # -----------------------------------------------------------------  
    # 8️⃣ 물질 마스터 일괄 임포트 (계산식 지원)  
    # -----------------------------------------------------------------  
    @staticmethod  
    @transaction.atomic  
    def import_substances(file):  
        """  
        물질 마스터 엑셀 업로드.  
        - 컬럼이 `물질명, 사내기준, 법적기준, 단위` 로 구성돼 있다고 가정합니다.  
        - `계산식`(formula) 컬럼이 있으면 그 값을 그대로 저장하고,  
          없으면 기본값 `'-'` 을 사용합니다.  
        """  
        df = pd.read_excel(file)  
        # 컬럼명에 공백이 있을 수 있으니 모두 strip  
        df.columns = [c.strip() for c in df.columns]

        for _, row in df.iterrows():  
            name = str(row.get('물질명') or '').strip()  
            if not name:  
                continue

            # 기존 사내·법적 기준은 그대로 저장 (필요 시 사용)  
            val1 = float(row.get('사내기준', 0))  
            val2_raw = row.get('법적기준')  
            val2 = float(val2_raw) if pd.notna(val2_raw) else None

            # 새로운 계산식 컬럼 지원  
            formula = str(row.get('계산식') or row.get('formula') or '-').strip()

            Substance.objects.update_or_create(  
                name=name,  
                defaults={  
                    'val1': val1,  
                    'val2': val2,  
                    'unit': str(row.get('단위') or 'ppm').strip(),  
                    'formula': formula,  
                }  
            )  
        return len(df)  


    def refresh_report_data_flag(facility, substance, year, month):
        """해당 월의 마지막 측정건을 제출용(is_report_data)으로 마킹"""
        month_str = f"{month}월"
        
        # 1. 해당 월/시설/물질에 대한 모든 데이터의 제출 플래그 초기화
        DailyLog.objects.filter(
            facility=facility, 
            substance=substance, 
            date__year=year, 
            collection_month=month_str
        ).update(is_report_data=False) # <--- .update() 앞에 괄호 닫기 확인!

        # 2. 날짜가 가장 늦은(최신) 데이터 하나만 찾기
        # 날짜가 같을 경우를 대비해 id 역순(-id)도 추가하는 것이 안전합니다.
        latest_log = DailyLog.objects.filter(
            facility=facility, 
            substance=substance, 
            date__year=year, 
            collection_month=month_str
        ).order_by('-date', '-id').first()

        if latest_log:
            latest_log.is_report_data = True
            latest_log.save()