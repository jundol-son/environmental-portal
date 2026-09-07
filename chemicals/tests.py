from datetime import date, datetime, timedelta
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from .models import CompletionSubmissionLog, HandlerProfile, TrainingCompletion
from .views import UPDATE_HEADERS


class TrainingTestCase(TestCase):
    year = 2026

    def setUp(self):
        self.user = User.objects.create_user(username="KNOX001", password="test-password")
        self.other_user = User.objects.create_user(
            username="KNOX002", password="test-password"
        )
        self.manager = User.objects.create_user(
            username="manager", password="test-password"
        )
        self.manager.user_permissions.add(
            Permission.objects.get(codename="change_trainingcompletion")
        )
        self.handler = HandlerProfile.objects.create(
            knoxid="KNOX001", name="홍길동", department="환경팀"
        )
        self.other_handler = HandlerProfile.objects.create(
            knoxid="KNOX002", name="김환경", department="안전팀"
        )
        self.completion = TrainingCompletion.objects.create(
            handler=self.handler, target_year=self.year
        )
        self.other_completion = TrainingCompletion.objects.create(
            handler=self.other_handler, target_year=self.year
        )

    def _login(self, user):
        self.client.force_login(user)

    def _excel_file(self, rows, headers=("knoxid", "이름", "부서")):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        content = BytesIO()
        workbook.save(content)
        workbook.close()
        return SimpleUploadedFile(
            "handlers.xlsx",
            content.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def _status_excel_file(self, rows, headers=UPDATE_HEADERS):
        return self._excel_file(rows, headers=headers)

    def test_final_completion_requires_online_code_and_offline_completion(self):
        self.completion.online_completion_code = "ONLINE-CODE"
        self.completion.save()
        self.assertTrue(self.completion.online_completed)
        self.assertFalse(self.completion.is_completed)

        self.completion.online_completion_code = ""
        self.completion.offline_completion_date = date(2026, 5, 2)
        self.completion.save()
        self.assertTrue(self.completion.offline_completed)
        self.assertFalse(self.completion.is_completed)

        self.completion.online_completion_code = "ONLINE-CODE"
        self.completion.save()
        self.assertTrue(self.completion.is_completed)

        self.completion.offline_application_date = date(2026, 5, 3)
        with self.assertRaises(ValidationError):
            self.completion.save()

    def test_online_completed_at_changes_only_when_code_changes(self):
        first = timezone.now()
        second = first + timedelta(minutes=5)
        with patch("chemicals.models.timezone.now", return_value=first):
            self.completion.online_completion_code = " CODE-ONE "
            self.completion.save()
        self.assertEqual(self.completion.online_completion_code, "CODE-ONE")
        self.assertEqual(self.completion.online_completed_at, first)

        with patch("chemicals.models.timezone.now", return_value=second):
            self.completion.save()
        self.assertEqual(self.completion.online_completed_at, first)

        with patch("chemicals.models.timezone.now", return_value=second):
            self.completion.online_completion_code = "CODE-TWO"
            self.completion.save()
        self.assertEqual(self.completion.online_completed_at, second)

        self.completion.online_completion_code = ""
        self.completion.save()
        self.assertIsNone(self.completion.online_completed_at)

    def test_legacy_route_redirects_by_role_and_manager_endpoints_are_protected(self):
        legacy_url = reverse("training_dashboard")
        self.assertRedirects(
            self.client.get(legacy_url), f"/accounts/login/?next={legacy_url}"
        )

        self._login(self.user)
        self.assertRedirects(
            self.client.get(legacy_url, {"year": self.year}),
            f"{reverse('training_status')}?year={self.year}",
        )
        for name in (
            "training_manage",
            "training_upload",
            "training_excel_template",
            "training_status_upload",
            "training_export_csv",
        ):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)

        self._login(self.manager)
        self.assertRedirects(
            self.client.get(legacy_url, {"year": self.year}),
            f"{reverse('training_manage')}?year={self.year}",
        )

    @override_settings(
        HANDLER_TRAINING_ONLINE_URL="https://education.example/online",
        HANDLER_TRAINING_OFFLINE_URL="javascript:alert(1)",
    )
    def test_personal_status_uses_authenticated_knoxid_and_safe_links(self):
        self._login(self.user)
        response = self.client.get(
            reverse("training_status"),
            {"year": self.year, "knoxid": self.other_handler.knoxid},
        )
        self.assertContains(response, "홍길동")
        self.assertNotContains(response, "김환경")
        self.assertContains(response, "https://education.example/online")
        self.assertContains(response, "오프라인교육 연결 주소가 등록되지 않았습니다")
        self.assertNotContains(response, "javascript:alert(1)")

    @override_settings(HANDLER_TRAINING_KNOXID_ATTRIBUTE="sso_profile.knoxid")
    def test_personal_status_handles_missing_sso_knoxid(self):
        self._login(self.user)
        response = self.client.get(reverse("training_status"), {"year": self.year})
        self.assertContains(response, "사용자 식별정보를 확인할 수 없습니다")

    def test_code_submission_records_history_but_needs_offline_completion(self):
        self._login(self.user)
        url = reverse("training_submit", args=[self.completion.id])

        self.client.post(url, {"completion_code": "CODE-ONE"})
        self.completion.refresh_from_db()
        self.assertFalse(self.completion.is_completed)

        self.completion.offline_completion_date = date(2026, 6, 10)
        self.completion.save()
        self.client.post(url, {"completion_code": "CODE-TWO"})
        self.completion.refresh_from_db()
        self.assertTrue(self.completion.is_completed)
        self.assertEqual(self.completion.online_completion_code, "CODE-TWO")
        self.assertEqual(
            list(
                CompletionSubmissionLog.objects.order_by("submitted_at").values_list(
                    "completion_code", flat=True
                )
            ),
            ["CODE-ONE", "CODE-TWO"],
        )

    def test_blank_code_and_other_users_record_are_rejected(self):
        self._login(self.user)
        self.client.post(
            reverse("training_submit", args=[self.completion.id]),
            {"completion_code": "   "},
        )
        self.assertFalse(CompletionSubmissionLog.objects.exists())
        response = self.client.post(
            reverse("training_submit", args=[self.other_completion.id]),
            {"completion_code": "CODE"},
        )
        self.assertEqual(response.status_code, 404)

    def test_manager_can_register_code_for_any_target(self):
        self._login(self.manager)
        response = self.client.post(
            reverse("training_submit", args=[self.completion.id]),
            {"completion_code": "MANAGER-CODE"},
        )
        self.assertRedirects(
            response, f"{reverse('training_manage')}?year={self.year}"
        )
        self.completion.refresh_from_db()
        self.assertEqual(self.completion.online_completion_code, "MANAGER-CODE")

    def test_target_upload_still_upserts_and_preserves_missing_handlers(self):
        self._login(self.manager)
        upload = self._excel_file(
            [
                ["KNOX001", "홍길동", "변경부서"],
                ["KNOX003", "신규대상", "환경팀"],
            ]
        )
        response = self.client.post(
            reverse("training_upload"),
            {"target_year": 2027, "excel_file": upload},
        )

        self.assertRedirects(response, f"{reverse('training_manage')}?year=2027")
        self.handler.refresh_from_db()
        self.assertEqual(self.handler.department, "변경부서")
        self.assertTrue(HandlerProfile.objects.filter(knoxid="KNOX003").exists())
        self.assertTrue(HandlerProfile.objects.filter(knoxid="KNOX002").exists())
        self.assertEqual(TrainingCompletion.objects.filter(target_year=2027).count(), 2)

    def test_invalid_target_upload_is_not_partially_applied(self):
        self._login(self.manager)
        upload = self._excel_file(
            [
                ["KNOX003", "신규대상", "환경팀"],
                ["KNOX003", "중복대상", "안전팀"],
            ]
        )
        response = self.client.post(
            reverse("training_upload"),
            {"target_year": 2027, "excel_file": upload},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(HandlerProfile.objects.filter(knoxid="KNOX003").exists())

    def test_manager_stats_and_name_or_knoxid_search_use_final_status(self):
        self.other_completion.online_completion_code = "COMPLETE"
        self.other_completion.offline_completion_date = date(2026, 7, 1)
        self.other_completion.save()
        self._login(self.manager)

        response = self.client.get(reverse("training_manage"), {"year": self.year})
        self.assertEqual(response.context["total_count"], 2)
        self.assertEqual(response.context["completed_count"], 1)
        self.assertEqual(response.context["completion_rate"], 50.0)

        for query in ("김환경", "KNOX002"):
            response = self.client.get(
                reverse("training_manage"), {"year": self.year, "query": query}
            )
            self.assertContains(response, "김환경")
            self.assertNotContains(response, "홍길동")
            self.assertEqual(response.context["completed_count"], 1)

    def test_excel_template_contains_exact_update_headers(self):
        self._login(self.manager)
        response = self.client.get(
            reverse("training_excel_template"), {"year": self.year}
        )
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        headers = tuple(cell.value for cell in next(workbook.active.iter_rows()))
        workbook.close()
        self.assertEqual(headers, UPDATE_HEADERS)

    def test_status_upload_updates_existing_record_and_blank_cells_keep_values(self):
        self.completion.online_completion_code = "OLD-CODE"
        self.completion.offline_application_date = date(2026, 4, 1)
        self.completion.save()
        self._login(self.manager)
        upload = self._status_excel_file(
            [[self.year, "KNOX001", "홍길동", "환경팀", "NEW-CODE", datetime(2026, 4, 1), "2026-04-20"]]
        )
        response = self.client.post(
            reverse("training_status_upload"), {"excel_file": upload}
        )
        self.assertRedirects(response, f"{reverse('training_manage')}?year={self.year}")
        self.completion.refresh_from_db()
        self.assertEqual(self.completion.online_completion_code, "NEW-CODE")
        self.assertEqual(self.completion.offline_application_date, date(2026, 4, 1))
        self.assertEqual(self.completion.offline_completion_date, date(2026, 4, 20))
        self.assertTrue(self.completion.is_completed)

        keep_upload = self._status_excel_file(
            [[self.year, "KNOX001", "", "", "", "", ""]]
        )
        self.client.post(
            reverse("training_status_upload"), {"excel_file": keep_upload}
        )
        self.completion.refresh_from_db()
        self.assertEqual(self.completion.online_completion_code, "NEW-CODE")
        self.assertEqual(self.completion.offline_completion_date, date(2026, 4, 20))

    def test_status_upload_clear_token_resets_code_timestamp_and_final_status(self):
        self.completion.online_completion_code = "CODE"
        self.completion.offline_completion_date = date(2026, 4, 20)
        self.completion.save()
        self._login(self.manager)
        upload = self._status_excel_file(
            [[self.year, "KNOX001", "", "", "__CLEAR__", "", ""]]
        )
        self.client.post(reverse("training_status_upload"), {"excel_file": upload})
        self.completion.refresh_from_db()
        self.assertEqual(self.completion.online_completion_code, "")
        self.assertIsNone(self.completion.online_completed_at)
        self.assertFalse(self.completion.is_completed)

    def test_status_upload_error_rolls_back_all_rows(self):
        self._login(self.manager)
        upload = self._status_excel_file(
            [
                [self.year, "KNOX001", "", "", "SHOULD-NOT-SAVE", "", ""],
                [self.year, "UNKNOWN", "", "", "CODE", "", ""],
            ]
        )
        response = self.client.post(
            reverse("training_status_upload"), {"excel_file": upload}
        )
        self.assertContains(response, "교육 대상자가 없습니다")
        self.completion.refresh_from_db()
        self.assertEqual(self.completion.online_completion_code, "")

    def test_status_upload_rejects_formulas_and_invalid_date_order(self):
        self._login(self.manager)
        formula_upload = self._status_excel_file(
            [[self.year, "KNOX001", "", "", "=1+1", "", ""]]
        )
        response = self.client.post(
            reverse("training_status_upload"), {"excel_file": formula_upload}
        )
        self.assertContains(response, "수식 셀은 허용되지 않습니다")

        date_upload = self._status_excel_file(
            [[self.year, "KNOX001", "", "", "", "2026-05-02", "2026-05-01"]]
        )
        response = self.client.post(
            reverse("training_status_upload"), {"excel_file": date_upload}
        )
        self.assertContains(response, "수료일자는 신청일자보다 빠를 수 없습니다")

    def test_csv_contains_new_fields_and_neutralizes_spreadsheet_formulas(self):
        self.handler.name = "=FORMULA"
        self.handler.save()
        self.completion.online_completion_code = "+CODE"
        self.completion.offline_application_date = date(2026, 4, 1)
        self.completion.offline_completion_date = date(2026, 4, 20)
        self.completion.save()
        self._login(self.manager)
        response = self.client.get(
            reverse("training_export_csv"), {"year": self.year}
        )
        body = response.content.decode("utf-8-sig")
        self.assertIn("오프라인교육 신청일자", body)
        self.assertIn("'=FORMULA", body)
        self.assertIn("'+CODE", body)
        self.assertIn("수료", body)
