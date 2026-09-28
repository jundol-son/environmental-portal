from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q

from .models import (
    AllocationRule,
    AllocationRuleDetail,
    Vendor,
    VendorPrice,
)


class BootstrapFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = 'form-check-input' if isinstance(
                field.widget, forms.CheckboxInput
            ) else 'form-control'
            field.widget.attrs.setdefault('class', css)


class SettlementStartForm(BootstrapFormMixin, forms.Form):
    settlement_month = forms.CharField(
        label='정산월',
        widget=forms.TextInput(attrs={'type': 'month'}),
    )

    def clean_settlement_month(self):
        value = self.cleaned_data['settlement_month']
        try:
            return datetime.strptime(value, '%Y-%m').date()
        except ValueError as exc:
            raise forms.ValidationError('정산월 형식이 올바르지 않습니다.') from exc


class VendorForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Vendor
        fields = [
            'vendor_name',
            'business_number',
            'vendor_type',
            'manager_name',
            'manager_email',
            'mail_cc',
            'mail_enabled',
            'allocation_rule',
            'active',
        ]
        labels = {
            'vendor_name': '업체명',
            'business_number': '사업자번호',
            'vendor_type': '업체 유형',
            'manager_name': '정산 담당자',
            'manager_email': 'TO',
            'mail_cc': 'CC',
            'mail_enabled': '메일 사용',
            'allocation_rule': '분배율 규칙',
            'active': '사용',
        }

    def clean_mail_cc(self):
        addresses = [
            item for item in re.split(r'[,;\s]+', self.cleaned_data['mail_cc'])
            if item
        ]
        try:
            for address in addresses:
                validate_email(address)
        except ValidationError as exc:
            raise forms.ValidationError('CC 이메일 주소를 확인하세요.') from exc
        return ', '.join(addresses)


class VendorPriceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = VendorPrice
        fields = [
            'vendor', 'waste_type', 'price_type', 'unit_price',
            'unit', 'valid_from', 'valid_to',
        ]
        labels = {
            'vendor': '업체',
            'waste_type': '폐기물 종류',
            'price_type': '업무 유형',
            'unit_price': '단가',
            'unit': '단위',
            'valid_from': '적용 시작일',
            'valid_to': '적용 종료일',
        }
        widgets = {
            'valid_from': forms.DateInput(attrs={'type': 'date'}),
            'valid_to': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('valid_from')
        end = cleaned.get('valid_to')
        if start and end and start > end:
            self.add_error('valid_to', '종료일은 시작일보다 빠를 수 없습니다.')
        required = ('vendor', 'waste_type', 'price_type')
        if start and all(cleaned.get(name) for name in required):
            overlaps = VendorPrice.objects.filter(
                vendor=cleaned['vendor'],
                waste_type=cleaned['waste_type'],
                price_type=cleaned['price_type'],
            ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=start))
            if end:
                overlaps = overlaps.filter(valid_from__lte=end)
            if self.instance.pk:
                overlaps = overlaps.exclude(pk=self.instance.pk)
            if overlaps.exists():
                raise forms.ValidationError('같은 조건의 단가 적용기간이 겹칩니다.')
        return cleaned


class AllocationRuleForm(BootstrapFormMixin, forms.ModelForm):
    details_text = forms.CharField(
        label='사업부별 분배율',
        help_text='한 줄에 사업부|비율|정렬순서 형식으로 입력하세요.',
        widget=forms.Textarea(attrs={
            'rows': 5,
            'placeholder': 'Foundry|70|1\n반도체연구소|15|2\nCSS|15|3',
        }),
    )

    class Meta:
        model = AllocationRule
        fields = ['rule_code', 'rule_name', 'valid_from', 'valid_to', 'active']
        labels = {
            'rule_code': '규칙 코드',
            'rule_name': '규칙명',
            'valid_from': '적용 시작일',
            'valid_to': '적용 종료일',
            'active': '사용',
        }
        widgets = {
            'valid_from': forms.DateInput(attrs={'type': 'date'}),
            'valid_to': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            self.initial['details_text'] = '\n'.join(
                f'{item.business_unit}|{item.allocation_rate}|{item.sort_order}'
                for item in self.instance.details.all()
            )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('valid_from')
        end = cleaned.get('valid_to')
        if start and end and start > end:
            self.add_error('valid_to', '종료일은 시작일보다 빠를 수 없습니다.')
        return cleaned

    def clean_details_text(self):
        rows = []
        names = set()
        for line_number, line in enumerate(
            self.cleaned_data['details_text'].splitlines(), 1
        ):
            if not line.strip():
                continue
            parts = [part.strip() for part in line.split('|')]
            if len(parts) != 3:
                raise forms.ValidationError(f'{line_number}행 형식이 올바르지 않습니다.')
            name, rate_text, order_text = parts
            try:
                rate = Decimal(rate_text)
                order = int(order_text)
            except (InvalidOperation, ValueError) as exc:
                raise forms.ValidationError(
                    f'{line_number}행 비율 또는 순서가 올바르지 않습니다.'
                ) from exc
            if not name or name in names or rate < 0 or order < 0:
                raise forms.ValidationError(f'{line_number}행 값을 확인하세요.')
            names.add(name)
            rows.append((name, rate, order))
        if not rows or sum(row[1] for row in rows) != Decimal('100'):
            raise forms.ValidationError('분배율 합계는 정확히 100%여야 합니다.')
        return rows

    @transaction.atomic
    def save(self, commit=True):
        rule = super().save(commit=commit)
        if commit:
            rule.details.all().delete()
            AllocationRuleDetail.objects.bulk_create([
                AllocationRuleDetail(
                    rule=rule,
                    business_unit=name,
                    allocation_rate=rate,
                    sort_order=order,
                )
                for name, rate, order in self.cleaned_data['details_text']
            ])
        return rule
