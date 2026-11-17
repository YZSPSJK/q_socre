import json
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from .models import Activity, ItemType, ScoreTemplate, Task, User
from .services import assign_relationships


class TemplateWeightTests(TestCase):
    def test_template_validates_weights_as_decimal_values(self):
        manager = User.objects.create_user(username="hr", role=User.Role.HR)
        self.client.force_login(manager)
        data = {
            "name": "季度评分",
            "items-TOTAL_FORMS": 2,
            "items-INITIAL_FORMS": 0,
            "items-0-name": "工作质量",
            "items-0-minimum": "1",
            "items-0-maximum": "10",
            "items-0-weight": "59.50",
            "items-0-required": "on",
            "items-1-name": "沟通协作",
            "items-1-minimum": "0",
            "items-1-maximum": "100",
            "items-1-weight": "40.25",
        }
        url = reverse("new_template")

        invalid = self.client.post(url, data)
        self.assertContains(invalid, "权重之和必须为 100%")
        self.assertFalse(ScoreTemplate.objects.exists())

        valid = self.client.post(url, {**data, "items-0-weight": "59.75"})
        self.assertRedirects(valid, reverse("templates"))
        template = ScoreTemplate.objects.get()
        self.assertEqual(sum(template.items.values_list("weight", flat=True)), 100)


class TemplateOrderTests(TestCase):
    def test_order_is_saved_and_copied_into_activity_snapshot(self):
        manager = User.objects.create_user(username="hr", role=User.Role.HR)
        self.client.force_login(manager)
        data = {"name": "顺序测试", "items-TOTAL_FORMS": 2, "items-INITIAL_FORMS": 0}
        for index, name in enumerate(("质量", "协作")):
            data.update({
                f"items-{index}-name": name,
                f"items-{index}-minimum": "0",
                f"items-{index}-maximum": "100",
                f"items-{index}-weight": "50",
                f"items-{index}-ORDER": str(2 - index),
            })
        self.assertRedirects(self.client.post(reverse("new_template"), data), reverse("templates"))
        template = ScoreTemplate.objects.get()
        self.assertEqual(list(template.items.values_list("name", "sort_order")), [("协作", 1), ("质量", 2)])

        self.client.post(reverse("template_action", args=[template.pk]), {"action": "copy"})
        copy = ScoreTemplate.objects.exclude(pk=template.pk).get()
        self.assertEqual(list(copy.items.values_list("name", flat=True)), ["协作", "质量"])

        now = timezone.now()
        activity = Activity.objects.create(
            name="顺序快照", year=now.year, quarter=1, starts_at=now, ends_at=now + timedelta(hours=1),
            template=template,
        )
        self.client.post(reverse("activity_action", args=[activity.pk]), {"action": "enable"})
        data.update({"items-INITIAL_FORMS": 2, "items-0-ORDER": "1", "items-1-ORDER": "2"})
        self.assertRedirects(self.client.post(reverse("edit_template", args=[template.pk]), data), reverse("templates"))
        self.assertEqual(list(template.items.values_list("name", flat=True)), ["质量", "协作"])
        self.assertEqual(list(activity.items.values_list("name", flat=True)), ["协作", "质量"])


class DynamicScoreFormTests(TestCase):
    def test_submission_validates_frozen_fields_and_keeps_unscored_answers(self):
        User.objects.bulk_create([
            User(username="hr", role=User.Role.HR), User(username="reviewer"), User(username="target"),
        ])
        people = User.objects.in_bulk(["hr", "reviewer", "target"], field_name="username")
        manager, reviewer, target = people["hr"], people["reviewer"], people["target"]
        self.client.force_login(manager)
        items = [
            {"name": "标题", "field_type": ItemType.TEXT, "default_value": "默认标题"},
            {"name": "反馈", "field_type": ItemType.TEXTAREA, "required": "on", "help_text": "请输入具体事例"},
            {"name": "单选", "field_type": ItemType.RADIO, "counts_for_score": "on", "weight": "20"},
            {"name": "下拉单选", "field_type": ItemType.SELECT},
            {"name": "下拉多选", "field_type": ItemType.MULTISELECT, "default_value": "良好\n优秀"},
            {"name": "复选框", "field_type": ItemType.CHECKBOXES, "counts_for_score": "on", "weight": "20"},
            {
                "name": "数字", "field_type": ItemType.NUMBER, "minimum": "0",
                "maximum": "10", "precision": "6", "weight": "60", "required": "on",
            },
        ]
        options = json.dumps([{"label": "良好", "score": "2"}, {"label": "优秀", "score": "4"}])
        for index in (2, 3, 4, 5):
            items[index]["options"] = options
        data = {
            "name": "组合表单",
            "items-TOTAL_FORMS": len(items),
            "items-INITIAL_FORMS": 0,
            **{f"items-{index}-{key}": value for index, item in enumerate(items) for key, value in item.items()},
        }
        self.assertRedirects(self.client.post(reverse("new_template"), data), reverse("templates"))
        now = timezone.now()
        activity = Activity.objects.create(
            name="评分活动", year=now.year, quarter=1, starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=1), template=ScoreTemplate.objects.get(),
        )
        assign_relationships(activity, [reviewer], [target])
        self.client.post(reverse("activity_action", args=[activity.pk]), {"action": "enable"})
        task = Task.objects.get(activity=activity)
        fields = {item.name: f"item_{item.pk}" for item in activity.items.all()}
        url = reverse("score_task", args=[task.pk])

        self.client.force_login(reviewer)
        form = self.client.get(url).context["form"]
        self.assertEqual(form[fields["标题"]].value(), "默认标题")
        self.assertEqual(form[fields["下拉多选"]].value(), ["1", "2"])
        self.assertRedirects(self.client.post(url, {"action": "draft"}), url)
        self.assertIsNone(self.client.get(url).context["form"][fields["标题"]].value())

        invalid = self.client.post(url, {"action": "submit", fields["数字"]: "10.0000001"})
        self.assertTrue(invalid.context["form"][fields["反馈"]].errors)
        self.assertTrue(invalid.context["form"][fields["数字"]].errors)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.DRAFT)

        valid = self.client.post(url, {
            "action": "submit", fields["反馈"]: "多行\n文本",
            fields["单选"]: "1", fields["数字"]: "5.000001", fields["复选框"]: ["1", "1"],
        })
        self.assertRedirects(valid, url)
        task.refresh_from_db()
        self.assertEqual(task.total, Decimal("46.67"))
        scores = {score.item.name: score for score in task.scores.select_related("item")}
        self.assertEqual(scores["数字"].value, Decimal("5.000001"))
        self.assertEqual(scores["反馈"].answer, "多行\n文本")
        self.assertIsNone(scores["反馈"].value)
        self.assertEqual(scores["复选框"].answer, ["1"])
        self.assertEqual(scores["复选框"].value, Decimal("2"))

        self.client.force_login(manager)
        report = self.client.get(reverse("results", args=[activity.pk]), {"export": "xlsx"})
        workbook = load_workbook(BytesIO(report.content), read_only=True)
        headers, values = list(workbook.active.values)
        workbook.close()
        self.assertEqual(headers[8:], ("单选", "复选框", "数字"))
        self.assertEqual(values[7:], (46.67, 2, 2, 5))

        Activity.objects.filter(pk=activity.pk).update(
            results_open=True, visibility=Activity.Visibility.DIMENSIONS, show_reviews=True, anonymous=True,
        )
        self.client.force_login(target)
        result = self.client.get(reverse("my_result", args=[activity.pk]))
        self.assertContains(result, "多行<br>文本")
        self.assertContains(result, "复选框</strong>：良好")
        self.assertContains(result, "匿名")
