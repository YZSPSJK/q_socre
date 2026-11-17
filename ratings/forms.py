import json
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseFormSet, formset_factory
from django.utils import timezone

from .models import CHOICE_TYPES, MULTIPLE_TYPES, Activity, ItemType, ScoreTemplate, Task, User
from .services import score_limit


class ActivityForm(forms.ModelForm):
    year = forms.IntegerField(label="年度", min_value=1, max_value=9999)

    class Meta:
        model = Activity
        fields = (
            "name", "year", "quarter", "template", "starts_at", "ends_at",
            "allow_self", "count_self", "visibility", "show_reviews", "anonymous",
        )
        widgets = {
            "starts_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].disabled = bool(self.instance.activated_at)
        self.fields["show_reviews"].help_text = "员工可查看维度汇总时生效。"
        self.fields["anonymous"].help_text = "只影响员工看到的逐条评价。"
        self.fields["count_self"].help_text = "关闭后，仍可完成自评任务，得分仅保留在评分记录中。"

    def clean(self):
        data = super().clean()
        start = data.get("starts_at")
        end = data.get("ends_at")
        if start and end and end <= start:
            self.add_error("ends_at", "截止时间必须晚于开始时间。")
        if not data.get("allow_self"):
            data["count_self"] = False
        if data.get("visibility") != Activity.Visibility.DIMENSIONS:
            data["show_reviews"] = False
        return data


class TemplateForm(forms.ModelForm):
    class Meta:
        model = ScoreTemplate
        fields = ("name",)


class TemplateItemForm(forms.Form):
    name = forms.CharField(label="评分项", max_length=100)
    field_type = forms.ChoiceField(label="表单类型", choices=ItemType.choices, initial=ItemType.NUMBER, required=False)
    help_text = forms.CharField(label="文字提示", max_length=300, required=False)
    default_value = forms.CharField(
        label="默认值", max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 2}),
    )
    minimum = forms.DecimalField(
        label="最小值", max_digits=11, decimal_places=6, min_value=0, initial=0, required=False,
    )
    maximum = forms.DecimalField(
        label="最大值", max_digits=11, decimal_places=6, initial=100, required=False,
    )
    weight = forms.DecimalField(
        label="权重（%）", max_digits=5, decimal_places=2, min_value=Decimal("0.01"), max_value=100,
        required=False,
    )
    precision = forms.IntegerField(label="小数位数", min_value=0, max_value=6, initial=2, required=False)
    counts_for_score = forms.BooleanField(label="参与计分", required=False)
    options = forms.JSONField(label="选项", required=False, widget=forms.HiddenInput)
    required = forms.BooleanField(label="必填", initial=True, required=False)

    @staticmethod
    def initial_data(item):
        data = item.configuration()
        data["counts_for_score"] = item.scored
        value = item.default_value
        if item.field_type in CHOICE_TYPES and value is not None:
            labels = {option["id"]: option["label"] for option in item.options}
            values = value if item.field_type in MULTIPLE_TYPES else [value]
            value = "\n".join(labels[option_id] for option_id in values)
        data["default_value"] = value
        if not item.scored:
            data["weight"] = None
        return data

    def clean_options_config(self, options, scored):
        if not isinstance(options, list) or not 1 <= len(options) <= 100:
            raise ValidationError("请配置 1 至 100 个选项。")
        result = []
        labels = set()
        points = forms.DecimalField(min_value=0, max_digits=11, decimal_places=6)
        for index, row in enumerate(options, start=1):
            label = row.get("label", "") if isinstance(row, dict) else ""
            if not isinstance(label, str) or not label.strip() or len(label.strip()) > 200:
                raise ValidationError(f"第 {index} 个选项名称须为 1 至 200 个字符。")
            label = label.strip()
            if label in labels or "\n" in label or "\r" in label:
                raise ValidationError(f"第 {index} 个选项名称重复或包含换行。")
            option = {"id": str(index), "label": label}
            if scored:
                value = row.get("score")
                if not isinstance(value, (str, int, float)):
                    raise ValidationError(f"第 {index} 个选项需要有效分值。")
                try:
                    option["score"] = format(points.clean(value), "f")
                except ValidationError as error:
                    raise ValidationError(f"第 {index} 个选项分值无效：{error.messages[0]}") from error
            labels.add(label)
            result.append(option)
        if scored and not any(Decimal(option["score"]) > 0 for option in result):
            raise ValidationError("参与计分的选项至少有一个分值大于 0。")
        return result

    def clean(self):
        data = super().clean()
        kind = data.get("field_type") or ItemType.NUMBER
        is_number = kind == ItemType.NUMBER
        is_choice = kind in CHOICE_TYPES
        scored = is_number or (is_choice and data.get("counts_for_score"))
        data["field_type"] = kind
        if scored and data.get("weight") is None:
            self.add_error("weight", "请填写参与计分的权重。")
        if not scored:
            data["weight"] = Decimal("0")
        default = data.get("default_value") or None
        if is_number:
            minimum = data.get("minimum")
            maximum = data.get("maximum")
            precision = data.get("precision")
            if precision is None and "precision" not in self.errors:
                precision = 2
            if minimum is None:
                self.add_error("minimum", "请填写最小值。")
            if maximum is None or minimum is not None and maximum <= minimum:
                self.add_error("maximum", "最大值必须大于最小值。")
            if precision is not None:
                data["precision"] = precision
                quantum = Decimal(1).scaleb(-precision)
                for field, limit in (("minimum", minimum), ("maximum", maximum)):
                    if limit is not None and limit != limit.quantize(quantum):
                        self.add_error(field, f"最多允许 {precision} 位小数。")
                if default is not None and minimum is not None and maximum is not None:
                    try:
                        value = forms.DecimalField(
                            min_value=minimum, max_value=maximum, max_digits=5 + precision, decimal_places=precision,
                        ).clean(default)
                        default = format(value, "f")
                    except ValidationError as error:
                        self.add_error("default_value", error)
        else:
            data.update(minimum=Decimal("0"), maximum=Decimal("100"), precision=2)
        data["options"] = self.validate_choice_defaults(data, default, kind, scored) if is_choice else []
        if not is_choice:
            if kind == ItemType.TEXT and default and "\n" in default:
                self.add_error("default_value", "单行文本的默认值不能包含换行。")
            data["default_value"] = default
        return data

    def validate_choice_defaults(self, data, default, kind, scored):
        try:
            options = self.clean_options_config(data.get("options"), scored)
        except ValidationError as error:
            self.add_error("options", error)
            return []
        data["default_value"] = None
        if default is not None:
            labels = {option["label"]: option["id"] for option in options}
            names = [line.strip() for line in default.splitlines() if line.strip()]
            if len(names) != len(set(names)) or any(name not in labels for name in names):
                self.add_error("default_value", "默认项必须是已有选项，且不能重复。")
            elif kind in MULTIPLE_TYPES:
                data["default_value"] = [labels[name] for name in names]
            elif len(names) == 1:
                data["default_value"] = labels[names[0]]
            else:
                self.add_error("default_value", "单选只能设置一个默认项。")
        return options


class BaseTemplateItems(BaseFormSet):
    ordering_widget = forms.HiddenInput

    @property
    def item_data(self):
        entries = [
            form.cleaned_data for form in self.forms if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]
        entries.sort(key=lambda data: (data["ORDER"] is None, data["ORDER"]))
        fields = TemplateItemForm.base_fields.keys() - {"counts_for_score"}
        return [
            {**{field: data[field] for field in fields}, "sort_order": position}
            for position, data in enumerate(entries, start=1)
        ]

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        items = self.item_data
        names = [item["name"].casefold() for item in items]
        if len(names) != len(set(names)):
            raise ValidationError("评分项名称不能重复。")
        if items and sum(item["weight"] for item in items) != 100:
            raise ValidationError("所有评分项的权重之和必须为 100%。")


TemplateItems = formset_factory(
    TemplateItemForm, formset=BaseTemplateItems, can_order=True, can_delete=True, extra=0, min_num=1, validate_min=True,
)


class TargetPicker(forms.SelectMultiple):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        option["attrs"]["data-department"] = value.instance.department
        option["attrs"]["data-position"] = value.instance.position
        return option


class RelationshipForm(forms.Form):
    reviewers = forms.ModelMultipleChoiceField(
        label="评分人", queryset=User.objects.none(), widget=forms.SelectMultiple(attrs={"size": 7})
    )
    targets = forms.ModelMultipleChoiceField(
        label="被评分人", queryset=User.objects.none(), widget=TargetPicker(attrs={"size": 7})
    )

    def __init__(self, *args, activity, **kwargs):
        super().__init__(*args, **kwargs)
        self.activity = activity
        employees = User.objects.filter(is_active=True).order_by("department", "username")
        self.fields["reviewers"].queryset = employees
        self.fields["targets"].queryset = employees
        self.fields["reviewers"].label_from_instance = (
            lambda user: f"{user} · {user.department}" if user.department else str(user)
        )
        self.fields["targets"].label_from_instance = (
            lambda user: " · ".join(part for part in (str(user), user.department, user.position) if part)
        )

    def clean(self):
        data = super().clean()
        if not self.activity.allow_self and data.get("reviewers") is not None and data.get("targets") is not None:
            if {user.id for user in data["reviewers"]} & {user.id for user in data["targets"]}:
                raise ValidationError("当前活动未启用自评，请从任意一侧移除重复选择的人员。")
        return data


class ScoreForm(forms.Form):
    def __init__(self, *args, items, existing, use_defaults=False, submitting=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = items
        for item in items:
            initial = existing.get(item.id, item.default_value if use_defaults else None)
            self.fields[f"item_{item.id}"] = self.answer_field(item, initial, submitting)

    @staticmethod
    def answer_field(item, initial, submitting):
        attributes = {
            "label": item.name, "required": submitting and item.required,
            "help_text": item.help_text, "initial": initial,
        }
        if item.numeric:
            if initial is not None:
                attributes["initial"] = format(Decimal(initial), f".{item.precision}f")
            return forms.DecimalField(
                **attributes, min_value=item.minimum, max_value=item.maximum,
                max_digits=5 + item.precision, decimal_places=item.precision,
                widget=forms.NumberInput(attrs={"step": format(Decimal(1).scaleb(-item.precision), "f")}),
            )
        if item.field_type == ItemType.TEXT:
            return forms.CharField(**attributes, max_length=2000)
        if item.field_type == ItemType.TEXTAREA:
            return forms.CharField(**attributes, max_length=2000, widget=forms.Textarea(attrs={"rows": 4}))
        choices = [(option["id"], option["label"]) for option in item.options]
        if item.field_type in MULTIPLE_TYPES:
            widget = forms.CheckboxSelectMultiple if item.field_type == ItemType.CHECKBOXES else forms.SelectMultiple
            return forms.MultipleChoiceField(**attributes, choices=choices, widget=widget)
        if item.field_type == ItemType.RADIO and item.required:
            return forms.ChoiceField(**attributes, choices=choices, widget=forms.RadioSelect)
        widget = forms.RadioSelect if item.field_type == ItemType.RADIO else forms.Select
        return forms.ChoiceField(**attributes, choices=[("", "未选择"), *choices], widget=widget)

    @property
    def item_fields(self):
        return [
            (
                item, self[f"item_{item.id}"], score_limit(item) if item.scored else None,
                json.dumps({option["id"]: option["score"] for option in item.options}) if item.scored and item.choice else "",
            )
            for item in self.items
        ]

    @property
    def values(self):
        return {item.id: self.cleaned_data[f"item_{item.id}"] for item in self.items}


class TaskFilterForm(forms.Form):
    activity = forms.ModelChoiceField(
        label="活动", queryset=Activity.objects.none(), required=False, empty_label="全部活动"
    )
    name = forms.CharField(label="被评分人", max_length=150, required=False)
    department = forms.CharField(label="部门", max_length=80, required=False)
    status = forms.ChoiceField(label="状态", choices=[("", "全部状态"), *Task.Status.choices], required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["activity"].queryset = Activity.objects.filter(
            tasks__reviewer__user=user, tasks__active=True, activated_at__isnull=False,
        ).distinct()


class ReportFilterForm(forms.Form):
    name = forms.CharField(label="姓名或工号", max_length=150, required=False)
    department = forms.ChoiceField(label="部门", required=False)
    sort = forms.ChoiceField(
        label="排序", required=False, choices=(
            ("", "按部门与姓名"), ("highest", "综合分从高到低"), ("lowest", "综合分从低到高"),
        ),
    )

    def __init__(self, *args, activity, progress=False, **kwargs):
        super().__init__(*args, **kwargs)
        departments = (
            activity.participants.exclude(department="").order_by("department")
            .values_list("department", flat=True).distinct()
        )
        self.fields["department"].choices = [("", "全部部门"), *((name, name) for name in departments)]
        if progress:
            del self.fields["sort"]
