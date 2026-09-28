from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator

class WasteLog(models.Model):
    manager = models.ForeignKey(User, on_delete=models.CASCADE)
    waste_type = models.CharField(max_length=100) # 폐기물 종류 (예: 폐유, 폐산)
    quantity = models.FloatField()               # 배출량
    unit = models.CharField(max_length=10, default='kg')
    company = models.CharField(max_length=100)   # 수거 업체
    created_at = models.DateTimeField(auto_now_add=True)


class AllocationRule(models.Model):
    rule_code = models.CharField(max_length=30, unique=True)
    rule_name = models.CharField(max_length=100)
    valid_from = models.DateField()
    valid_to = models.DateField(blank=True, null=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.rule_code} - {self.rule_name}'


class AllocationRuleDetail(models.Model):
    rule = models.ForeignKey(AllocationRule, on_delete=models.CASCADE, related_name='details')
    business_unit = models.CharField(max_length=100)
    allocation_rate = models.DecimalField(
        max_digits=7, decimal_places=4,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'business_unit']
        constraints = [
            models.UniqueConstraint(
                fields=['rule', 'business_unit'], name='unique_rule_business_unit'
            )
        ]


class Vendor(models.Model):
    class Type(models.TextChoices):
        TRANSPORT = 'TRANSPORT', '운반'
        DISPOSAL = 'DISPOSAL', '처리'
        BOTH = 'BOTH', '운반/처리'

    vendor_name = models.CharField(max_length=100, unique=True)
    business_number = models.CharField(max_length=20, blank=True)
    vendor_type = models.CharField(max_length=10, choices=Type.choices)
    manager_name = models.CharField(max_length=100, blank=True)
    manager_email = models.EmailField(blank=True)
    mail_cc = models.TextField(blank=True)
    mail_enabled = models.BooleanField(default=False)
    allocation_rule = models.ForeignKey(
        AllocationRule, blank=True, null=True, on_delete=models.PROTECT,
        related_name='vendors',
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.vendor_name


class VendorPrice(models.Model):
    class Type(models.TextChoices):
        TRANSPORT = 'TRANSPORT', '운반'
        DISPOSAL = 'DISPOSAL', '처리'

    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name='prices')
    waste_type = models.CharField(max_length=100)
    price_type = models.CharField(max_length=10, choices=Type.choices)
    unit_price = models.DecimalField(max_digits=16, decimal_places=4)
    unit = models.CharField(max_length=20, default='kg')
    valid_from = models.DateField()
    valid_to = models.DateField(blank=True, null=True)

    class Meta:
        ordering = ['-valid_from', 'vendor__vendor_name', 'waste_type']
        constraints = [
            models.UniqueConstraint(
                fields=['vendor', 'waste_type', 'price_type', 'valid_from'],
                name='unique_vendor_price_start',
            )
        ]


class Settlement(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', '작성 중'
        SOURCE_LOADED = 'SOURCE_LOADED', '데이터 불러오기 완료'
        VENDOR_CALCULATED = 'VENDOR_CALCULATED', '업체 정산 완료'
        ALLOCATED = 'ALLOCATED', '사업부 배분 완료'
        VALIDATED = 'VALIDATED', '검증 완료'
        CONFIRMED = 'CONFIRMED', '정산 확정'
        REPORT_GENERATED = 'REPORT_GENERATED', '보고서 생성 완료'
        EMAIL_SENT = 'EMAIL_SENT', '메일 발송 완료'

    settlement_month = models.DateField(unique=True)
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='waste_settlements'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-settlement_month']

    def __str__(self):
        return self.settlement_month.strftime('%Y-%m')


class SettlementSource(models.Model):
    settlement = models.ForeignKey(
        Settlement, on_delete=models.CASCADE, related_name='sources'
    )
    source_id = models.CharField(max_length=100)
    weigh_date = models.DateTimeField()
    waste_type = models.CharField(max_length=100)
    transport_company = models.CharField(max_length=100)
    disposal_company = models.CharField(max_length=100)
    weight = models.DecimalField(max_digits=16, decimal_places=3)
    weight_unit = models.CharField(max_length=20, default='kg')
    vehicle_no = models.CharField(max_length=30, blank=True)
    slip_no = models.CharField(max_length=50, blank=True)
    source_reference = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['weigh_date', 'source_id']
        constraints = [
            models.UniqueConstraint(
                fields=['settlement', 'source_id'], name='unique_settlement_source'
            )
        ]


class SettlementVendor(models.Model):
    settlement = models.ForeignKey(
        Settlement, on_delete=models.CASCADE, related_name='vendor_results'
    )
    source = models.ForeignKey(
        SettlementSource, on_delete=models.CASCADE, related_name='vendor_results'
    )
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    vendor_name = models.CharField(max_length=100)
    waste_type = models.CharField(max_length=100)
    price_type = models.CharField(max_length=10, choices=VendorPrice.Type.choices)
    weight = models.DecimalField(max_digits=16, decimal_places=3)
    unit = models.CharField(max_length=20)
    unit_price = models.DecimalField(max_digits=16, decimal_places=4)
    price_valid_from = models.DateField()
    price_valid_to = models.DateField(blank=True, null=True)
    allocation_rule_code = models.CharField(max_length=30, blank=True)
    allocation_rule_name = models.CharField(max_length=100, blank=True)
    raw_amount = models.DecimalField(max_digits=20, decimal_places=4)
    supply_amount = models.BigIntegerField()
    vat_amount = models.BigIntegerField()
    total_amount = models.BigIntegerField()

    class Meta:
        ordering = ['vendor_name', 'waste_type', 'price_type', 'source_id']
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'price_type'], name='unique_source_price_type'
            )
        ]


class SettlementAllocation(models.Model):
    vendor_result = models.ForeignKey(
        SettlementVendor, on_delete=models.CASCADE, related_name='allocations'
    )
    business_unit = models.CharField(max_length=100)
    allocation_rate = models.DecimalField(max_digits=7, decimal_places=4)
    sort_order = models.PositiveIntegerField(default=0)
    raw_supply_amount = models.DecimalField(max_digits=20, decimal_places=4)
    base_supply_amount = models.BigIntegerField()
    supply_adjustment = models.IntegerField(default=0)
    supply_amount = models.BigIntegerField()
    raw_vat_amount = models.DecimalField(max_digits=20, decimal_places=4)
    base_vat_amount = models.BigIntegerField()
    vat_adjustment = models.IntegerField(default=0)
    vat_amount = models.BigIntegerField()
    total_amount = models.BigIntegerField()

    class Meta:
        ordering = ['vendor_result_id', 'sort_order', 'business_unit']
        constraints = [
            models.UniqueConstraint(
                fields=['vendor_result', 'business_unit'],
                name='unique_result_business_unit',
            )
        ]


class SettlementValidation(models.Model):
    settlement = models.ForeignKey(
        Settlement, on_delete=models.CASCADE, related_name='validations'
    )
    code = models.CharField(max_length=50)
    passed = models.BooleanField()
    message = models.TextField(blank=True)
    checked_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(
                fields=['settlement', 'code'], name='unique_settlement_validation'
            )
        ]


class SettlementAuditLog(models.Model):
    settlement = models.ForeignKey(
        Settlement, on_delete=models.CASCADE, related_name='audit_logs'
    )
    action = models.CharField(max_length=50)
    user = models.ForeignKey(User, blank=True, null=True, on_delete=models.SET_NULL)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class SettlementEmail(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', '발송 대기'
        SENT = 'SENT', '발송 완료'
        FAILED = 'FAILED', '발송 실패'

    settlement = models.ForeignKey(
        Settlement, on_delete=models.CASCADE, related_name='emails'
    )
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    vendor_name = models.CharField(max_length=100)
    recipient_to = models.EmailField()
    recipient_cc = models.TextField(blank=True)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT
    )
    sent_by = models.ForeignKey(
        User, blank=True, null=True, on_delete=models.SET_NULL
    )
    sent_at = models.DateTimeField(blank=True, null=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['vendor_name', '-created_at']
