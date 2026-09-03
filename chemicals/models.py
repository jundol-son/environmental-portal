from django.conf import settings
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
    is_completed = models.BooleanField(default=False, verbose_name="수료 여부")
    completion_code = models.TextField(blank=True, verbose_name="수료코드")
    completed_at = models.DateTimeField(blank=True, null=True, verbose_name="수료 처리 시각")
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

    def save(self, *args, **kwargs):
        self.completion_code = self.completion_code.strip()
        self.is_completed = bool(self.completion_code)
        if self.is_completed and not self.completed_at:
            self.completed_at = timezone.now()
        elif not self.is_completed:
            self.completed_at = None
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                "completion_code",
                "is_completed",
                "completed_at",
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
    completion_code = models.TextField(verbose_name="제출 수료코드")
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name="제출 시각")

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = "수료코드 제출 이력"
        verbose_name_plural = "수료코드 제출 이력"

    def __str__(self):
        return f"{self.completion} - {self.submitted_at:%Y-%m-%d %H:%M}"
