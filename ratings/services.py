from decimal import Decimal, ROUND_HALF_UP

from django.db.models import F

from .models import MULTIPLE_TYPES, ActivityItem, Participant, Score, Task


ZERO = Decimal("0")
PERCENT = Decimal("100")


def round_score(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def freeze_template(activity):
    items = list(activity.template.items.all())
    if not items or sum(item.weight for item in items) != PERCENT:
        return False
    ActivityItem.objects.bulk_create([
        ActivityItem(activity=activity, **item.configuration())
        for item in items
    ])
    return True


def assign_relationships(activity, reviewers, targets):
    people = {user.pk: user for user in [*reviewers, *targets]}
    participants = {
        person.user_id: person
        for person in activity.participants.filter(user_id__in=people).order_by()
    }
    Participant.objects.bulk_create([
        Participant(
            activity=activity, user=user, name=user.display_name,
            department=user.department, position=user.position,
        )
        for user in people.values() if user.pk not in participants
    ])
    participants = {
        person.user_id: person.id
        for person in activity.participants.filter(user_id__in=people).order_by()
    }
    reviewer_ids = [participants[user.id] for user in reviewers]
    target_ids = [participants[user.id] for user in targets]
    existing = {
        (task.reviewer_id, task.target_id): task
        for task in activity.tasks.filter(reviewer_id__in=reviewer_ids, target_id__in=target_ids).order_by()
    }
    additions = []
    reactivated = []
    for reviewer_id in reviewer_ids:
        for target_id in target_ids:
            task = existing.get((reviewer_id, target_id))
            if task is None:
                additions.append(Task(activity=activity, reviewer_id=reviewer_id, target_id=target_id))
            elif not task.active:
                task.active = True
                reactivated.append(task)
    Task.objects.bulk_create(additions)
    Task.objects.bulk_update(reactivated, ["active"])
    return len(additions), len(reactivated)


def sum_weighted(items, values):
    return round_score(sum(
        ((values.get(item.id) or ZERO) / score_limit(item) * item.weight for item in items if item.scored), ZERO
    ))


def score_limit(item):
    if item.numeric:
        return item.maximum
    points = [Decimal(option["score"]) for option in item.options]
    return sum(points, ZERO) if item.field_type in MULTIPLE_TYPES else max(points)


def save_scores(task, form, *, submit, now):
    answers = form.values
    scores = []
    values = {}
    for item in form.items:
        answer = answers[item.id]
        if answer is None or answer == "" or answer == []:
            continue
        if item.field_type in MULTIPLE_TYPES:
            answer = list(dict.fromkeys(answer))
        value = None
        if item.numeric:
            value = answer
            answer = format(answer, "f")
        elif item.scored:
            points = {option["id"]: Decimal(option["score"]) for option in item.options}
            value = sum((points[option] for option in answer), ZERO) if item.field_type in MULTIPLE_TYPES else points[answer]
        scores.append(Score(task=task, item=item, answer=answer, value=value))
        values[item.id] = value
    task.scores.all().delete()
    Score.objects.bulk_create(scores)
    task.status = Task.Status.SUBMITTED if submit else Task.Status.DRAFT
    task.total = sum_weighted(form.items, values) if submit else None
    task.submitted_at = now if submit else None
    task.save(update_fields=["status", "total", "submitted_at", "updated_at"])


def valid_tasks(activity):
    tasks = activity.tasks.filter(active=True, status=Task.Status.SUBMITTED, total__isnull=False)
    if not activity.count_self:
        tasks = tasks.exclude(reviewer_id=F("target_id"))
    return tasks
