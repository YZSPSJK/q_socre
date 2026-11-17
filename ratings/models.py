from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        EMPLOYEE = "employee", "员工"
        HR = "hr", "人事管理员"

    role = models.CharField("角色", max_length=12, choices=Role, default=Role.EMPLOYEE)
    employee_number = models.CharField("工号", max_length=32, unique=True, blank=True, null=True)
    department = models.CharField("部门", max_length=80, blank=True)
    position = models.CharField("岗位", max_length=80, blank=True)

    @property
    def display_name(self):
        return f"{self.last_name}{self.first_name}" or self.username

    @property
    def can_manage_ratings(self):
        return self.is_superuser or self.role == self.Role.HR

    def __str__(self):
        return f"{self.display_name}（{self.employee_number or self.username}）"


class ScoreTemplate(models.Model):
    name = models.CharField("模板名称", max_length=100, unique=True)
    comment_required = models.BooleanField("评语必填", default=False)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class ItemType(models.TextChoices):
    TEXT = "text", "文本"
    TEXTAREA = "textarea", "文本框"
    RADIO = "radio", "单选框"
    SELECT = "select", "下拉单选"
    MULTISELECT = "multiselect", "下拉多选"
    CHECKBOXES = "checkboxes", "复选框"
    NUMBER = "number", "数字"


CHOICE_TYPES = (ItemType.RADIO, ItemType.SELECT, ItemType.MULTISELECT, ItemType.CHECKBOXES)
MULTIPLE_TYPES = (ItemType.MULTISELECT, ItemType.CHECKBOXES)


class ScoreItem(models.Model):
    name = models.CharField("评分项", max_length=100)
    field_type = models.CharField("表单类型", max_length=12, choices=ItemType, default=ItemType.NUMBER)
    minimum = models.DecimalField("最小值", max_digits=11, decimal_places=6, default=0)
    maximum = models.DecimalField("最大值", max_digits=11, decimal_places=6, default=100)
    weight = models.DecimalField("权重（%）", max_digits=5, decimal_places=2)
    required = models.BooleanField("必填", default=True)
    precision = models.PositiveSmallIntegerField("小数位数", default=2)
    help_text = models.CharField("文字提示", max_length=300, blank=True)
    default_value = models.JSONField("默认值", null=True, blank=True)
    options = models.JSONField("选项", default=list, blank=True)
    sort_order = models.PositiveIntegerField("排序", default=0)

    class Meta:
        abstract = True
        ordering = ("sort_order", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(minimum__gte=0, maximum__gt=F("minimum")),
                name="%(app_label)s_%(class)s_valid_range",
            ),
            models.CheckConstraint(
                condition=Q(weight__gte=0, weight__lte=100),
                name="%(app_label)s_%(class)s_valid_weight",
            ),
        ]

    @property
    def numeric(self):
        return self.field_type == ItemType.NUMBER

    @property
    def scored(self):
        return self.weight > 0

    @property
    def choice(self):
        return self.field_type in CHOICE_TYPES

    def configuration(self):
        fields = (
            "name", "field_type", "minimum", "maximum", "weight", "required",
            "precision", "help_text", "default_value", "options", "sort_order",
        )
        return {field: getattr(self, field) for field in fields}


class TemplateItem(ScoreItem):
    template = models.ForeignKey(ScoreTemplate, on_delete=models.CASCADE, related_name="items")


class Activity(models.Model):
    class Visibility(models.TextChoices):
        HIDDEN = "hidden", "不可查看"
        TOTAL = "total", "仅看综合分"
        DIMENSIONS = "dimensions", "综合分及维度汇总"

    name = models.CharField("活动名称", max_length=120)
    year = models.PositiveSmallIntegerField("年度")
    quarter = models.PositiveSmallIntegerField(
        "季度", choices=[(number, f"第 {number} 季度") for number in range(1, 5)]
    )
    starts_at = models.DateTimeField("开始时间")
    ends_at = models.DateTimeField("截止时间")
    template = models.ForeignKey(ScoreTemplate, verbose_name="评分模板", on_delete=models.PROTECT)
    enabled = models.BooleanField("启用", default=False)
    activated_at = models.DateTimeField("首次启用时间", null=True, blank=True)
    comment_required = models.BooleanField(default=False)
    allow_self = models.BooleanField("允许自评", default=False)
    count_self = models.BooleanField("自评计入结果", default=False)
    results_open = models.BooleanField("开放评分结果", default=False)
    visibility = models.CharField(
        "员工结果查看范围", max_length=12, choices=Visibility, default=Visibility.HIDDEN
    )
    show_reviews = models.BooleanField("允许查看逐条评价", default=False)
    anonymous = models.BooleanField("逐条评价匿名", default=True)

    class Meta:
        ordering = ("-year", "-quarter", "-id")
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="activity_valid_dates"),
        ]

    def __str__(self):
        return self.name

    def can_submit(self, now=None):
        now = now or timezone.now()
        return self.enabled and self.starts_at <= now < self.ends_at

    @property
    def phase(self):
        if not self.activated_at:
            return "草稿"
        if not self.enabled:
            return "已停用"
        now = timezone.now()
        if now < self.starts_at:
            return "待开始"
        if now >= self.ends_at:
            return "已截止"
        return "评分中"


class ActivityItem(ScoreItem):
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="items")


class Participant(models.Model):
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    name = models.CharField(max_length=300)
    department = models.CharField(max_length=80, blank=True)
    position = models.CharField(max_length=80, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("activity", "user"), name="unique_activity_participant"),
        ]


class Task(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待评分"
        DRAFT = "draft", "草稿"
        SUBMITTED = "submitted", "已提交"
        RETURNED = "returned", "已退回"

    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="tasks")
    reviewer = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name="assigned_tasks")
    target = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name="received_tasks")
    active = models.BooleanField(default=True)
    status = models.CharField(max_length=12, choices=Status, default=Status.PENDING)
    comment = models.TextField("评语", blank=True, max_length=2000)
    total = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("activity", "target__name", "id")
        constraints = [
            models.UniqueConstraint(fields=("activity", "reviewer", "target"), name="unique_rating_task"),
        ]
        indexes = [models.Index(fields=("activity", "active", "status"), name="task_activity_status_idx")]


class Score(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="scores")
    item = models.ForeignKey(ActivityItem, on_delete=models.PROTECT)
    value = models.DecimalField(max_digits=14, decimal_places=6, null=True)
    answer = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("task", "item"), name="unique_task_score_item"),
        ]
