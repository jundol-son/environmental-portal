from django.db import models
import re

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