from io import BytesIO

from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from .models import CompletionSubmissionLog, HandlerProfile, TrainingCompletion


class TrainingTestCase(TestCase):
    year = 2026

    def setUp(self):
        self.user = User.objects.create_user(username="KNOX001", password="test-password")
        self.other_user = User.objects.create_user(username="KNOX002", password="test-password")
        self.manager = User.objects.create_user(username="manager", password="test-password")
        self.manager.user_permissions.add(
            Permission.objects.get(codename="change_trainingcompletion")
        )
        self.handler = HandlerProfile.objects.create(
            knoxid="KNOX001",
            name="홍길동",
            department="환경팀",
        )
        self.other_handler = HandlerProfile.objects.create(
            knoxid="KNOX002",
            name="김환경",
            department="안전팀",
        )
        self.completion = TrainingCompletion.objects.create(
            handler=self.handler,
            target_year=self.year,
        )
        TrainingCompletion.objects.create(
            handler=self.other_handler,
            target_year=self.year,
        )

    def _login(self, user):
        self.client.force_login(user)

    def _excel_file(self, rows):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["knoxid", "이름", "부서"])
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

    def test_training_dashboard_requires_login_and_limits_user_to_own_row(self):
        url = reverse("training_dashboard")
        self.assertRedirects(self.client.get(url), f"/accounts/login/?next={url}")

        self._login(self.user)
        response = self.client.get(url, {"year": self.year})
        self.assertContains(response, "홍길동")
        self.assertContains(response, "환경팀")
        self.assertNotContains(response, "김환경")
        self.assertEqual(response.context["total_count"], 1)

    def test_code_submission_completes_and_resubmission_keeps_history(self):
        self._login(self.user)
        url = reverse("training_submit", args=[self.completion.id])

        self.client.post(url, {"completion_code": "CODE-ONE"})
        self.client.post(url, {"completion_code": "CODE-TWO"})

        self.completion.refresh_from_db()
        self.assertTrue(self.completion.is_completed)
        self.assertEqual(self.completion.completion_code, "CODE-TWO")
        self.assertEqual(
            list(
                CompletionSubmissionLog.objects.order_by("submitted_at").values_list(
                    "completion_code", flat=True
                )
            ),
            ["CODE-ONE", "CODE-TWO"],
        )

    def test_blank_code_is_rejected(self):
        self._login(self.user)
        self.client.post(
            reverse("training_submit", args=[self.completion.id]),
            {"completion_code": "   "},
        )
        self.completion.refresh_from_db()
        self.assertFalse(self.completion.is_completed)
        self.assertFalse(CompletionSubmissionLog.objects.exists())

    def test_user_cannot_submit_for_an_unmatched_knoxid(self):
        self._login(self.other_user)
        self.other_handler.is_active = False
        self.other_handler.save()
        response = self.client.post(
            reverse("training_submit", args=[self.completion.id]),
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
            response,
            f"{reverse('training_dashboard')}?year={self.year}",
        )
        self.completion.refresh_from_db()
        self.assertTrue(self.completion.is_completed)
        self.assertEqual(self.completion.completion_code, "MANAGER-CODE")

    def test_manager_upload_upserts_rows_and_preserves_missing_handlers(self):
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

        self.assertRedirects(response, f"{reverse('training_dashboard')}?year=2027")
        self.handler.refresh_from_db()
        self.assertEqual(self.handler.department, "변경부서")
        self.assertTrue(HandlerProfile.objects.filter(knoxid="KNOX003").exists())
        self.assertTrue(HandlerProfile.objects.filter(knoxid="KNOX002").exists())
        self.assertEqual(TrainingCompletion.objects.filter(target_year=2027).count(), 2)

    def test_invalid_upload_is_not_partially_applied(self):
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

    def test_manager_csv_contains_completion_code_and_requires_permission(self):
        self.completion.is_completed = True
        self.completion.completion_code = "VISIBLE-CODE"
        self.completion.save()
        url = reverse("training_export_csv")

        self._login(self.user)
        self.assertEqual(self.client.get(url, {"year": self.year}).status_code, 403)

        self._login(self.manager)
        response = self.client.get(url, {"year": self.year})
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8-sig")
        self.assertIn("VISIBLE-CODE", body)
        self.assertIn("홍길동", body)

    def test_manager_dashboard_counts_all_active_targets(self):
        self.completion.completion_code = "COMPLETED-CODE"
        self.completion.save()
        self._login(self.manager)
        response = self.client.get(reverse("training_dashboard"), {"year": self.year})
        self.assertEqual(response.context["total_count"], 2)
        self.assertEqual(response.context["completed_count"], 1)
        self.assertEqual(response.context["completion_rate"], 50.0)

    def test_manager_can_search_name_and_see_filtered_status(self):
        self.completion.completion_code = "SEARCHED-CODE"
        self.completion.save()
        self._login(self.manager)
        response = self.client.get(
            reverse("training_dashboard"),
            {"year": self.year, "name": "길동"},
        )
        self.assertContains(response, "홍길동")
        self.assertNotContains(response, "김환경")
        self.assertEqual(response.context["total_count"], 1)
        self.assertEqual(response.context["completed_count"], 1)
