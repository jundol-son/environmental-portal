import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from wastes.models import (
    AllocationRule,
    AllocationRuleDetail,
    Settlement,
    Vendor,
    VendorPrice,
    WasteLog,
)
from wastes.settlement_services import (
    allocate_business_units,
    calculate_vendors,
    create_settlement,
    load_sources,
    settlement_period,
    validate_settlement,
)

MONTHS = [date(2026, month, 1) for month in range(4, 10)]
ROWS_PER_MONTH = 12
WASTE_TYPES = ['폐유', '폐산', '폐알칼리', '폐합성수지']
COMPANIES = ['[모의] 그린환경', '[모의] 에코리사이클', '[모의] 청정운반처리']


def _rule(code, name, valid_from, rows):
    rule, _ = AllocationRule.objects.get_or_create(
        rule_code=code,
        defaults={'rule_name': name, 'valid_from': valid_from},
    )
    if not rule.details.exists():
        AllocationRuleDetail.objects.bulk_create([
            AllocationRuleDetail(
                rule=rule,
                business_unit=business_unit,
                allocation_rate=Decimal(rate),
                sort_order=sort_order,
            )
            for business_unit, rate, sort_order in rows
        ])
    return rule


def _seed_master_data():
    rate_01 = _rule(
        'DEV_RATE_01',
        '개발용 70/15/15',
        date(2026, 1, 1),
        [('Foundry', '70', 1), ('반도체연구소', '15', 2), ('CSS', '15', 3)],
    )
    rate_02 = _rule(
        'DEV_RATE_02',
        '개발용 90/10',
        date(2026, 1, 1),
        [('Foundry', '90', 1), ('반도체연구소', '10', 2)],
    )

    for index, company in enumerate(COMPANIES):
        vendor, _ = Vendor.objects.get_or_create(
            vendor_name=company,
            defaults={
                'vendor_type': Vendor.Type.BOTH,
                'allocation_rule': rate_01 if index != 1 else rate_02,
            },
        )
        for waste_index, waste_type in enumerate(WASTE_TYPES):
            for price_type, base_price in (
                (VendorPrice.Type.TRANSPORT, 90),
                (VendorPrice.Type.DISPOSAL, 210),
            ):
                VendorPrice.objects.get_or_create(
                    vendor=vendor,
                    waste_type=waste_type,
                    price_type=price_type,
                    valid_from=date(2026, 1, 1),
                    defaults={
                        'unit_price': Decimal(base_price + index * 15 + waste_index * 10),
                        'unit': 'kg',
                    },
                )


def _seed_month(month, manager):
    period_start, period_end = settlement_period(month)
    existing = WasteLog.objects.filter(
        company__startswith='[모의]',
        created_at__date__gte=period_start,
        created_at__date__lte=period_end,
    ).count()
    for index in range(existing, ROWS_PER_MONTH):
        rng = random.Random(month.month * 100 + index)
        day = period_start + timedelta(days=(index * 2) % 30)
        when = timezone.make_aware(datetime.combine(
            day,
            time(hour=8 + index % 9, minute=(index * 7) % 60),
        ))
        log = WasteLog.objects.create(
            manager=manager,
            waste_type=WASTE_TYPES[index % len(WASTE_TYPES)],
            quantity=round(rng.uniform(80, 850), 3),
            unit='kg',
            company=COMPANIES[index % len(COMPANIES)],
        )
        WasteLog.objects.filter(pk=log.pk).update(created_at=when)
    return ROWS_PER_MONTH - existing


def _build_settlement(month, user):
    settlement, _ = create_settlement(month, user)
    if settlement.status in {
        Settlement.Status.CONFIRMED,
        Settlement.Status.REPORT_GENERATED,
        Settlement.Status.EMAIL_SENT,
    }:
        return settlement, True
    load_sources(settlement, user)
    calculate_vendors(settlement, user)
    allocate_business_units(settlement, user)
    if not validate_settlement(settlement, user):
        raise RuntimeError(f'{month:%Y-%m} 정산 검증 실패')
    settlement.refresh_from_db()
    return settlement, False


@transaction.atomic
def run():
    user_model = get_user_model()
    user = user_model.objects.filter(is_superuser=True).first() or user_model.objects.first()
    if not user:
        raise RuntimeError('모의 데이터를 연결할 사용자가 없습니다.')

    _seed_master_data()
    print('월       신규 계근  Snapshot  상태')
    for month in MONTHS:
        created = _seed_month(month, user)
        settlement, skipped = _build_settlement(month, user)
        suffix = ' (확정되어 건너뜀)' if skipped else ''
        print(
            f'{month:%Y-%m}  {created:>4}건      '
            f'{settlement.sources.count():>4}건   '
            f'{settlement.get_status_display()}{suffix}'
        )
