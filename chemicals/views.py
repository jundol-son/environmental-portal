from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import NicsNotice
from .utils import crawl_nics_notices
from django.contrib import messages

@login_required
def chemical_check(request):
    # 연동할 외부 URL (예: 화학물질안전원 또는 자체 법령 시스템)
    external_url = "https://www.safetydata.go.kr/" # 실제 필요한 URL로 교체하세요
    return render(request, 'chemicals/external_viewer.html', {'external_url': external_url})

def nics_notice_list(request):
    # DB에 저장된 고시 목록을 가져옴 (최신순)
    notices = NicsNotice.objects.all()
    return render(request, 'chemicals/nics_list.html', {'notices': notices})

def nics_notice_list(request):
    # 'update' 파라미터가 들어오면 크롤링 실행
    if 'update' in request.GET:
        count = crawl_nics_notices()
        messages.success(request, f"{count}건의 새로운 고시가 업데이트되었습니다.")
        return redirect('nics_notice_list')

    notices = NicsNotice.objects.all().order_by('-reg_date')
    return render(request, 'chemicals/nics_list.html', {'notices': notices})