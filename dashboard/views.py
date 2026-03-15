from django.shortcuts import render, redirect  # HTML을 띄워주기 위해 필수!
from django.contrib.auth.decorators import login_required  # 로그인 체크용
from .models import CustomerAsset, CalendarEvent  # DB 데이터를 가져오기 위해 필수!
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator # 추가
import pandas as pd
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from datetime import datetime, timedelta
from io import BytesIO
from django.views.decorators.csrf import csrf_exempt
import json, calendar
from pytimekr import pytimekr

@login_required
def home(request):
    # 로그인한 사람만 홈 화면을 볼 수 있음
    return render(request, 'home.html')

@login_required
def asset_list(request):
    # 모든 관리자와 자산군 리스트 (콤보박스용)
    managers = User.objects.all()
    # 중복 제거된 자산군 리스트 추출
    asset_types = CustomerAsset.objects.values_list('asset_type', flat=True).distinct()

    # 필터 값 가져오기
    selected_manager = request.GET.get('manager')
    selected_asset_type = request.GET.get('asset_type')
    search_name = request.GET.get('search_name')  
    start_date = request.GET.get('start_date') # 시작일
    end_date = request.GET.get('end_date')     # 종료일      
    per_page = request.GET.get('per_page', 20) # 기본값 20줄
    # 로그인한 사람만 자산 리스트를 볼 수 있음
    assets = CustomerAsset.objects.all().order_by('-created_at') # 최신순 정렬 권장
    # 필터 적용
    if selected_manager:
        assets = assets.filter(manager_id=selected_manager)
    if selected_asset_type:
        assets = assets.filter(asset_type=selected_asset_type)
    if search_name:
        assets = assets.filter(name__icontains=search_name)
    # 날짜 범위 필터링 (해당 날짜의 00:00:00부터 23:59:59까지 포함)
    if start_date:
        assets = assets.filter(updated_at__date__gte=start_date)
    if end_date:
        assets = assets.filter(updated_at__date__lte=end_date)
    # --- 페이징 처리 시작 ---
    paginator = Paginator(assets, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    # --- 페이징 처리 끝 ---

    context = {
        'assets': page_obj,
        'managers': managers,
        'asset_types': asset_types,
        'per_page': int(per_page),
    }    
    return render(request, 'dashboard/asset_list.html', context)

def signup(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "회원가입이 완료되었습니다! 로그인을 해주세요.")
            return redirect('login')
        else:
            # 폼 검증에 실패하면(중복 아이디 등) 에러 메시지를 포함해 다시 보여줌
            messages.error(request, "가입 정보에 문제가 있습니다. 아래 내용을 확인해주세요.")
    else:
        form = UserCreationForm()
    
    return render(request, 'registration/signup.html', {'form': form})

@login_required
def export_assets_excel(request):
    # 1. URL에서 선택된 ID 리스트 가져오기
    selected_ids = request.GET.getlist('ids')
    
    # 2. 데이터 필터링 로직
    if selected_ids:
        # 체크박스로 선택된 ID가 있는 경우
        assets = CustomerAsset.objects.filter(id__in=selected_ids)
    else:
        # 선택된 게 없으면 검색 필터 적용
        assets = CustomerAsset.objects.all()
        manager = request.GET.get('manager')
        asset_type = request.GET.get('asset_type')
        search_name = request.GET.get('search_name')

        if manager: 
            assets = assets.filter(manager_id=manager)
        if asset_type: 
            assets = assets.filter(asset_type=asset_type)
        if search_name: 
            assets = assets.filter(name__icontains=search_name)

    # 3. 엑셀로 변환할 데이터 리스트 생성
    data = []
    for a in assets:
        data.append({
            '담당자': a.manager.username if a.manager else '미지정',
            '고객명': a.name,
            '자산군': a.asset_type,
            '잔고': float(a.balance), # Decimal 타입을 float로 변환하여 엑셀 오류 방지
            '이메일': a.email,
            '최종수정일': a.updated_at.strftime('%Y-%m-%d %H:%M') if a.updated_at else ''
        })

    # 데이터가 없을 경우를 대비한 빈 데이터프레임 처리
    df = pd.DataFrame(data) if data else pd.DataFrame(columns=['담당자', '고객명', '자산군', '잔고', '이메일', '최종수정일'])

    # 4. HTTP 응답 설정 (이 부분이 반드시 함수 가장 바깥쪽에 있어야 합니다)
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename=asset_report_{datetime.now().strftime("%Y%m%d")}.xlsx'
    
    try:
        with pd.ExcelWriter(response, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='자산현황')
    except Exception as e:
        # 에러 발생 시 로그 출력 등을 위해 처리
        return HttpResponse(f"엑셀 생성 중 오류가 발생했습니다: {e}", status=500)
        
    return response # 👈 이 리턴문이 누락되지 않았는지 꼭 확인하세요!

@staff_member_required
def admin_management(request):
    users = User.objects.all().order_by('-date_joined')
    preview_data = None  # 화면에 보여줄 검증 리스트 초기화

    if request.method == 'POST':
        # 1. 개별 자산 등록 로직
        if 'add_single_asset' in request.POST:
            CustomerAsset.objects.create(
                manager=request.user,
                name=request.POST.get('name'),
                asset_type=request.POST.get('asset_type'),
                balance=request.POST.get('balance'),
                email=request.POST.get('email')
            )
            messages.success(request, "새로운 고객 자산이 개별 등록되었습니다.")
            return redirect('admin_management')

        # 2. 엑셀 업로드 및 검증 단계 (파일을 읽어 세션에 임시 저장)
        elif request.FILES.get('excel_file'):
            try:
                excel_file = request.FILES['excel_file']
                df = pd.read_excel(excel_file)
                
                # 데이터프레임을 딕셔너리 리스트로 변환 (템플릿 출력용)
                preview_data = df.to_dict(orient='records')
                
                # 최종 확정 버튼을 위해 세션에 임시 저장 (JSON 직렬화 가능 형태)
                request.session['temp_upload_data'] = preview_data
                messages.info(request, "엑셀 데이터를 읽어왔습니다. 하단 리스트를 확인 후 '최종 확정'을 눌러주세요.")
            except Exception as e:
                messages.error(request, f"엑셀 파일을 읽는 중 오류가 발생했습니다: {e}")

        # 3. 엑셀 최종 확정 로직 (세션의 데이터를 DB에 실제 저장)
        elif 'confirm_upload' in request.POST:
            temp_data = request.session.get('temp_upload_data')
            if temp_data:
                created_count = 0
                try:
                    for item in temp_data:
                        CustomerAsset.objects.create(
                            manager=request.user,
                            name=item.get('고객명'),
                            asset_type=item.get('자산군'),
                            balance=item.get('잔고'),
                            email=item.get('이메일')
                        )
                        created_count += 1
                    
                    # 저장 성공 후 세션 비우기
                    del request.session['temp_upload_data']
                    messages.success(request, f"성공적으로 {created_count}건의 데이터가 최종 등록되었습니다.")
                except Exception as e:
                    messages.error(request, f"데이터 저장 중 오류가 발생했습니다: {e}")
                
                return redirect('admin_management')
            else:
                messages.warning(request, "확정할 데이터가 없습니다. 다시 업로드해 주세요.")

    return render(request, 'dashboard/admin_management.html', {
        'users': users,
        'preview_data': preview_data # 템플릿으로 검증 리스트 전달
    })

# 샘플 엑셀 다운로드 뷰
@staff_member_required
def download_sample_excel(request):
    data = {
        '고객명': ['유재석', '강호동'],
        '자산군': ['가상자산', '예적금'],
        '잔고': [10000000, 50000000],
        '이메일': ['yu@example.com', 'kang@example.com']
    }
    df = pd.DataFrame(data)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    
    output.seek(0)
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=asset_upload_sample.xlsx'
    return response

# 사용자 권한 수정 (AJAX)
@require_POST
@staff_member_required
def update_user_status(request):
    try:
        user_id = request.POST.get('user_id')
        is_staff = request.POST.get('is_staff') == 'true'
        is_active = request.POST.get('is_active') == 'true'
        
        target_user = User.objects.get(id=user_id)
        target_user.is_staff = is_staff
        target_user.is_active = is_active
        target_user.save()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

def get_family_day(year, month):
    """특정 연/월의 21일이 포함된 주의 금요일 날짜를 반환"""
    # 해당 월의 21일 날짜 객체 생성
    target_date = datetime(year, month, 21)
    
    # 21일의 요일 (0:월, 1:화, ..., 4:금, 5:토, 6:일)
    weekday = target_date.weekday()
    
    # 21일이 포함된 주의 금요일 계산
    # 금요일(4)에서 현재 요일을 뺀 만큼 더해줌
    days_to_friday = 4 - weekday
    family_day = target_date + timedelta(days=days_to_friday)
    
    return family_day

@login_required  # 로그인한 사용자만 접근 가능하도록 설정
@csrf_exempt
def save_event(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        event_id = data.get('id')
        
        # 날짜 포맷 정리 (T 포함 여부 체크)
        start_time = data.get('start')
        end_time = data.get('end')

        if event_id:  # 수정 시
            event = CalendarEvent.objects.get(id=event_id)
            event.title = data.get('title')
            event.start_time = start_time
            event.end_time = end_time
            event.description = data.get('description')
            event.save()
        else:  # 신규 등록 시 ★이 부분이 핵심입니다★
            CalendarEvent.objects.create(
                title=data.get('title'),
                start_time=start_time,
                end_time=end_time,
                description=data.get('description'),
                user=request.user  # 현재 로그인한 PB님 계정을 직접 할당
            )
        return JsonResponse({'status': 'success'})

# 일정 삭제
@csrf_exempt
def delete_event(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        event = CalendarEvent.objects.get(id=data.get('id'))
        event.delete()
        return JsonResponse({'status': 'success'})

# 기존에 여러 개 있던 event_list 함수들을 모두 지우고 이 하나만 남기세요.
def event_list(request):
    # 1. DB에 저장된 일반 일정 가져오기
    events = CalendarEvent.objects.all().select_related('user')
    event_data = []
    
    for e in events:
        u_name = e.user.username if e.user else "알수없음"
        event_data.append({
            'id': e.id,
            'title': f"[{u_name}] {e.title}",
            'start': e.start_time.isoformat(),
            'end': e.end_time.isoformat(),
            'extendedProps': {
                'original_title': e.title,
                'description': e.description,
                'user_name': u_name,
                'is_system': False  # 일반 일정
            }
        })
# 2. pytimekr 공휴일 이름 매칭 및 추가
    now = datetime.now()
    # pytimekr은 '설날', '추석' 등 명칭을 포함한 딕셔너리 형태의 접근을 지원합니다.
    # 아래는 주요 공휴일 명칭을 자동으로 가져오는 최적화된 방식입니다.
    kr_holidays = pytimekr.holidays(year=now.year)
    
    for dt in kr_holidays:
        # pytimekr의 get_holiday_name 같은 메서드 대신 날짜별 명칭을 매핑합니다.
        h_name = pytimekr.red_days(dt) # 해당 날짜의 공휴일 명칭 반환
        
        event_data.append({
            'title': f"🚩 {h_name}" if h_name else "🚩 공휴일", 
            'start': dt.strftime("%Y-%m-%d"),
            'allDay': True, # 공휴일은 항상 종일
            'backgroundColor': '#ff4757',
            'borderColor': '#ff4757',
            'extendedProps': {
                'is_system': True, 
                'description': '국가 법정 공휴일',
                'user_name': '시스템'
            }
        })
    for i in range(-12, 12):
        target_month = now.month + i
        target_year = now.year
        
        while target_month > 12:
            target_month -= 12
            target_year += 1
        while target_month < 1:
            target_month += 12
            target_year -= 1
            
        f_day = get_family_day(target_year, target_month)
        
        event_data.append({
            'title': "✨ 패밀리데이",
            'start': f_day.strftime("%Y-%m-%d"),
            'allDay' : True,
            'backgroundColor': '#ff4757', # 빨간색 바
            'borderColor': '#ff4757',
            'extendedProps': {
                'description': "매달 21일이 포함된 주의 즐거운 패밀리데이입니다!",
                'user_name': "시스템",
                'is_system': True  # 시스템 일정 (수정/삭제 방지용)
            }
        })
        
    return JsonResponse(event_data, safe=False)

@login_required
def generate_asset_report(request):
    selected_ids = request.GET.getlist('ids')
    if not selected_ids:
        return HttpResponse("<script>alert('보고서를 작성할 고객을 선택해주세요.'); history.back();</script>")

    # 선택된 자산 데이터 가져오기
    assets = CustomerAsset.objects.filter(id__in=selected_ids).select_related('manager')
    
    # 고객명으로 그룹화 (한 고객이 여러 자산군을 가질 수 있음)
    customer_data = {}
    for a in assets:
        if a.name not in customer_data:
            customer_data[a.name] = {'manager': a.manager.username if a.manager else '미지정', 'items': [], 'total': 0}
        customer_data[a.name]['items'].append(a)
        customer_data[a.name]['total'] += float(a.balance)

    # 보고서 내용 생성
    reports = []
    today = datetime.now().strftime('%Y-%m-%d')

    for name, data in customer_data.items():
        report_text = f"### [고객 자산 관리 보고서] - {name} 고객님\n"
        report_text += f"- 작성일: {today} / 담당 PB: {data['manager']}\n\n"
        report_text += "#### 1. 자산 보유 현황\n"
        
        for item in data['items']:
            weight = (float(item.balance) / data['total']) * 100
            report_text += f"- {item.asset_type}: {int(item.balance):,}원 ({weight:.1f}%)\n"
        
        report_text += f"**- 총 자산 규모: {int(data['total']):,}원**\n\n"
        
        # 간단한 분석 로직 (예시)
        report_text += "#### 2. PB 종합 의견\n"
        if any("가상자산" in item.asset_type for item in data['items']):
            report_text += "- 현재 고위험 자산(가상자산 등)이 포트폴리오에 포함되어 있습니다. 시장 변동성에 유의하십시오.\n"
        else:
            report_text += "- 안정적인 자산 위주로 구성되어 있습니다. 수익성 제고를 위해 일부 채권형 ETF 검토를 권고합니다.\n"
        
        report_text += "\n" + "-"*50 + "\n"
        reports.append(report_text)

    return render(request, 'dashboard/asset_report.html', {'reports': reports})