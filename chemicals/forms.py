from datetime import date

from django import forms
from django.conf import settings


class CompletionCodeForm(forms.Form):
    completion_code = forms.CharField(
        label="온라인 교육 수료코드",
        max_length=500,
        strip=True,
        widget=forms.TextInput(
            attrs={"class": "form-control", "autocomplete": "off"}
        ),
    )


class TrainingUploadForm(forms.Form):
    target_year = forms.IntegerField(
        label="대상 연도",
        min_value=2000,
        max_value=2100,
        initial=date.today().year,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )
    excel_file = forms.FileField(
        label="대상자 엑셀 파일",
        widget=forms.FileInput(
            attrs={"class": "form-control", "accept": ".xlsx"}
        ),
    )

    def clean_excel_file(self):
        excel_file = self.cleaned_data["excel_file"]
        if not excel_file.name.lower().endswith(".xlsx"):
            raise forms.ValidationError(".xlsx 형식의 엑셀 파일만 업로드할 수 있습니다.")
        allowed_types = {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/octet-stream",
        }
        if excel_file.content_type and excel_file.content_type not in allowed_types:
            raise forms.ValidationError("엑셀 .xlsx 파일만 업로드할 수 있습니다.")
        max_bytes = getattr(settings, "HANDLER_TRAINING_UPLOAD_MAX_BYTES", 5 * 1024 * 1024)
        if excel_file.size > max_bytes:
            raise forms.ValidationError(
                f"파일 크기는 {max_bytes // (1024 * 1024)}MB 이하여야 합니다."
            )
        return excel_file


class TrainingStatusUploadForm(forms.Form):
    excel_file = forms.FileField(
        label="수료현황 엑셀 파일",
        widget=forms.FileInput(
            attrs={"class": "form-control", "accept": ".xlsx"}
        ),
    )

    def clean_excel_file(self):
        excel_file = self.cleaned_data["excel_file"]
        if not excel_file.name.lower().endswith(".xlsx"):
            raise forms.ValidationError(".xlsx 형식의 엑셀 파일만 업로드할 수 있습니다.")
        max_bytes = getattr(settings, "HANDLER_TRAINING_UPLOAD_MAX_BYTES", 5 * 1024 * 1024)
        if excel_file.size > max_bytes:
            raise forms.ValidationError(
                f"파일 크기는 {max_bytes // (1024 * 1024)}MB 이하여야 합니다."
            )
        allowed_types = {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/octet-stream",
        }
        if excel_file.content_type and excel_file.content_type not in allowed_types:
            raise forms.ValidationError("올바른 .xlsx 파일을 선택해 주세요.")
        return excel_file
