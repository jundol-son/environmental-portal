from django.db import models

class Facility(models.Model):
    """환통법 설비 기준 정보 (13개 상세 컬럼)"""
    facility_no = models.CharField(max_length=50, verbose_name="시설번호", null=True, blank=True)
    prevent_no = models.CharField(max_length=50, verbose_name="방지시설번호", null=True, blank=True)
    company_no = models.CharField(max_length=50, verbose_name="업체번호", null=True, blank=True)
    sec = models.CharField(max_length=100, verbose_name="세부라인 방지시설", unique=True) # 엑셀 매칭 키
    workplace = models.CharField(max_length=100, verbose_name="사업장", null=True, blank=True)
    line = models.CharField(max_length=100, verbose_name="라인", null=True, blank=True)
    exhaust = models.CharField(max_length=100, verbose_name="배기", null=True, blank=True)
    line_exhaust = models.CharField(max_length=200, verbose_name="라인 배기", null=True, blank=True)
    common_name = models.CharField(max_length=200, verbose_name="라인 세부 방지(공통)", null=True, blank=True)
    capacity = models.CharField(max_length=50, verbose_name="용량", null=True, blank=True)
    tms_yn = models.CharField(max_length=10, verbose_name="TMS", default="X")
    status = models.CharField(max_length=20, verbose_name="운영/폐쇄", default="운영")
    diameter = models.CharField(max_length=50, verbose_name="직경", null=True, blank=True)

    def __str__(self):
        return self.sec

class Substance(models.Model):
    name = models.CharField(max_length=50, verbose_name="물질명", unique=True)
    formula = models.CharField(max_length=250, verbose_name="계산식", default="-")
    unit = models.CharField(max_length=20, verbose_name="단위", default="mg/Sm3")
    
    # [추가] 법적 구분
    LEGAL_CHOICES = [('법적', '법적'), ('참고', '참고')]
    legal_type = models.CharField(max_length=10, choices=LEGAL_CHOICES, default='법적', verbose_name="법적구분")
    
    # [추가] 측정 주기
    CYCLE_CHOICES = [('매월', '매월'), ('분기', '분기'), ('반기', '반기')]
    cycle = models.CharField(max_length=10, choices=CYCLE_CHOICES, default='매월', verbose_name="측정주기")

    # 기존 val1, val2는 통합기준관리용 기본값으로 유지하거나 비워둠
    val1 = models.FloatField(null=True, blank=True, default=0)
    val2 = models.FloatField(null=True, blank=True, default=0)

    def __str__(self):
        return self.name

class MeasurementConfig(models.Model):
    """설비별 필수 측정 항목 설정 (엑셀 O표시 정보 매핑)"""
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE)
    substance = models.ForeignKey(Substance, on_delete=models.CASCADE)
    is_required = models.BooleanField(default=True, verbose_name="필수여부")

    class Meta:
        unique_together = ('facility', 'substance')
        verbose_name = "측정 설정"
        verbose_name_plural = "측정 설정 리스트"

    def __str__(self):
        return f"{self.facility.sec} - {self.substance.name} (필수)"

class DailyLog(models.Model):
    """측정 데이터 로그 (상세 컬럼 포함)"""
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE)
    substance = models.ForeignKey(Substance, on_delete=models.CASCADE)
    date = models.DateField(verbose_name="채취일자")
    
    # 엑셀 상세 컬럼 데이터
    collection_month = models.CharField(max_length=20, null=True, blank=True)
    sampling_time_text = models.CharField(max_length=50, null=True, blank=True)
    sampling_datetime = models.DateTimeField(null=True, blank=True)
    agency = models.CharField(max_length=100, null=True, blank=True)
    
    value = models.FloatField(verbose_name="농도")
    air_flow = models.FloatField(verbose_name="풍량", null=True, blank=True)
    weather = models.CharField(max_length=50, null=True, blank=True)
    temp = models.FloatField(null=True, blank=True)
    humidity = models.FloatField(null=True, blank=True)
    pressure = models.FloatField(null=True, blank=True)
    wind_dir = models.CharField(max_length=50, null=True, blank=True)
    wind_speed = models.FloatField(null=True, blank=True)
    o2_conc = models.FloatField(null=True, blank=True)
    gas_speed = models.FloatField(null=True, blank=True)
    gas_temp = models.FloatField(null=True, blank=True)
    moisture = models.FloatField(null=True, blank=True)
    emission_rate = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ('facility', 'substance', 'date')
