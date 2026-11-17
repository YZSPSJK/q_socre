from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .forms import (
    ActivityForm, RelationshipForm, ReportFilterForm, ScoreForm,
    TaskFilterForm, TemplateForm, TemplateItemForm, TemplateItems,
)
from .models import MULTIPLE_TYPES, Activity, ScoreTemplate, Task, TemplateItem
from .reports import department_results, progress_rows, result_rows, results_export, score_summary
from .services import assign_relationships, freeze_template, save_scores, score_limit, valid_tasks


def manager_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.can_manage_ratings:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


@login_required
def home(request):
    return redirect("activities" if request.user.can_manage_ratings else "my_tasks")


@manager_required
def activities(request):
    return render(request, "ratings/activities.html", {"activities": Activity.objects.select_related("template")})


@manager_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def edit_activity(request, pk=None):
    activity = None
    if pk is not None:
        qs = Activity.objects.select_for_update() if request.method == "POST" else Activity.objects.all()
        activity = get_object_or_404(qs, pk=pk)
    form = ActivityForm(request.POST if request.method == "POST" else None, instance=activity)
    if request.method == "POST" and form.is_valid():
        if activity and not form.cleaned_data["allow_self"] and activity.tasks.filter(
            active=True, reviewer_id=F("target_id")
        ).exists():
            form.add_error("allow_self", "请先取消现有自评关系，再关闭自评。")
        else:
            activity = form.save()
            messages.success(request, "活动配置已保存。")
            return redirect("activity_detail", pk=activity.id)
    return render(request, "ratings/edit_activity.html", {"form": form, "activity": activity})


@manager_required
def activity_detail(request, pk):
    activity = get_object_or_404(Activity.objects.select_related("template"), pk=pk)
    return render(request, "ratings/activity.html", {
        "activity": activity, "task_count": activity.tasks.filter(active=True).count(),
        "items": activity.items.all() if activity.activated_at else activity.template.items.all(),
    })


@manager_required
@require_POST
@transaction.atomic
def activity_action(request, pk):
    activity = get_object_or_404(Activity.objects.select_for_update(), pk=pk)
    action = request.POST.get("action")
    if action == "enable":
        if not activity.activated_at:
            ScoreTemplate.objects.select_for_update().get(pk=activity.template_id)
            if not freeze_template(activity):
                messages.error(request, "请配置至少一个评分项，且权重总和为 100%。")
                return redirect("activity_detail", pk=pk)
            activity.activated_at = timezone.now()
        activity.enabled = True
        activity.save(update_fields=["enabled", "activated_at"])
        messages.success(request, "评分活动已启用。")
    elif action == "disable":
        activity.enabled = False
        activity.save(update_fields=["enabled"])
        messages.success(request, "评分活动已停用。")
    elif action in ("open_results", "close_results"):
        activity.results_open = action == "open_results"
        activity.save(update_fields=["results_open"])
        messages.success(request, "员工结果查看开关已更新。")
    else:
        raise Http404
    return redirect("activity_detail", pk=pk)


@manager_required
def templates(request):
    return render(request, "ratings/templates.html", {"templates": ScoreTemplate.objects.prefetch_related("items")})


@manager_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def edit_template(request, pk=None):
    qs = ScoreTemplate.objects.select_for_update() if request.method == "POST" else ScoreTemplate.objects.all()
    template = get_object_or_404(qs, pk=pk) if pk is not None else ScoreTemplate()
    data = request.POST if request.method == "POST" else None
    form = TemplateForm(data, instance=template)
    initial_items = [TemplateItemForm.initial_data(item) for item in template.items.all()] if pk else []
    items = TemplateItems(data, prefix="items", initial=initial_items)
    if request.method == "POST":
        valid_form = form.is_valid()
        valid_items = items.is_valid()
        if valid_form and valid_items:
            form.save()
            template.items.all().delete()
            TemplateItem.objects.bulk_create([TemplateItem(template=template, **item) for item in items.item_data])
            messages.success(request, "评分模板已保存。")
            return redirect("templates")
    return render(request, "ratings/edit_template.html", {"form": form, "items": items, "score_template": template})


@manager_required
@require_POST
@transaction.atomic
def template_action(request, pk):
    template = get_object_or_404(ScoreTemplate.objects.select_for_update(), pk=pk)
    action = request.POST.get("action")
    if action == "delete":
        try:
            template.delete()
        except ProtectedError:
            messages.error(request, "模板已被活动使用，无法删除。")
        else:
            messages.success(request, "模板已删除。")
        return redirect("templates")
    if action != "copy":
        raise Http404
    base = template.name[:75]
    names = set(ScoreTemplate.objects.filter(name__startswith=base).values_list("name", flat=True))
    name = f"{base}（副本）"
    number = 2
    while name in names:
        name = f"{base}（副本 {number}）"
        number += 1
    copy = ScoreTemplate.objects.create(name=name)
    TemplateItem.objects.bulk_create([
        TemplateItem(template=copy, **item.configuration())
        for item in template.items.all()
    ])
    return redirect("edit_template", pk=copy.id)


@manager_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def relationships(request, pk):
    qs = Activity.objects.select_for_update() if request.method == "POST" else Activity.objects.all()
    activity = get_object_or_404(qs, pk=pk)
    form = RelationshipForm(request.POST if request.method == "POST" else None, activity=activity)
    if request.method == "POST" and form.is_valid():
        created, restored = assign_relationships(
            activity, list(form.cleaned_data["reviewers"]), list(form.cleaned_data["targets"]),
        )
        messages.success(request, f"新增 {created} 条评分关系，恢复 {restored} 条。")
        return redirect("relationships", pk=pk)
    tasks = activity.tasks.select_related("reviewer", "target").order_by(
        "-active", "reviewer__name", "target__name", "id",
    )
    page = Paginator(tasks, 50).get_page(request.GET.get("page"))
    return render(request, "ratings/relationships.html", {"activity": activity, "form": form, "page": page})


@manager_required
@require_POST
@transaction.atomic
def task_action(request, pk, task_id):
    activity = get_object_or_404(Activity.objects.select_for_update(), pk=pk)
    task = get_object_or_404(activity.tasks, pk=task_id)
    action = request.POST.get("action")
    if action == "cancel":
        task.active = False
        task.save(update_fields=["active", "updated_at"])
        messages.success(request, "已取消评分关系，原评分记录已保留。")
        return redirect("relationships", pk=pk)
    if action == "return":
        if not task.active or task.status != Task.Status.SUBMITTED:
            messages.error(request, "只有有效且已提交的任务可以退回。")
        else:
            task.status = Task.Status.RETURNED
            task.save(update_fields=["status", "updated_at"])
            messages.success(request, "评分已退回。原内容可作为重评的起点。")
        return redirect("review_task", pk=pk, task_id=task_id)
    raise Http404


@login_required
def my_tasks(request):
    form = TaskFilterForm(request.GET, user=request.user)
    all_tasks = Task.objects.filter(
        active=True, reviewer__user=request.user, activity__activated_at__isnull=False,
    )
    tasks = all_tasks.select_related("activity", "target")
    if form.is_valid():
        data = form.cleaned_data
        if data["activity"]:
            tasks = tasks.filter(activity=data["activity"])
        if data["name"]:
            tasks = tasks.filter(target__name__icontains=data["name"])
        if data["department"]:
            tasks = tasks.filter(target__department__icontains=data["department"])
        if data["status"]:
            tasks = tasks.filter(status=data["status"])
    tasks = list(tasks)
    submitted = sum(task.status == Task.Status.SUBMITTED for task in tasks)
    return render(request, "ratings/my_tasks.html", {
        "form": form, "tasks": tasks, "submitted": submitted, "pending": len(tasks) - submitted,
    })


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@transaction.atomic
def score_task(request, task_id):
    owned = Task.objects.filter(
        pk=task_id, reviewer__user=request.user, active=True, activity__activated_at__isnull=False,
    )
    if request.method == "POST":
        activity_id = get_object_or_404(owned.only("activity")).activity_id
        get_object_or_404(Activity.objects.select_for_update(), pk=activity_id)
    task = get_object_or_404(owned.select_related("activity", "target"), pk=task_id)
    return task_page(request, task)


@manager_required
@never_cache
def review_task(request, pk, task_id):
    task = get_object_or_404(
        Task.objects.select_related("activity", "reviewer", "target"), activity_id=pk, pk=task_id,
    )
    return task_page(request, task, manager=True)


def task_page(request, task, *, manager=False):
    activity = task.activity
    now = timezone.now()
    editable = not manager and activity.enabled and task.status != Task.Status.SUBMITTED
    can_submit = editable and activity.can_submit(now)
    items = list(activity.items.all())
    submitting = request.method == "POST" and request.POST.get("action") == "submit"
    data = request.POST if request.method == "POST" else None
    existing = {score.item_id: score.answer if score.answer is not None else score.value for score in task.scores.all()}
    form = ScoreForm(
        data, items=items, existing=existing, use_defaults=editable and task.status == Task.Status.PENDING,
        submitting=submitting,
    )
    if request.method == "POST":
        if task.status == Task.Status.SUBMITTED and submitting:
            messages.info(request, "该评分已提交。")
            return redirect("score_task", task_id=task.id)
        if not editable:
            raise PermissionDenied
        if request.POST.get("action") not in ("draft", "submit"):
            raise Http404
        if submitting and not can_submit:
            messages.error(request, "当前时间不在正式评分时段内。")
        elif form.is_valid():
            save_scores(task, form, submit=submitting, now=now)
            messages.success(request, "评分已提交。" if submitting else "草稿已保存。")
            return redirect("score_task", task_id=task.id)
    if not editable:
        for field in form.fields.values():
            field.disabled = True
    return render(request, "ratings/score.html", {
        "task": task, "form": form, "manager": manager, "editable": editable, "can_submit": can_submit,
    })


@manager_required
@never_cache
def progress(request, pk):
    activity = get_object_or_404(Activity, pk=pk)
    form = ReportFilterForm(request.GET, activity=activity, progress=True)
    rows, summary, pending_tasks = progress_rows(activity, form.cleaned_data if form.is_valid() else {})
    return render(request, "ratings/progress.html", {
        "activity": activity, "form": form, "rows": rows, "summary": summary,
        "page": Paginator(pending_tasks, 50).get_page(request.GET.get("page")),
    })


@manager_required
@never_cache
def results(request, pk):
    activity = get_object_or_404(Activity, pk=pk)
    items = list(activity.items.filter(weight__gt=0))
    form = ReportFilterForm(request.GET, activity=activity)
    valid = form.is_valid()
    rows = result_rows(activity, items, form.cleaned_data if valid else {})
    if request.GET.get("export") == "xlsx" and valid:
        return results_export(activity, items, rows)
    return render(request, "ratings/results.html", {
        "activity": activity, "form": form, "items": items, "rows": rows, "departments": department_results(rows),
    })


@login_required
@never_cache
def my_results(request):
    return render(request, "ratings/my_results.html", {"activities": open_results_for(request.user)})


def open_results_for(user):
    return Activity.objects.filter(
        results_open=True, tasks__target__user=user, tasks__active=True,
    ).exclude(visibility=Activity.Visibility.HIDDEN).distinct()


@login_required
@never_cache
def my_result(request, pk):
    activity = get_object_or_404(open_results_for(request.user), pk=pk)
    items = list(activity.items.all())
    show_details = activity.visibility == Activity.Visibility.DIMENSIONS
    tasks = list(valid_tasks(activity).filter(target__user=request.user).order_by("submitted_at", "id")
                 .select_related("reviewer").prefetch_related("scores"))
    scored_items = [item for item in items if item.scored]
    summary = score_summary(scored_items, tasks)
    reviews = []
    if show_details and activity.show_reviews:
        for task in tasks:
            answers = {score.item_id: score.answer if score.answer is not None else score.value for score in task.scores.all()}
            reviews.append({
                "name": None if activity.anonymous else task.reviewer.name,
                "total": task.total,
                "answers": [(item.name, display_answer(item, answers.get(item.id))) for item in items],
            })
    return render(request, "ratings/my_result.html", {
        "activity": activity, "total": summary["total"], "show_details": show_details,
        "count": summary["count"],
        "averages": [(item, score_limit(item), average) for item, average in zip(scored_items, summary["averages"])],
        "reviews": reviews,
    })


def display_answer(item, answer):
    if answer is None:
        return None
    if item.numeric:
        return f"{Decimal(answer):.{item.precision}f}"
    if item.choice:
        labels = {option["id"]: option["label"] for option in item.options}
        values = answer if item.field_type in MULTIPLE_TYPES else [answer]
        return "、".join(labels[value] for value in values)
    return answer
