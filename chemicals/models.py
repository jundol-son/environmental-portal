from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

class NicsNotice(models.Model):
    post_id = models.CharField(max_length=20, unique=True, verbose_name="고유ID")
    title = models.CharField(max_length=500, verbose_name="제목")
    reg_date = models.DateField(verbose_name="등록일")
    content = models.TextField(verbose_name="본문내용", blank=True, null=True)
    file_links = models.TextField(verbose_name="첨부파일", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-reg_date', '-post_id']
        verbose_name = "안전원 고시"
        verbose_name_plural = "안전원 고시 목록"

    def __str__(self):
        return self.title

    # --- 아래 메서드를 추가했습니다 ---
    def get_file_list(self):
        """
        file_links에 저장된 '파일명 (URL)' 형태의 텍스트를 
        템플릿에서 사용하기 좋게 리스트 형태로 변환합니다.
        """
        if not self.file_links or self.file_links == "첨부파일 없음":
            return []
        
        files = []
        # 줄바꿈 단위로 파일을 나눕니다.
        lines = self.file_links.split('\n')
        for line in lines:
            # 마지막 '('의 위치와 맨 뒤 ')'를 기준으로 파일명과 URL을 추출합니다.
            if '(' in line and line.endswith(')'):
                idx = line.rfind('(')
                name_part = line[:idx].strip()
                link_part = line[idx+1:-1].strip()
                files.append({
                    'name': name_part,
                    'link': link_part
                })
        return files


class HandlerProfile(models.Model):
    knoxid = models.CharField(max_length=100, unique=True, verbose_name="KNOX ID")
    name = models.CharField(max_length=100, verbose_name="이름")
    department = models.CharField(max_length=200, verbose_name="부서")
    is_active = models.BooleanField(default=True, verbose_name="교육 대상")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["department", "name"]
        verbose_name = "취급자교육 대상자"
        verbose_name_plural = "취급자교육 대상자"

    def __str__(self):
        return f"{self.name} ({self.knoxid})"


class TrainingCompletion(models.Model):
    handler = models.ForeignKey(
        HandlerProfile,
        on_delete=models.CASCADE,
        related_name="training_completions",
        verbose_name="대상자",
    )
    target_year = models.PositiveSmallIntegerField(verbose_name="대상 연도")
    is_completed = models.BooleanField(default=False, verbose_name="최종 수료 여부")
    online_completion_code = models.TextField(blank=True, verbose_name="온라인교육 수료코드")
    online_completed_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="온라인교육 수료 처리 시각",
    )
    offline_application_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="오프라인교육 신청일자",
    )
    offline_completion_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="오프라인교육 수료일자",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["handler", "target_year"],
                name="unique_handler_training_year",
            )
        ]
        ordering = ["-target_year", "handler__department", "handler__name"]
        verbose_name = "취급자교육 수료 현황"
        verbose_name_plural = "취급자교육 수료 현황"

    def __str__(self):
        return f"{self.handler} - {self.target_year}"

    @property
    def online_completed(self):
        return bool((self.online_completion_code or "").strip())

    @property
    def offline_completed(self):
        return self.offline_completion_date is not None

    def calculate_is_completed(self):
        return self.online_completed and self.offline_completed

    def clean(self):
        if len((self.online_completion_code or "").strip()) > 500:
            raise ValidationError({"online_completion_code": "수료코드는 500자 이하로 입력해 주세요."})
        if (
            self.offline_application_date
            and self.offline_completion_date
            and self.offline_completion_date < self.offline_application_date
        ):
            raise ValidationError(
                {"offline_completion_date": "수료일자는 신청일자보다 빠를 수 없습니다."}
            )

    def save(self, *args, **kwargs):
        normalized_code = (self.online_completion_code or "").strip()
        previous_code = None
        if self.pk:
            previous_code = type(self).objects.filter(pk=self.pk).values_list(
                "online_completion_code", flat=True
            ).first()
            previous_code = (previous_code or "").strip()

        self.online_completion_code = normalized_code
        if not normalized_code:
            self.online_completed_at = None
        elif previous_code != normalized_code or not self.online_completed_at:
            self.online_completed_at = timezone.now()

        self.is_completed = self.calculate_is_completed()
        self.clean()
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                "online_completion_code",
                "online_completed_at",
                "is_completed",
            }
        super().save(*args, **kwargs)


class CompletionSubmissionLog(models.Model):
    completion = models.ForeignKey(
        TrainingCompletion,
        on_delete=models.CASCADE,
        related_name="submission_logs",
        verbose_name="수료 기록",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="제출자",
    )
    completion_code = models.TextField(blank=True, verbose_name="제출 수료코드")
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name="제출 시각")

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = "수료코드 제출 이력"
        verbose_name_plural = "수료코드 제출 이력"

    def __str__(self):
        return f"{self.completion} - {self.submitted_at:%Y-%m-%d %H:%M}"
