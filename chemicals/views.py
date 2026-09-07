import csv
from datetime import date, datetime
from urllib.parse import urlsplit
from zipfile import BadZipFile

from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from .forms import CompletionCodeForm, TrainingStatusUploadForm, TrainingUploadForm
from .models import CompletionSubmissionLog, HandlerProfile, NicsNotice, TrainingCompletion
from .utils import crawl_nics_notices
from django.contrib import messages

@login_required
def chemical_check(request):
    # 연동할 외부 URL (예: 화학물질안전원 또는 자체 법령 시스템)
    external_url = "https://www.safetydata.go.kr/" # 실제 필요한 URL로 교체하세요
    return render(request, 'chemicals/external_viewer.html', {'external_url': external_url})

def nics_notice_list(request):
    # DB에 저장된 고시 목록을 가져옴 (최신순)
    notices = NicsNotice.objects.all()
    return render(request, 'chemicals/nics_list.html', {'notices': notices})

def nics_notice_list(request):
    # 'update' 파라미터가 들어오면 크롤링 실행
    if 'update' in request.GET:
        count = crawl_nics_notices()
        messages.success(request, f"{count}건의 새로운 고시가 업데이트되었습니다.")
        return redirect('nics_notice_list')

    notices = NicsNotice.objects.all().order_by('-reg_date')
    return render(request, 'chemicals/nics_list.html', {'notices': notices})


MANAGE_PERMISSION = "chemicals.change_trainingcompletion"
UPDATE_HEADERS = (
    "연도",
    "knoxid",
    "이름",
    "부서",
    "온라인교육 수료코드",
    "오프라인교육 신청일자",
    "오프라인교육 수료일자",
)
KEEP = object()


def _user_knoxid(user):
    attribute_path = getattr(settings, "HANDLER_TRAINING_KNOXID_ATTRIBUTE", "username")
    value = user
    for attribute in attribute_path.split("."):
        value = getattr(value, attribute, None)
        if value is None:
            return ""
    return str(value).strip()


def _configured_training_url(setting_name):
    value = str(getattr(settings, setting_name, "") or "").strip()
    parsed = urlsplit(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _year_from_request(request):
    try:
        year = int(request.GET.get("year", date.today().year))
    except (TypeError, ValueError):
        return date.today().year
    return year if 2000 <= year <= 2100 else date.today().year


def _filtered_completions(request, target_year):
    completions = TrainingCompletion.objects.select_related("handler").filter(
        target_year=target_year,
        handler__is_active=True,
    )
    department = request.GET.get("department", "").strip()
    if department:
        completions = completions.filter(handler__department=department)
    query = request.GET.get("query", request.GET.get("name", "")).strip()
    if query:
        completions = completions.filter(
            Q(handler__name__icontains=query) | Q(handler__knoxid__icontains=query)
        )
    status = request.GET.get("status")
    if status == "completed":
        completions = completions.filter(is_completed=True)
    elif status == "pending":
        completions = completions.filter(is_completed=False)
    return completions


@login_required
def training_dashboard(request):
    target = "training_manage" if request.user.has_perm(MANAGE_PERMISSION) else "training_status"
    return redirect(f"{reverse(target)}?year={_year_from_request(request)}")


@login_required
def training_status(request):
    target_year = _year_from_request(request)
    viewer_knoxid = _user_knoxid(request.user)
    completion = TrainingCompletion.objects.select_related("handler").filter(
        target_year=target_year,
        handler__is_active=True,
        handler__knoxid=viewer_knoxid,
    ).first() if viewer_knoxid else None
    years = set(
        TrainingCompletion.objects.filter(handler__knoxid=viewer_knoxid).values_list(
            "target_year", flat=True
        )
    ) if viewer_knoxid else set()
    years.add(date.today().year)
    return render(
        request,
        "chemicals/training_status.html",
        {
            "target_year": target_year,
            "years": sorted(years, reverse=True),
            "viewer_knoxid": viewer_knoxid,
            "completion": completion,
            "online_training_url": _configured_training_url("HANDLER_TRAINING_ONLINE_URL"),
            "offline_training_url": _configured_training_url("HANDLER_TRAINING_OFFLINE_URL"),
        },
    )


@login_required
@permission_required(MANAGE_PERMISSION, raise_exception=True)
def training_manage(request):
    target_year = _year_from_request(request)
    base_completions = _filtered_completions(request, target_year)

    selected_department = request.GET.get("department", "").strip()
    selected_query = request.GET.get("query", request.GET.get("name", "")).strip()
    selected_status = request.GET.get("status", "")

    total_count = base_completions.count()
    completed_count = base_completions.filter(is_completed=True).count()
    pending_count = total_count - completed_count
    completion_rate = round(completed_count * 100 / total_count, 1) if total_count else 0

    all_years = set(TrainingCompletion.objects.values_list("target_year", flat=True).distinct())
    all_years.add(date.today().year)

    departments = list(
        TrainingCompletion.objects.filter(target_year=target_year, handler__is_active=True)
        .exclude(handler__department="")
        .values_list("handler__department", flat=True)
        .distinct()
        .order_by("handler__department")
    )
    department_stats = list(
        base_completions.values("handler__department")
        .annotate(
            total=Count("id"),
            completed=Count("id", filter=Q(is_completed=True)),
        )
        .order_by("handler__department")
    )
    for stat in department_stats:
        stat["rate"] = round(stat["completed"] * 100 / stat["total"], 1)

    context = {
        "can_manage": True,
        "target_year": target_year,
        "years": sorted(all_years, reverse=True),
        "departments": departments,
        "department_stats": department_stats,
        "selected_department": selected_department,
        "selected_query": selected_query,
        "selected_status": selected_status,
        "total_count": total_count,
        "completed_count": completed_count,
        "pending_count": pending_count,
        "completion_rate": completion_rate,
        "completions": Paginator(base_completions, 50).get_page(request.GET.get("page")),
    }
    return render(request, "chemicals/training_dashboard.html", context)


@login_required
@require_POST
def training_submit(request, completion_id):
    completions = TrainingCompletion.objects.select_related("handler").filter(
        handler__is_active=True
    )
    can_manage = request.user.has_perm(MANAGE_PERMISSION)
    if not can_manage:
        completions = completions.filter(handler__knoxid=_user_knoxid(request.user))
    completion = get_object_or_404(completions, id=completion_id)
    form = CompletionCodeForm(request.POST)
    if form.is_valid():
        code = form.cleaned_data["completion_code"]
        with transaction.atomic():
            completion.online_completion_code = code
            completion.save(update_fields=["online_completion_code", "updated_at"])
            CompletionSubmissionLog.objects.create(
                completion=completion,
                submitted_by=request.user,
                completion_code=code,
            )
        messages.success(request, "온라인교육 수료코드가 등록되었습니다.")
    else:
        messages.error(request, "수료코드를 입력해 주세요.")
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        target = "training_manage" if can_manage else "training_status"
        next_url = f"{reverse(target)}?year={completion.target_year}"
    return redirect(next_url)


def _excel_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


@login_required
@permission_required(MANAGE_PERMISSION, raise_exception=True)
def training_upload(request):
    form = TrainingUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            workbook = load_workbook(
                form.cleaned_data["excel_file"], read_only=True, data_only=True
            )
            sheet = workbook.active
            header_row = next(sheet.iter_rows(values_only=True), ())
            headers = {_excel_text(value): index for index, value in enumerate(header_row)}
            required_headers = ("knoxid", "이름", "부서")
            missing_headers = [header for header in required_headers if header not in headers]
            if missing_headers:
                form.add_error(
                    "excel_file",
                    f"필수 열이 없습니다: {', '.join(missing_headers)}",
                )
            else:
                rows = []
                seen_knoxids = set()
                errors = []
                for row_number, row in enumerate(
                    sheet.iter_rows(min_row=2, values_only=True), start=2
                ):
                    values = {
                        header: _excel_text(row[headers[header]])
                        if headers[header] < len(row)
                        else ""
                        for header in required_headers
                    }
                    if not any(values.values()):
                        continue
                    empty_fields = [header for header, value in values.items() if not value]
                    if empty_fields:
                        errors.append(f"{row_number}행: {', '.join(empty_fields)} 값이 비어 있습니다.")
                    elif values["knoxid"] in seen_knoxids:
                        errors.append(f"{row_number}행: knoxid가 파일 안에서 중복됩니다.")
                    else:
                        seen_knoxids.add(values["knoxid"])
                        rows.append(values)

                if errors:
                    shown_errors = errors[:10]
                    if len(errors) > 10:
                        shown_errors.append(f"그 외 {len(errors) - 10}건")
                    form.add_error("excel_file", " ".join(shown_errors))
                elif not rows:
                    form.add_error("excel_file", "등록할 대상자 데이터가 없습니다.")
                else:
                    with transaction.atomic():
                        for row in rows:
                            handler, _ = HandlerProfile.objects.update_or_create(
                                knoxid=row["knoxid"],
                                defaults={
                                    "name": row["이름"],
                                    "department": row["부서"],
                                    "is_active": True,
                                },
                            )
                            TrainingCompletion.objects.get_or_create(
                                handler=handler,
                                target_year=form.cleaned_data["target_year"],
                            )
                    messages.success(
                        request,
                        f"{form.cleaned_data['target_year']}년 대상자 {len(rows)}명을 갱신했습니다.",
                    )
                    return redirect(
                        f"{reverse('training_manage')}?year={form.cleaned_data['target_year']}"
                    )
        except (BadZipFile, InvalidFileException, OSError, ValueError, StopIteration):
            form.add_error("excel_file", "엑셀 파일을 읽을 수 없습니다.")
        finally:
            if "workbook" in locals():
                workbook.close()

    return render(request, "chemicals/training_upload.html", {"form": form})


def _parse_year(value):
    if isinstance(value, bool):
        raise ValueError("4자리 연도를 입력해 주세요.")
    if isinstance(value, (int, float)) and int(value) == value:
        year = int(value)
    else:
        text = _excel_text(value)
        if not text.isdigit():
            raise ValueError("4자리 연도를 입력해 주세요.")
        year = int(text)
    if not 2000 <= year <= 2100:
        raise ValueError("연도는 2000~2100 범위여야 합니다.")
    return year


def _parse_date(value):
    if value is None or _excel_text(value) == "":
        return KEEP
    if _excel_text(value) == "__CLEAR__":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(_excel_text(value))
    except ValueError as exc:
        raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.") from exc


def _parse_code(value):
    text = _excel_text(value)
    if not text:
        return KEEP
    if text == "__CLEAR__":
        return ""
    if len(text) > 500:
        raise ValueError("수료코드는 500자 이하여야 합니다.")
    return text


@login_required
@permission_required(MANAGE_PERMISSION, raise_exception=True)
def training_excel_template(request):
    target_year = _year_from_request(request)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "수료현황 업데이트"
    sheet.append(UPDATE_HEADERS)
    for completion in _filtered_completions(request, target_year):
        sheet.append(
            (
                completion.target_year,
                completion.handler.knoxid,
                completion.handler.name,
                completion.handler.department,
                completion.online_completion_code,
                completion.offline_application_date,
                completion.offline_completion_date,
            )
        )
        sheet.cell(sheet.max_row, 5).number_format = "@"
        for column in (6, 7):
            sheet.cell(sheet.max_row, column).number_format = "yyyy-mm-dd"
    guide = workbook.create_sheet("안내")
    guide.append(("항목", "내용"))
    guide.append(("빈 셀", "기존 값을 유지합니다."))
    guide.append(("값 삭제", "수정할 셀에 __CLEAR__를 입력합니다."))
    guide.append(("날짜", "YYYY-MM-DD 또는 Excel 날짜 형식을 사용합니다."))
    guide.append(("식별자", "연도와 knoxid는 변경하지 않습니다."))
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="handler_training_update_{target_year}_{date.today():%Y%m%d}.xlsx"'
    )
    workbook.save(response)
    workbook.close()
    return response


@login_required
@permission_required(MANAGE_PERMISSION, raise_exception=True)
def training_status_upload(request):
    form = TrainingStatusUploadForm(request.POST or None, request.FILES or None)
    upload_errors = []
    if request.method == "POST" and form.is_valid():
        workbook = None
        try:
            workbook = load_workbook(form.cleaned_data["excel_file"], read_only=True, data_only=False)
            sheet = workbook.active
            header_cells = next(sheet.iter_rows(min_row=1, max_row=1), ())
            headers = [_excel_text(cell.value) for cell in header_cells]
            while headers and not headers[-1]:
                headers.pop()
            nonempty_headers = [header for header in headers if header]
            duplicates = sorted({header for header in nonempty_headers if nonempty_headers.count(header) > 1})
            unknown = sorted(set(nonempty_headers) - set(UPDATE_HEADERS))
            missing = [header for header in ("연도", "knoxid") if header not in nonempty_headers]
            if duplicates:
                upload_errors.append(f"1행: 중복 헤더가 있습니다: {', '.join(duplicates)}")
            if unknown:
                upload_errors.append(f"1행: 알 수 없는 헤더가 있습니다: {', '.join(unknown)}")
            if missing:
                upload_errors.append(f"1행: 필수 헤더가 없습니다: {', '.join(missing)}")

            parsed_rows = []
            seen_keys = set()
            max_rows = getattr(settings, "HANDLER_TRAINING_UPLOAD_MAX_ROWS", 5000)
            if not upload_errors:
                header_map = {header: index for index, header in enumerate(headers) if header}
                for row_number, cells in enumerate(sheet.iter_rows(min_row=2), start=2):
                    values = {
                        header: cells[index].value if index < len(cells) else None
                        for header, index in header_map.items()
                    }
                    if not any(value not in (None, "") for value in values.values()):
                        continue
                    if len(parsed_rows) >= max_rows:
                        upload_errors.append(f"{row_number}행: 최대 {max_rows}행까지 업로드할 수 있습니다.")
                        break
                    formula_fields = [
                        header for header, index in header_map.items()
                        if index < len(cells) and cells[index].data_type == "f"
                    ]
                    if formula_fields:
                        upload_errors.append(
                            f"{row_number}행: 수식 셀은 허용되지 않습니다: {', '.join(formula_fields)}"
                        )
                        continue
                    try:
                        year = _parse_year(values.get("연도"))
                        knoxid = _excel_text(values.get("knoxid"))
                        if not knoxid or knoxid == "__CLEAR__":
                            raise ValueError("knoxid를 입력해 주세요.")
                        key = (year, knoxid)
                        if key in seen_keys:
                            raise ValueError("같은 연도와 knoxid가 파일 안에서 중복됩니다.")
                        seen_keys.add(key)
                        parsed_rows.append(
                            {
                                "row_number": row_number,
                                "year": year,
                                "knoxid": knoxid,
                                "name": _excel_text(values.get("이름")),
                                "department": _excel_text(values.get("부서")),
                                "online_completion_code": _parse_code(values.get("온라인교육 수료코드")),
                                "offline_application_date": _parse_date(values.get("오프라인교육 신청일자")),
                                "offline_completion_date": _parse_date(values.get("오프라인교육 수료일자")),
                            }
                        )
                    except ValueError as exc:
                        upload_errors.append(f"{row_number}행: {exc}")

            if not parsed_rows and not upload_errors:
                upload_errors.append("업데이트할 데이터가 없습니다.")

            target_map = {
                (item.target_year, item.handler.knoxid): item
                for item in TrainingCompletion.objects.select_related("handler").filter(
                    target_year__in={row["year"] for row in parsed_rows},
                    handler__knoxid__in={row["knoxid"] for row in parsed_rows},
                    handler__is_active=True,
                )
            }
            changes = []
            warnings = []
            for row in parsed_rows:
                completion = target_map.get((row["year"], row["knoxid"]))
                if not completion:
                    upload_errors.append(
                        f"{row['row_number']}행: 해당 연도와 knoxid의 교육 대상자가 없습니다."
                    )
                    continue
                if row["name"] and row["name"] != completion.handler.name:
                    warnings.append(f"{row['row_number']}행: 이름이 현재 대상자 정보와 다릅니다.")
                if row["department"] and row["department"] != completion.handler.department:
                    warnings.append(f"{row['row_number']}행: 부서가 현재 대상자 정보와 다릅니다.")

                updates = {}
                for field in (
                    "online_completion_code",
                    "offline_application_date",
                    "offline_completion_date",
                ):
                    value = row[field]
                    if value is not KEEP and getattr(completion, field) != value:
                        updates[field] = value
                application_date = updates.get(
                    "offline_application_date", completion.offline_application_date
                )
                completion_date = updates.get(
                    "offline_completion_date", completion.offline_completion_date
                )
                if application_date and completion_date and completion_date < application_date:
                    upload_errors.append(
                        f"{row['row_number']}행: 오프라인 수료일자는 신청일자보다 빠를 수 없습니다."
                    )
                    continue
                changes.append((completion, updates))

            if not upload_errors:
                changed_count = 0
                skipped_count = 0
                with transaction.atomic():
                    for completion, updates in changes:
                        if not updates:
                            skipped_count += 1
                            continue
                        for field, value in updates.items():
                            setattr(completion, field, value)
                        completion.save(update_fields=[*updates, "updated_at"])
                        if "online_completion_code" in updates:
                            CompletionSubmissionLog.objects.create(
                                completion=completion,
                                submitted_by=request.user,
                                completion_code=completion.online_completion_code,
                            )
                        changed_count += 1
                messages.success(
                    request,
                    f"총 {len(parsed_rows)}행 중 {changed_count}행을 변경하고 {skipped_count}행을 건너뛰었습니다.",
                )
                if warnings:
                    messages.warning(request, " ".join(warnings[:20]))
                years = {row["year"] for row in parsed_rows}
                suffix = f"?year={next(iter(years))}" if len(years) == 1 else ""
                return redirect(f"{reverse('training_manage')}{suffix}")
        except (BadZipFile, InvalidFileException, OSError, ValueError, StopIteration):
            form.add_error("excel_file", "엑셀 파일을 읽을 수 없습니다.")
        except Exception:
            form.add_error("excel_file", "업로드 처리 중 오류가 발생했습니다. 파일을 확인해 주세요.")
        finally:
            if workbook:
                workbook.close()
    return render(
        request,
        "chemicals/training_status_upload.html",
        {"form": form, "upload_errors": upload_errors},
    )


def _csv_safe(value):
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


@login_required
@permission_required(MANAGE_PERMISSION, raise_exception=True)
def training_export_csv(request):
    target_year = _year_from_request(request)
    completions = _filtered_completions(request, target_year)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response.write("\ufeff")
    response["Content-Disposition"] = (
        f'attachment; filename="handler_training_{target_year}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "대상 연도",
            "knoxid",
            "이름",
            "부서",
            "최종 수료 상태",
            "온라인교육 수료코드",
            "온라인교육 수료 처리 시각",
            "오프라인교육 신청일자",
            "오프라인교육 수료일자",
        ]
    )
    for completion in completions:
        writer.writerow(
            [
                completion.target_year,
                _csv_safe(completion.handler.knoxid),
                _csv_safe(completion.handler.name),
                _csv_safe(completion.handler.department),
                "수료" if completion.is_completed else "미수료",
                _csv_safe(completion.online_completion_code),
                timezone.localtime(completion.online_completed_at).strftime("%Y-%m-%d %H:%M")
                if completion.online_completed_at
                else "",
                completion.offline_application_date or "",
                completion.offline_completion_date or "",
            ]
        )
    return response


@login_required
def worker_training(request):
    return render(request, "chemicals/worker_training.html")
