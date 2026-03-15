# wastes/services.py
import pandas as pd
from datetime import datetime
from io import BytesIO
from django.http import HttpResponse
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from .models import WasteLog

class WasteService:
    @staticmethod
    def export_wastes_to_excel(wastes):
        """폐기물 데이터를 엑셀 파일 객체로 변환 (비즈니스 로직)"""
        data = []
        for w in wastes:
            data.append({
                '담당자': w.manager.username if w.manager else '미지정',
                '폐기물종류': w.waste_type,
                '배출량': w.quantity,
                '단위': w.unit,
                '수거업체': w.company,
                '배출일시': w.created_at.strftime('%Y-%m-%d %H:%M')
            })

        df = pd.DataFrame(data) if data else pd.DataFrame(columns=['담당자', '폐기물종류', '배출량', '단위', '수거업체', '배출일시'])
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='폐기물배출현황')
        
        return output.getvalue()

    @staticmethod
    def generate_analysis_report(wastes):
        """데이터를 분석하여 보고서 텍스트 생성 (비즈니스 로직)"""
        type_summary = {}
        total_qty = 0
        for w in wastes:
            if w.waste_type not in type_summary:
                type_summary[w.waste_type] = 0
            type_summary[w.waste_type] += w.quantity
            total_qty += w.quantity

        today = datetime.now().strftime('%Y-%m-%d')
        report_text = f"### [폐기물 분석 리포트]\n- 작성일: {today}\n\n"
        
        for w_type, qty in type_summary.items():
            percentage = (qty / total_qty) * 100 if total_qty > 0 else 0
            report_text += f"- {w_type}: {qty:.2f} ({percentage:.1f}%)\n"
        
        report_text += f"\n**총 배출량: {total_qty:.2f}**\n"
        return [report_text]
    
    @staticmethod
    def get_dashboard_data():
        """차트용 통계 데이터 가공"""
        # 1. 종류별 배출 비중 (도넛 차트용)
        type_stats = WasteLog.objects.values('waste_type').annotate(
            total=Sum('quantity')
        ).order_by('-total')

        # 2. 월별 배출 추이 (선 그래프용)
        monthly_stats = WasteLog.objects.annotate(
            month=TruncMonth('created_at')
        ).values('month').annotate(
            total=Sum('quantity')
        ).order_by('month')

        return {
            'labels': [item['waste_type'] for item in type_stats],
            'values': [float(item['total']) for item in type_stats],
            'months': [item['month'].strftime('%Y-%m') for item in monthly_stats],
            'monthly_values': [float(item['total']) for item in monthly_stats],
        }    