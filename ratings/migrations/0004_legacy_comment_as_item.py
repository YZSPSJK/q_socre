from collections import defaultdict

from django.db import migrations


def add_comment_items(Item, parent_field, parents, alias):
    items = Item.objects.using(alias)
    names = defaultdict(set)
    for parent_id, name in list(items.values_list(f"{parent_field}_id", "name")):
        names[parent_id].add(name.casefold())
    new_items = []
    for parent_id, required in parents:
        name = "评语"
        index = 2
        while name.casefold() in names[parent_id]:
            name = f"评语（{index}）"
            index += 1
        new_items.append(Item(
            **{f"{parent_field}_id": parent_id},
            name=name, field_type="textarea", required=required, weight=0,
        ))
    items.bulk_create(new_items)


def migrate_comments(apps, schema_editor):
    alias = schema_editor.connection.alias
    Template = apps.get_model("ratings", "ScoreTemplate")
    Activity = apps.get_model("ratings", "Activity")
    TemplateItem = apps.get_model("ratings", "TemplateItem")
    ActivityItem = apps.get_model("ratings", "ActivityItem")
    Task = apps.get_model("ratings", "Task")
    Score = apps.get_model("ratings", "Score")

    templates = list(Template.objects.using(alias).values_list("id", "comment_required"))
    activities = list(Activity.objects.using(alias).filter(
        activated_at__isnull=False,
    ).values_list("id", "comment_required"))
    add_comment_items(TemplateItem, "template", templates, alias)
    add_comment_items(ActivityItem, "activity", activities, alias)
    item_ids = dict(ActivityItem.objects.using(alias).filter(
        field_type="textarea",
    ).values_list("activity_id", "id"))
    comments = list(Task.objects.using(alias).filter(
        activity_id__in=item_ids,
    ).exclude(comment="").values_list("id", "activity_id", "comment"))
    Score.objects.using(alias).bulk_create([
        Score(task_id=task_id, item_id=item_ids[activity_id], answer=comment)
        for task_id, activity_id, comment in comments
    ])


class Migration(migrations.Migration):
    dependencies = [("ratings", "0003_dynamic_score_fields")]

    operations = [migrations.RunPython(migrate_comments, atomic=True)]
