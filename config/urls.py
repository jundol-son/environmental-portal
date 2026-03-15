from django.contrib import admin
from django.urls import path, include
from dashboard.views import signup

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/signup/', signup, name='signup'),
    path('accounts/', include('django.contrib.auth.urls')), # 로그인/로그아웃 경로 자동 생성
    path('', include('dashboard.urls')),
    path('chemicals/', include('chemicals.urls')), # 화관법 앱 등록
    path('integrated/', include('integrated.urls')), # 환통법(추후)
    path('wastes/', include('wastes.urls')),    
]