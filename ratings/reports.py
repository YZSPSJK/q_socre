from collections import defaultdict
from io import BytesIO

from django.db.models import Count, Q
from django.http import HttpResponse
from openpyxl import Workbook

from .models import Task
from .services import PERCENT, ZERO, round_score, valid_tasks


def filter_person(queryset, relation, filters):
    name = filters.get("name")
    if name:
        queryset = queryset.filter(
            Q(**{f"{relation}__name__icontains": name})
            | Q(**{f"{relation}__user__employee_number__icontains": name})
        )
    department = filters.get("department")
    if department:
        queryset = queryset.filter(**{f"{relation}__department": department})
    return queryset


def progress_rows(activity, filters):
    tasks = filter_person(activity.tasks.filter(active=True, reviewer__user__is_active=True), "reviewer", filters)
    rows = list(tasks.order_by().values(
        "reviewer_id", "reviewer__name", "reviewer__department", "reviewer__position",
    ).annotate(
        expected=Count("id"), submitted=Count("id", filter=Q(status=Task.Status.SUBMITTED)),
    ).order_by("reviewer__department", "reviewer__name", "reviewer_id"))
    for row in rows:
        row["pending"] = row["expected"] - row["submitted"]
        row["rate"] = round_score(PERCENT * row["submitted"] / row["expected"])
    expected = sum(row["expected"] for row in rows)
    submitted = sum(row["submitted"] for row in rows)
    summary = {
        "reviewers": len(rows), "expected": expected, "submitted": submitted, "pending": expected - submitted,
        "rate": round_score(PERCENT * submitted / expected) if expected else ZERO,
    }
    pending_tasks = tasks.exclude(status=Task.Status.SUBMITTED).select_related("reviewer", "target").order_by(
        "reviewer__department", "reviewer__name", "target__name", "id",
    )
    return rows, summary, pending_tasks


def score_summary(items, tasks):
    tasks = list(tasks)
    if not tasks:
        return {"count": 0, "total": None, "averages": [None for item in items]}
    item_sums = defaultdict(lambda: ZERO)
    for task in tasks:
        for score in task.scores.all():
            if score.value is not None:
                item_sums[score.item_id] += score.value
    count = len(tasks)
    return {
        "count": count,
        "total": round_score(sum(task.total for task in tasks) / count),
        "averages": [round_score(item_sums[item.id] / count) for item in items],
    }


def result_rows(activity, items, filters):
    targets = filter_person(activity.tasks.filter(active=True), "target", filters)
    people = targets.order_by("target__department", "target__name", "target_id").values(
        "target_id", "target__name", "target__department", "target__position",
    ).distinct()
    reviews_by_target = defaultdict(list)
    tasks = filter_person(valid_tasks(activity), "target", filters).prefetch_related("scores")
    for task in tasks:
        reviews_by_target[task.target_id].append(task)
    rows = [
        {**person, **score_summary(items, reviews_by_target[person["target_id"]])}
        for person in people
    ]
    sort = filters.get("sort")
    if sort in ("highest", "lowest"):
        rows.sort(key=lambda row: (
            row["total"] is None, (row["total"] or ZERO) * (-1 if sort == "highest" else 1),
        ))
    return rows


def department_results(rows):
    departments = defaultdict(list)
    for row in rows:
        departments[row["target__department"]].append(row["total"])
    results = []
    for department, totals in sorted(departments.items()):
        scores = [total for total in totals if total is not None]
        results.append({
            "name": department, "participants": len(totals), "scored": len(scores),
            "total": round_score(sum(scores) / len(scores)) if scores else None,
        })
    return results


def results_export(activity, items, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工评分汇总"
    sheet.append(["评分活动", "年度", "季度", "员工", "部门", "岗位", "有效评价数", "综合分", *(item.name for item in items)])
    for row in rows:
        sheet.append([
            activity.name, activity.year, activity.quarter, row["target__name"], row["target__department"],
            row["target__position"], row["count"], row["total"], *row["averages"],
        ])
    for row in sheet:
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = "s"
            elif cell.row > 1 and cell.column >= 8:
                cell.number_format = "0.00"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    data = BytesIO()
    workbook.save(data)
    response = HttpResponse(
        data.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="qscore-activity-{activity.id}.xlsx"'
    return response
