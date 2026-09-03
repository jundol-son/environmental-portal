from datetime import date

from django import forms


class CompletionCodeForm(forms.Form):
    completion_code = forms.CharField(
        label="온라인 교육 수료코드",
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
        return excel_file
