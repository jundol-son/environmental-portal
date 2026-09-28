from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from io import BytesIO
import re

from django.core.mail import EmailMessage
from django.core.mail import get_connection
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import (
    AllocationRule,
    AllocationRuleDetail,
    Settlement,
    SettlementAllocation,
    SettlementAuditLog,
    SettlementEmail,
    SettlementSource,
    SettlementValidation,
    SettlementVendor,
    Vendor,
    VendorPrice,
    WasteLog,
)

VAT_RATE = Decimal('0.10')


class SettlementError(Exception):
    pass


def settlement_period(month):
    month = month.replace(day=1)
    previous = month - timedelta(days=1)
    return previous.replace(day=21), month.replace(day=20)


def largest_remainder(total, details):
    rows = []
    for detail in details:
        raw = Decimal(total) * detail.allocation_rate / Decimal('100')
        base = int(raw.to_integral_value(rounding=ROUND_FLOOR))
        rows.append({
            'detail': detail,
            'raw': raw,
            'base': base,
            'adjustment': 0,
            'remainder': raw - base,
        })

    difference = total - sum(row['base'] for row in rows)
    ranked = sorted(
        rows,
        key=lambda row: (
            -row['remainder'],
            -row['detail'].allocation_rate,
            row['detail'].sort_order,
            row['detail'].business_unit,
        ),
    )
    for row in ranked[:difference]:
        row['adjustment'] = 1
    for row in rows:
        row['final'] = row['base'] + row['adjustment']
    return rows


class MockWeighingDataSource:
    def __init__(self, use_database=True):
        self.use_database = use_database

    def get_weighing_data(self, start_date, end_date):
        logs = WasteLog.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        ).order_by('created_at', 'id') if self.use_database else WasteLog.objects.none()
        if logs.exists():
            return [
                {
                    'source_id': f'WASTE-{item.pk}',
                    'weigh_date': item.created_at,
                    'waste_type': item.waste_type,
                    'transport_company': item.company,
                    'disposal_company': item.company,
                    'weight': Decimal(str(item.quantity)),
                    'weight_unit': item.unit,
                    'source_reference': f'WasteLog:{item.pk}',
                }
                for item in logs
            ], False

        noon = timezone.make_aware(datetime.combine(start_date, time(12)))
        return [
            {
                'source_id': 'MOCK-001',
                'weigh_date': noon,
                'waste_type': '폐유',
                'transport_company': '모의운반',
                'disposal_company': '모의처리',
                'weight': Decimal('100.000'),
                'weight_unit': 'kg',
                'source_reference': 'MockWeighingDataSource',
            },
            {
                'source_id': 'MOCK-002',
                'weigh_date': noon + timedelta(days=1),
                'waste_type': '폐산',
                'transport_company': '모의운반',
                'disposal_company': '모의처리',
                'weight': Decimal('33.330'),
                'weight_unit': 'kg',
                'source_reference': 'MockWeighingDataSource',
            },
        ], True


def _audit(settlement, action, user=None, before=None, after=None, reason=''):
    SettlementAuditLog.objects.create(
        settlement=settlement,
        action=action,
        user=user if getattr(user, 'is_authenticated', False) else None,
        before=before or {},
        after=after or {},
        reason=reason,
    )


@transaction.atomic
def create_settlement(month, user):
    month = month.replace(day=1)
    start, end = settlement_period(month)
    settlement, created = Settlement.objects.get_or_create(
        settlement_month=month,
        defaults={'period_start': start, 'period_end': end, 'created_by': user},
    )
    if created:
        _audit(settlement, 'CREATE', user, after={'status': settlement.status})
    return settlement, created


def _ensure_mock_master_data(start_date):
    rule, _ = AllocationRule.objects.get_or_create(
        rule_code='MOCK_RATE_01',
        defaults={
            'rule_name': '모의 기본 분배',
            'valid_from': start_date,
        },
    )
    if not rule.details.exists():
        AllocationRuleDetail.objects.bulk_create([
            AllocationRuleDetail(
                rule=rule, business_unit='Foundry',
                allocation_rate=Decimal('70'), sort_order=1,
            ),
            AllocationRuleDetail(
                rule=rule, business_unit='반도체연구소',
                allocation_rate=Decimal('15'), sort_order=2,
            ),
            AllocationRuleDetail(
                rule=rule, business_unit='CSS',
                allocation_rate=Decimal('15'), sort_order=3,
            ),
        ])

    transport, _ = Vendor.objects.get_or_create(
        vendor_name='모의운반',
        defaults={
            'vendor_type': Vendor.Type.TRANSPORT,
            'allocation_rule': rule,
        },
    )
    disposal, _ = Vendor.objects.get_or_create(
        vendor_name='모의처리',
        defaults={
            'vendor_type': Vendor.Type.DISPOSAL,
            'allocation_rule': rule,
        },
    )
    for vendor, manager_name, manager_email in (
        (transport, '모의 운반 담당자', 'transport@example.com'),
        (disposal, '모의 처리 담당자', 'disposal@example.com'),
    ):
        if not vendor.manager_email:
            vendor.manager_name = manager_name
            vendor.manager_email = manager_email
            vendor.mail_enabled = True
            vendor.save(update_fields=[
                'manager_name', 'manager_email', 'mail_enabled', 'updated_at'
            ])
    for waste_type in ('폐유', '폐산'):
        VendorPrice.objects.get_or_create(
            vendor=transport,
            waste_type=waste_type,
            price_type=VendorPrice.Type.TRANSPORT,
            valid_from=start_date,
            defaults={'unit_price': Decimal('120'), 'unit': 'kg'},
        )
        VendorPrice.objects.get_or_create(
            vendor=disposal,
            waste_type=waste_type,
            price_type=VendorPrice.Type.DISPOSAL,
            valid_from=start_date,
            defaults={'unit_price': Decimal('300'), 'unit': 'kg'},
        )


@transaction.atomic
def load_sources(settlement, user, data_source=None):
    if settlement.status in {
        Settlement.Status.CONFIRMED,
        Settlement.Status.REPORT_GENERATED,
        Settlement.Status.EMAIL_SENT,
    }:
        raise SettlementError('확정된 정산의 원본 데이터는 변경할 수 없습니다.')

    records, is_builtin_mock = (data_source or MockWeighingDataSource()).get_weighing_data(
        settlement.period_start, settlement.period_end
    )
    settlement.sources.all().delete()
    SettlementSource.objects.bulk_create([
        SettlementSource(
            settlement=settlement,
            source_id=row['source_id'],
            weigh_date=row['weigh_date'],
            waste_type=row['waste_type'],
            transport_company=row['transport_company'],
            disposal_company=row['disposal_company'],
            weight=row['weight'],
            weight_unit=row.get('weight_unit', 'kg'),
            vehicle_no=row.get('vehicle_no', ''),
            slip_no=row.get('slip_no', ''),
            source_reference=row.get('source_reference', ''),
        )
        for row in records
    ])
    if is_builtin_mock:
        _ensure_mock_master_data(settlement.period_start)

    before = settlement.status
    settlement.status = Settlement.Status.SOURCE_LOADED
    settlement.save(update_fields=['status', 'updated_at'])
    _audit(
        settlement,
        'LOAD_SOURCE',
        user,
        before={'status': before},
        after={'status': settlement.status, 'count': len(records)},
    )
    return len(records), is_builtin_mock


def compare_sources(settlement, data_source=None):
    records, _ = (data_source or MockWeighingDataSource()).get_weighing_data(
        settlement.period_start, settlement.period_end
    )
    fields = (
        'weigh_date',
        'waste_type',
        'transport_company',
        'disposal_company',
        'weight',
        'weight_unit',
        'vehicle_no',
        'slip_no',
        'source_reference',
    )
    current = {
        row.source_id: tuple(getattr(row, field) for field in fields)
        for row in settlement.sources.all()
    }
    latest = {
        row['source_id']: tuple(row.get(field, '') for field in fields)
        for row in records
    }
    current_ids = set(current)
    latest_ids = set(latest)
    return {
        'snapshot_count': len(current),
        'source_count': len(latest),
        'added': len(latest_ids - current_ids),
        'changed': sum(
            current[source_id] != latest[source_id]
            for source_id in current_ids & latest_ids
        ),
        'deleted': len(current_ids - latest_ids),
    }


def _active_price(vendor, source, price_type):
    day = source.weigh_date.date()
    return VendorPrice.objects.filter(
        vendor=vendor,
        waste_type=source.waste_type,
        price_type=price_type,
        valid_from__lte=day,
    ).filter(
        Q(valid_to__isnull=True) | Q(valid_to__gte=day)
    ).order_by('-valid_from').first()


def _vendor_for(name, price_type):
    allowed = (
        [Vendor.Type.TRANSPORT, Vendor.Type.BOTH]
        if price_type == VendorPrice.Type.TRANSPORT
        else [Vendor.Type.DISPOSAL, Vendor.Type.BOTH]
    )
    return Vendor.objects.filter(
        vendor_name=name, vendor_type__in=allowed, active=True
    ).first()


@transaction.atomic
def calculate_vendors(settlement, user):
    if settlement.status in {
        Settlement.Status.CONFIRMED,
        Settlement.Status.REPORT_GENERATED,
        Settlement.Status.EMAIL_SENT,
    }:
        raise SettlementError('확정된 정산은 재계산할 수 없습니다.')
    if not settlement.sources.exists():
        raise SettlementError('먼저 계근 데이터를 불러오세요.')

    prepared = []
    errors = []
    for source in settlement.sources.all():
        pairs = [
            (source.transport_company, VendorPrice.Type.TRANSPORT),
            (source.disposal_company, VendorPrice.Type.DISPOSAL),
        ]
        for vendor_name, price_type in pairs:
            vendor = _vendor_for(vendor_name, price_type)
            if not vendor:
                errors.append(f'{source.source_id}: {vendor_name} 업체 미등록')
                continue
            price = _active_price(vendor, source, price_type)
            if not price:
                errors.append(f'{source.source_id}: {vendor_name}/{source.waste_type} 단가 미등록')
                continue
            prepared.append((source, vendor, price, price_type))
    if errors:
        raise SettlementError(' / '.join(errors[:5]))

    settlement.vendor_results.all().delete()
    results = []
    for source, vendor, price, price_type in prepared:
        raw = source.weight * price.unit_price
        supply = int(raw.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        vat = int((Decimal(supply) * VAT_RATE).quantize(
            Decimal('1'), rounding=ROUND_HALF_UP
        ))
        results.append(SettlementVendor(
            settlement=settlement,
            source=source,
            vendor=vendor,
            vendor_name=vendor.vendor_name,
            waste_type=source.waste_type,
            price_type=price_type,
            weight=source.weight,
            unit=price.unit,
            unit_price=price.unit_price,
            price_valid_from=price.valid_from,
            price_valid_to=price.valid_to,
            raw_amount=raw,
            supply_amount=supply,
            vat_amount=vat,
            total_amount=supply + vat,
        ))
    SettlementVendor.objects.bulk_create(results)
    before = settlement.status
    settlement.status = Settlement.Status.VENDOR_CALCULATED
    settlement.save(update_fields=['status', 'updated_at'])
    _audit(
        settlement, 'CALCULATE_VENDOR', user,
        before={'status': before},
        after={'status': settlement.status, 'count': len(results)},
    )
    return len(results)


def _rule_applies(rule, settlement):
    return (
        rule
        and rule.active
        and rule.valid_from <= settlement.period_start
        and (not rule.valid_to or rule.valid_to >= settlement.period_end)
    )


@transaction.atomic
def set_vendor_allocation_rule(settlement, vendor, rule, user):
    if settlement.status in {
        Settlement.Status.CONFIRMED,
        Settlement.Status.REPORT_GENERATED,
        Settlement.Status.EMAIL_SENT,
    }:
        raise SettlementError('확정된 정산의 분배율은 변경할 수 없습니다.')
    if not settlement.vendor_results.filter(vendor=vendor).exists():
        raise SettlementError('이 정산에 포함되지 않은 업체입니다.')
    total = rule.details.aggregate(total=Sum('allocation_rate'))['total'] or 0
    if not _rule_applies(rule, settlement) or total != Decimal('100'):
        raise SettlementError('정산기간에 유효한 100% 분배율 규칙을 선택하세요.')

    previous_rule = vendor.allocation_rule
    vendor.allocation_rule = rule
    vendor.save(update_fields=['allocation_rule', 'updated_at'])
    SettlementAllocation.objects.filter(
        vendor_result__settlement=settlement
    ).delete()
    settlement.vendor_results.update(
        allocation_rule_code='', allocation_rule_name=''
    )
    settlement.validations.all().delete()
    settlement.status = Settlement.Status.VENDOR_CALCULATED
    settlement.save(update_fields=['status', 'updated_at'])
    _audit(
        settlement,
        'SET_ALLOCATION_RULE',
        user,
        before={'vendor': vendor.vendor_name, 'rule': getattr(previous_rule, 'rule_code', '')},
        after={'vendor': vendor.vendor_name, 'rule': rule.rule_code},
    )


@transaction.atomic
def allocate_business_units(settlement, user):
    if settlement.status in {
        Settlement.Status.CONFIRMED,
        Settlement.Status.REPORT_GENERATED,
        Settlement.Status.EMAIL_SENT,
    }:
        raise SettlementError('확정된 정산은 재배분할 수 없습니다.')
    results = list(settlement.vendor_results.select_related(
        'vendor__allocation_rule'
    ))
    if not results:
        raise SettlementError('먼저 업체별 정산을 계산하세요.')

    prepared = []
    errors = []
    for result in results:
        rule = result.vendor.allocation_rule
        if not rule:
            errors.append(f'{result.vendor_name}: 분배율 미등록')
            continue
        if not _rule_applies(rule, settlement):
            errors.append(f'{result.vendor_name}: 정산기간에 유효하지 않은 분배율')
            continue
        details = list(rule.details.all())
        rate_sum = sum((item.allocation_rate for item in details), Decimal('0'))
        if not details or rate_sum != Decimal('100'):
            errors.append(f'{result.vendor_name}: 분배율 합계가 100%가 아님')
            continue
        prepared.append((result, details))
    if errors:
        raise SettlementError(' / '.join(errors[:5]))

    SettlementAllocation.objects.filter(
        vendor_result__settlement=settlement
    ).delete()
    allocations = []
    for result, details in prepared:
        rule = result.vendor.allocation_rule
        result.allocation_rule_code = rule.rule_code
        result.allocation_rule_name = rule.rule_name
        supply_rows = largest_remainder(result.supply_amount, details)
        vat_rows = {
            row['detail'].pk: row
            for row in largest_remainder(result.vat_amount, details)
        }
        for supply in supply_rows:
            detail = supply['detail']
            vat = vat_rows[detail.pk]
            allocations.append(SettlementAllocation(
                vendor_result=result,
                business_unit=detail.business_unit,
                allocation_rate=detail.allocation_rate,
                sort_order=detail.sort_order,
                raw_supply_amount=supply['raw'],
                base_supply_amount=supply['base'],
                supply_adjustment=supply['adjustment'],
                supply_amount=supply['final'],
                raw_vat_amount=vat['raw'],
                base_vat_amount=vat['base'],
                vat_adjustment=vat['adjustment'],
                vat_amount=vat['final'],
                total_amount=supply['final'] + vat['final'],
            ))
    SettlementVendor.objects.bulk_update(
        [result for result, _ in prepared],
        ['allocation_rule_code', 'allocation_rule_name'],
    )
    SettlementAllocation.objects.bulk_create(allocations)
    before = settlement.status
    settlement.status = Settlement.Status.ALLOCATED
    settlement.save(update_fields=['status', 'updated_at'])
    _audit(
        settlement, 'ALLOCATE', user,
        before={'status': before},
        after={'status': settlement.status, 'count': len(allocations)},
    )
    return len(allocations)


def _source_snapshot_issues(settlement):
    unmatched = []
    missing_prices = []
    for source in settlement.sources.prefetch_related('vendor_results'):
        results = {item.price_type: item for item in source.vendor_results.all()}
        for name, price_type in (
            (source.transport_company, VendorPrice.Type.TRANSPORT),
            (source.disposal_company, VendorPrice.Type.DISPOSAL),
        ):
            result = results.get(price_type)
            if not result or result.vendor_name != name:
                unmatched.append(f'{source.source_id}/{name}')
                missing_prices.append(f'{source.source_id}/{name}/{source.waste_type}')
    return unmatched, missing_prices


@transaction.atomic
def validate_settlement(settlement, user):
    unmatched, missing_prices = _source_snapshot_issues(settlement)
    missing_rules = []
    invalid_rules = []
    vendor_supply = settlement.vendor_results.aggregate(
        total=Sum('supply_amount')
    )['total'] or 0
    vendor_vat = settlement.vendor_results.aggregate(
        total=Sum('vat_amount')
    )['total'] or 0
    vendor_total = settlement.vendor_results.aggregate(
        total=Sum('total_amount')
    )['total'] or 0
    allocations = SettlementAllocation.objects.filter(
        vendor_result__settlement=settlement
    )
    allocation_supply = allocations.aggregate(
        total=Sum('supply_amount')
    )['total'] or 0
    allocation_vat = allocations.aggregate(
        total=Sum('vat_amount')
    )['total'] or 0
    allocation_total = allocations.aggregate(
        total=Sum('total_amount')
    )['total'] or 0
    snapshot_issues = []
    for result in settlement.vendor_results.prefetch_related('allocations'):
        actual = list(result.allocations.all())
        rate_total = sum(
            (item.allocation_rate for item in actual), Decimal('0')
        )
        if not result.allocation_rule_code:
            missing_rules.append(result.vendor_name)
        if not actual or rate_total != Decimal('100'):
            invalid_rules.append(f'{result.vendor_name}({rate_total}%)')
            snapshot_issues.append(result.vendor_name)

    checks = [
        ('SOURCE', settlement.sources.exists(), f'{settlement.sources.count()}건'),
        ('UNMATCHED_VENDOR', not unmatched, ', '.join(unmatched[:5])),
        ('MISSING_PRICE', not missing_prices, ', '.join(missing_prices[:5])),
        ('MISSING_ALLOCATION', not missing_rules, ', '.join(sorted(set(missing_rules))[:5])),
        ('ALLOCATION_RATE', not invalid_rules, ', '.join(sorted(set(invalid_rules))[:5])),
        (
            'ALLOCATION_SNAPSHOT',
            not snapshot_issues,
            ', '.join(sorted(set(snapshot_issues))[:5]),
        ),
        (
            'SUPPLY_BALANCE',
            vendor_supply == allocation_supply,
            f'차액 {vendor_supply - allocation_supply:,}원',
        ),
        (
            'VAT_BALANCE',
            vendor_vat == allocation_vat,
            f'차액 {vendor_vat - allocation_vat:,}원',
        ),
        (
            'TOTAL_BALANCE',
            vendor_total == allocation_total,
            f'차액 {vendor_total - allocation_total:,}원',
        ),
    ]
    settlement.validations.all().delete()
    SettlementValidation.objects.bulk_create([
        SettlementValidation(
            settlement=settlement, code=code, passed=passed,
            message=message if message else ('정상' if passed else '오류'),
        )
        for code, passed, message in checks
    ])
    passed = all(item[1] for item in checks)
    before = settlement.status
    settlement.status = (
        Settlement.Status.VALIDATED if passed else Settlement.Status.ALLOCATED
    )
    settlement.save(update_fields=['status', 'updated_at'])
    _audit(
        settlement, 'VALIDATE', user,
        before={'status': before},
        after={'status': settlement.status, 'passed': passed},
    )
    return passed


def confirm_settlement(settlement, user):
    if settlement.status != Settlement.Status.VALIDATED:
        raise SettlementError('모든 검증을 통과한 정산만 확정할 수 있습니다.')
    if not validate_settlement(settlement, user):
        raise SettlementError('최종 재검증에 실패했습니다. 검증 결과를 확인하세요.')
    with transaction.atomic():
        settlement.refresh_from_db()
        before = settlement.status
        settlement.status = Settlement.Status.CONFIRMED
        settlement.confirmed_at = timezone.now()
        settlement.save(update_fields=['status', 'confirmed_at', 'updated_at'])
        _audit(
            settlement, 'CONFIRM', user,
            before={'status': before},
            after={
                'status': settlement.status,
                'confirmed_at': settlement.confirmed_at.isoformat(),
            },
        )


@transaction.atomic
def reopen_settlement(settlement, user, reason):
    if settlement.status not in {
        Settlement.Status.CONFIRMED,
        Settlement.Status.REPORT_GENERATED,
        Settlement.Status.EMAIL_SENT,
    }:
        raise SettlementError('완료된 정산만 다시 열 수 있습니다.')
    reason = reason.strip()
    if not reason:
        raise SettlementError('재작업 사유를 입력하세요.')
    before = settlement.status
    settlement.status = (
        Settlement.Status.ALLOCATED
        if SettlementAllocation.objects.filter(
            vendor_result__settlement=settlement
        ).exists()
        else Settlement.Status.VENDOR_CALCULATED
    )
    settlement.confirmed_at = None
    settlement.validations.all().delete()
    settlement.save(update_fields=['status', 'confirmed_at', 'updated_at'])
    _audit(
        settlement,
        'REOPEN',
        user,
        before={'status': before},
        after={'status': settlement.status},
        reason=reason,
    )


@transaction.atomic
def apply_manual_adjustment(settlement, source, target, amount, reason, user):
    if settlement.status not in {
        Settlement.Status.ALLOCATED,
        Settlement.Status.VALIDATED,
    }:
        raise SettlementError('사업부 배분 후 확정 전에만 추가 보정할 수 있습니다.')
    if source.pk == target.pk or source.vendor_result_id != target.vendor_result_id:
        raise SettlementError('같은 업체 정산 행의 서로 다른 사업부를 선택하세요.')
    if amount <= 0 or source.supply_amount < amount:
        raise SettlementError('보정금액은 차감 가능한 1원 이상의 정수여야 합니다.')
    reason = reason.strip()
    if not reason:
        raise SettlementError('추가 보정 사유를 입력하세요.')

    before = {
        'source': source.pk,
        'source_amount': source.supply_amount,
        'target': target.pk,
        'target_amount': target.supply_amount,
    }
    source.supply_adjustment -= amount
    source.supply_amount -= amount
    source.total_amount -= amount
    target.supply_adjustment += amount
    target.supply_amount += amount
    target.total_amount += amount
    SettlementAllocation.objects.bulk_update(
        [source, target],
        ['supply_adjustment', 'supply_amount', 'total_amount'],
    )
    settlement.validations.all().delete()
    settlement.status = Settlement.Status.ALLOCATED
    settlement.save(update_fields=['status', 'updated_at'])
    _audit(
        settlement,
        'MANUAL_ADJUST',
        user,
        before=before,
        after={
            'source': source.pk,
            'source_amount': source.supply_amount,
            'target': target.pk,
            'target_amount': target.supply_amount,
            'amount': amount,
        },
        reason=reason,
    )


@transaction.atomic
def mark_report_generated(settlement, user):
    if settlement.status not in {
        Settlement.Status.CONFIRMED,
        Settlement.Status.REPORT_GENERATED,
    }:
        raise SettlementError('확정된 정산만 결과물을 생성할 수 있습니다.')
    before = settlement.status
    settlement.status = Settlement.Status.REPORT_GENERATED
    settlement.save(update_fields=['status', 'updated_at'])
    _audit(
        settlement, 'GENERATE_REPORT', user,
        before={'status': before},
        after={'status': settlement.status},
    )


def settlement_totals(settlement):
    totals = settlement.vendor_results.aggregate(
        weight=Sum('weight'),
        supply=Sum('supply_amount'),
        vat=Sum('vat_amount'),
        total=Sum('total_amount'),
    )
    return {key: value or 0 for key, value in totals.items()}


def business_unit_totals(settlement):
    return SettlementAllocation.objects.filter(
        vendor_result__settlement=settlement
    ).values('business_unit').annotate(
        supply=Sum('supply_amount'),
        vat=Sum('vat_amount'),
        total=Sum('total_amount'),
    ).order_by('business_unit')


def vendor_totals(settlement):
    return settlement.vendor_results.values('vendor_name').annotate(
        weight=Sum('weight'),
        supply=Sum('supply_amount'),
        vat=Sum('vat_amount'),
        total=Sum('total_amount'),
    ).order_by('vendor_name')


def build_settlement_excel(settlement, vendor_id=None):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '정산결과'
    headers = [
        '업체', '업무유형', '분배규칙', '사업부', '폐기물', '계근량', '단위',
        '적용단가', '공급가액', '분배율', '배분 공급가액',
        '부가세', '총금액', '공급가액 보정', '부가세 보정',
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    allocations = SettlementAllocation.objects.filter(
        vendor_result__settlement=settlement
    ).select_related('vendor_result')
    if vendor_id:
        allocations = allocations.filter(vendor_result__vendor_id=vendor_id)
    for allocation in allocations:
        result = allocation.vendor_result
        sheet.append([
            result.vendor_name,
            result.get_price_type_display(),
            result.allocation_rule_code,
            allocation.business_unit,
            result.waste_type,
            float(result.weight),
            result.unit,
            float(result.unit_price),
            result.supply_amount,
            float(allocation.allocation_rate),
            allocation.supply_amount,
            allocation.vat_amount,
            allocation.total_amount,
            allocation.supply_adjustment,
            allocation.vat_adjustment,
        ])
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        width = max(len(str(cell.value or '')) for cell in column) + 2
        sheet.column_dimensions[column[0].column_letter].width = min(width, 24)

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


@transaction.atomic
def prepare_settlement_emails(settlement, user):
    if settlement.status != Settlement.Status.REPORT_GENERATED:
        raise SettlementError('보고서 생성 후 메일 초안을 만들 수 있습니다.')
    vendors = Vendor.objects.filter(
        settlementvendor__settlement=settlement,
        mail_enabled=True,
    ).exclude(manager_email='').distinct().order_by('vendor_name')
    if not vendors.exists():
        raise SettlementError('메일 사용 업체의 TO 주소를 먼저 등록하세요.')

    created = 0
    for vendor in vendors:
        totals = settlement.vendor_results.filter(vendor=vendor).aggregate(
            supply=Sum('supply_amount'),
            vat=Sum('vat_amount'),
            total=Sum('total_amount'),
        )
        month = settlement.settlement_month.strftime('%Y년 %m월')
        defaults = {
            'vendor_name': vendor.vendor_name,
            'recipient_to': vendor.manager_email,
            'recipient_cc': vendor.mail_cc,
            'subject': f'[폐기물 정산] {month} {vendor.vendor_name}',
            'body': (
                f'{vendor.manager_name or vendor.vendor_name} 담당자님,\n\n'
                f'{month} 폐기물 정산 결과를 전달드립니다.\n'
                f'정산기간: {settlement.period_start:%Y-%m-%d} ~ '
                f'{settlement.period_end:%Y-%m-%d}\n'
                f"공급가액: {totals['supply'] or 0:,}원\n"
                f"부가세: {totals['vat'] or 0:,}원\n"
                f"총금액: {totals['total'] or 0:,}원\n\n"
                '첨부된 업체별 정산 Excel을 확인해 주세요.'
            ),
            'status': SettlementEmail.Status.DRAFT,
            'sent_by': None,
            'sent_at': None,
            'error_message': '',
        }
        email = SettlementEmail.objects.filter(
            settlement=settlement,
            vendor=vendor,
            status__in=[
                SettlementEmail.Status.DRAFT,
                SettlementEmail.Status.FAILED,
            ],
        ).first()
        if email is None:
            SettlementEmail.objects.create(
                settlement=settlement, vendor=vendor, **defaults
            )
            created += 1
        else:
            for field, value in defaults.items():
                setattr(email, field, value)
            email.save()
    _audit(
        settlement, 'PREPARE_EMAIL', user,
        after={'count': vendors.count(), 'created': created},
    )
    return vendors.count()


def send_settlement_email(email, user):
    settlement = email.settlement
    if settlement.status not in {
        Settlement.Status.REPORT_GENERATED,
        Settlement.Status.EMAIL_SENT,
    }:
        raise SettlementError('보고서 생성 후 메일을 발송할 수 있습니다.')
    if email.status == SettlementEmail.Status.SENT:
        raise SettlementError('이미 발송한 메일입니다.')
    cc = [item for item in re.split(r'[,;\s]+', email.recipient_cc) if item]
    backend = getattr(
        settings,
        'WASTE_SETTLEMENT_EMAIL_BACKEND',
        'django.core.mail.backends.console.EmailBackend',
    )
    message = EmailMessage(
        subject=email.subject,
        body=email.body,
        from_email=getattr(
            settings, 'WASTE_SETTLEMENT_FROM_EMAIL', 'waste-settlement@localhost'
        ),
        to=[email.recipient_to],
        cc=cc,
        connection=get_connection(backend=backend),
    )
    month = settlement.settlement_month.strftime('%Y%m')
    message.attach(
        f'settlement_{month}_{email.vendor_id}.xlsx',
        build_settlement_excel(settlement, vendor_id=email.vendor_id),
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    try:
        if message.send(fail_silently=False) != 1:
            raise RuntimeError('메일 백엔드가 발송 완료를 반환하지 않았습니다.')
    except Exception as exc:
        email.status = SettlementEmail.Status.FAILED
        email.error_message = str(exc)[:1000]
        email.save(update_fields=['status', 'error_message', 'updated_at'])
        raise SettlementError(f'메일 발송 실패: {exc}') from exc

    email.status = SettlementEmail.Status.SENT
    email.sent_by = user
    email.sent_at = timezone.now()
    email.error_message = ''
    email.save(update_fields=[
        'status', 'sent_by', 'sent_at', 'error_message', 'updated_at'
    ])
    _audit(
        settlement, 'SEND_EMAIL', user,
        after={
            'email_id': email.pk,
            'vendor': email.vendor_name,
            'to': email.recipient_to,
        },
    )
    if settlement.emails.exists() and not settlement.emails.exclude(
        status=SettlementEmail.Status.SENT
    ).exists():
        settlement.status = Settlement.Status.EMAIL_SENT
        settlement.save(update_fields=['status', 'updated_at'])
