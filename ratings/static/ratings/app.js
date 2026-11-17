document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-confirm]");
  if (button && !window.confirm(button.dataset.confirm)) {
    event.preventDefault();
  }
});

const templateChoiceTypes = ["radio", "select", "multiselect", "checkboxes"];
const templateForm = document.querySelector("[data-template-form]");
if (templateForm) {
  const list = templateForm.querySelector("[data-item-list]");
  const source = templateForm.querySelector("[data-item-template]");
  const total = templateForm.querySelector('input[name$="-TOTAL_FORMS"]');
  const rows = templateForm.querySelector("[data-item-rows]");
  const rowTemplate = templateForm.querySelector("[data-item-row]");
  const emptyRow = templateForm.querySelector("[data-item-empty]");
  const weightTotal = templateForm.querySelector("[data-total-weight]");
  const add = templateForm.querySelector("[data-add-item]");
  const drawer = templateForm.querySelector("[data-item-drawer]");
  const drawerBody = drawer.querySelector("[data-item-drawer-body]");
  const drawerTitle = drawer.querySelector("[data-item-drawer-title]");
  const field = (item, name) => item.querySelector(`[name$="-${name}"]`);
  let active;
  let draggedItem;

  const renderRows = () => {
    rows.replaceChildren();
    let sum = 0;
    const itemRows = new Map();
    const items = [...list.children].filter((item) => !field(item, "DELETE").checked);
    for (const [index, item] of items.entries()) {
      field(item, "ORDER").value = index + 1;
      const row = rowTemplate.content.firstElementChild.cloneNode(true);
      const kind = field(item, "field_type");
      const scored = !kind.value || kind.value === "number" ||
        (templateChoiceTypes.includes(kind.value) && field(item, "counts_for_score").checked);
      const weight = scored ? field(item, "weight").value : "";
      const name = field(item, "name").value.trim() || "未命名评分项";
      sum += Number(weight) || 0;
      row.querySelector("[data-item-name]").textContent = name;
      row.querySelector("[data-item-type]").textContent = kind.selectedOptions[0]?.textContent || "数字";
      row.querySelector("[data-item-required]").textContent = field(item, "required").checked ? "是" : "否";
      row.querySelector("[data-item-weight]").textContent = weight ? `${Number(weight)}%` : scored ? "未填写" : "不计分";
      row.querySelector("[data-item-error]").hidden = !item.querySelector(".errorlist");
      const up = row.querySelector("[data-move-up]");
      const down = row.querySelector("[data-move-down]");
      up.disabled = index === 0;
      down.disabled = index === items.length - 1;
      up.setAttribute("aria-label", `上移 ${name}`);
      down.setAttribute("aria-label", `下移 ${name}`);
      up.addEventListener("click", () => moveItem(item, items[index - 1], false, "[data-move-up]"));
      down.addEventListener("click", () => moveItem(item, items[index + 1], true, "[data-move-down]"));
      if (items.length > 1) enableRowDrag(row, item);
      else row.querySelector("[data-item-handle]").draggable = false;
      row.querySelector("[data-edit-item]").addEventListener("click", () => openItem(item));
      row.querySelector("[data-remove-item]").addEventListener("click", () => {
        field(item, "DELETE").checked = true;
        const remaining = [...renderRows().values()];
        const nextRow = remaining[index] || remaining[index - 1];
        (nextRow?.querySelector("[data-edit-item]") || add).focus();
      });
      itemRows.set(item, row);
      rows.append(row);
    }
    if (!items.length) rows.append(emptyRow.content.cloneNode(true));
    weightTotal.textContent = `${Number(sum.toFixed(2))}%`;
    return itemRows;
  };

  function moveItem(item, target, after, buttonSelector) {
    if (after) target.after(item);
    else target.before(item);
    const row = renderRows().get(item);
    if (buttonSelector) {
      (row.querySelector(`${buttonSelector}:enabled`) || row.querySelector(".item-order button:enabled")).focus();
    }
  }

  function enableRowDrag(row, item) {
    const handle = row.querySelector("[data-item-handle]");
    const belowMiddle = (event) => {
      const bounds = row.getBoundingClientRect();
      return event.clientY >= bounds.top + bounds.height / 2;
    };
    handle.addEventListener("dragstart", (event) => {
      draggedItem = item;
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", field(item, "ORDER").value);
      row.classList.add("item-dragging");
    });
    handle.addEventListener("dragend", () => {
      draggedItem = null;
      row.classList.remove("item-dragging");
      rows.querySelector("[data-drop-position]")?.removeAttribute("data-drop-position");
    });
    row.addEventListener("dragover", (event) => {
      if (!draggedItem || draggedItem === item) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      row.dataset.dropPosition = belowMiddle(event) ? "after" : "before";
    });
    row.addEventListener("dragleave", (event) => {
      if (!row.contains(event.relatedTarget)) row.removeAttribute("data-drop-position");
    });
    row.addEventListener("drop", (event) => {
      if (!draggedItem || draggedItem === item) return;
      event.preventDefault();
      const sourceItem = draggedItem;
      draggedItem = null;
      moveItem(sourceItem, item, belowMiddle(event));
    });
  }

  function openItem(item) {
    const placeholder = document.createComment("");
    if (item) {
      const draft = item.cloneNode(true);
      for (const control of draft.querySelectorAll("input, select, textarea")) {
        const original = item.elements.namedItem(control.name);
        control.value = original.value;
        if (control.type === "checkbox") control.checked = original.checked;
      }
      item.replaceWith(placeholder);
      drawerBody.append(draft);
    } else {
      drawerBody.insertAdjacentHTML("beforeend", source.innerHTML.replaceAll("__prefix__", total.value));
    }
    const draft = drawerBody.firstElementChild;
    const name = field(draft, "name");
    name.required = true;
    configureItem(draft);
    active = { item, placeholder, draft };
    drawerTitle.textContent = item ? "编辑评分项" : "添加评分项";
    drawer.showModal();
    const error = draft.querySelector(".errorlist");
    if (error) {
      error.setAttribute("tabindex", "-1");
      error.focus();
    } else {
      name.focus();
    }
  }

  const closeItem = (apply) => {
    const { item, placeholder, draft } = active;
    let saved = item;
    if (apply) {
      const name = field(draft, "name");
      name.value = name.value.trim();
      const invalid = [...draft.elements].find((control) => control.willValidate && !control.validity.valid);
      if (invalid) {
        invalid.reportValidity();
        return;
      }
      draft.querySelector("[data-option-list]").replaceChildren();
      for (const error of draft.querySelectorAll(".errorlist")) error.remove();
      saved = draft;
    }
    if (item) {
      placeholder.replaceWith(saved);
    } else if (saved) {
      list.append(saved);
      total.value = Number(total.value) + 1;
    }
    drawerBody.replaceChildren();
    drawer.close();
    active = null;
    (renderRows().get(saved)?.querySelector("[data-edit-item]") || add).focus({ preventScroll: !apply });
  };

  add.addEventListener("click", () => openItem());
  drawer.querySelector("[data-apply-item]").addEventListener("click", () => closeItem(true));
  for (const button of drawer.querySelectorAll("[data-cancel-item]")) {
    button.addEventListener("click", () => closeItem(false));
  }
  drawer.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeItem(false);
  });
  templateForm.addEventListener("submit", (event) => {
    if (active) {
      event.preventDefault();
      closeItem(true);
    } else if (!templateForm.querySelector('[name="name"]').reportValidity()) {
      event.preventDefault();
    }
  });

  if (!list.childElementCount) total.value = 0;
  const itemOrder = (item) => Number(field(item, "ORDER").value) || Infinity;
  list.append(...[...list.children].sort((left, right) => itemOrder(left) - itemOrder(right)));
  renderRows();
  const invalidItem = [...list.children].find((item) => !field(item, "DELETE").checked && item.querySelector(".errorlist"));
  if (invalidItem) openItem(invalidItem);
}

function configureItem(row) {
  const kind = row.querySelector('[name$="-field_type"]');
  const counts = row.querySelector('[name$="-counts_for_score"]');
  const hiddenOptions = row.querySelector('[name$="-options"]');
  const optionEditor = row.querySelector("[data-item-options]");
  const optionList = row.querySelector("[data-option-list]");
  const source = row.querySelector("[data-option-template]");

  const showField = (name, visible) => {
    const field = row.querySelector(`[data-config-field="${name}"]`);
    field.hidden = !visible;
    field.querySelector("input").disabled = !visible;
  };
  const updateOptions = () => {
    hiddenOptions.value = JSON.stringify([...optionList.children].map((option) => ({
      label: option.querySelector("[data-option-label]").value,
      score: option.querySelector("[data-option-score]").value,
    })));
  };
  const updateFields = () => {
    const isNumber = kind.value === "number";
    const isChoice = templateChoiceTypes.includes(kind.value);
    for (const field of ["minimum", "maximum", "precision"]) showField(field, isNumber);
    showField("counts_for_score", isChoice);
    showField("weight", isNumber || (isChoice && counts.checked));
    optionEditor.hidden = !isChoice;
    row.querySelector("[data-choice-default-hint]").hidden = !isChoice;
    for (const option of optionList.children) {
      option.querySelector("[data-option-label]").disabled = !isChoice;
      const points = option.querySelector("[data-option-points]");
      points.hidden = !counts.checked;
      points.querySelector("input").disabled = !isChoice || !counts.checked;
    }
  };
  const addOption = (option = {}) => {
    const entry = source.content.cloneNode(true);
    entry.querySelector("[data-option-label]").value = option.label ?? "";
    entry.querySelector("[data-option-score]").value = option.score ?? "";
    optionList.append(entry);
  };
  try {
    const options = JSON.parse(hiddenOptions.value || "[]");
    if (Array.isArray(options)) {
      for (const option of options) {
        if (option && typeof option === "object") addOption(option);
      }
    }
  } catch (error) {
    // 服务端会显示无效选项的错误，可在此重新编辑。
  }
  kind.addEventListener("change", updateFields);
  counts.addEventListener("change", updateFields);
  optionList.addEventListener("input", updateOptions);
  row.querySelector("[data-add-option]").addEventListener("click", () => {
    addOption();
    updateFields();
    updateOptions();
    optionList.lastElementChild.querySelector("[data-option-label]").focus();
  });
  optionList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-option]");
    if (button) {
      button.closest(".option-row").remove();
      updateOptions();
    }
  });
  updateFields();
}

for (const picker of document.querySelectorAll("[data-person-picker]")) {
  const search = picker.querySelector("[data-person-search]");
  const select = picker.querySelector("select[multiple]");
  const filters = [...picker.querySelectorAll("[data-person-filter]")];
  const count = picker.querySelector("[data-person-count]");
  const updateCount = () => {
    count.textContent = `已选 ${select.selectedOptions.length} 人`;
  };
  const filterPeople = () => {
    const term = search.value.trim().toLowerCase();
    for (const option of select.options) {
      option.hidden = !option.text.toLowerCase().includes(term) ||
        filters.some((filter) => filter.value && option.dataset[filter.dataset.personFilter] !== filter.value);
    }
  };
  for (const filter of filters) {
    const values = new Set([...select.options].map((option) => option.dataset[filter.dataset.personFilter]));
    for (const value of [...values].filter(Boolean).sort((left, right) => left.localeCompare(right, "zh-CN"))) {
      filter.add(new Option(value, value));
    }
    filter.addEventListener("change", filterPeople);
    filter.parentElement.hidden = false;
  }
  count.hidden = false;
  updateCount();
  search.addEventListener("input", filterPeople);
  select.addEventListener("change", updateCount);
  picker.querySelector("[data-select-people]").addEventListener("click", () => {
    for (const option of select.options) {
      if (!option.hidden) option.selected = true;
    }
    updateCount();
  });
  search.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      select.focus();
    }
  });
}

const scoreForm = document.querySelector("[data-score-form]");
if (scoreForm) {
  const fields = [...scoreForm.querySelectorAll("[data-score-item]")];
  const preview = scoreForm.querySelector("[data-score-preview]");
  const updatePreview = () => {
    const total = fields.reduce((sum, field) => {
      const number = field.querySelector('input[type="number"]');
      let points = 0;
      if (number) {
        points = number.value && number.validity.valid ? Number(number.value) : 0;
      } else {
        const scores = JSON.parse(field.dataset.optionScores);
        const select = field.querySelector("select");
        const chosen = select ? [...select.selectedOptions] : [...field.querySelectorAll("input:checked")];
        points = chosen.reduce((subtotal, option) => subtotal + Number(scores[option.value] ?? 0), 0);
      }
      return sum + points / Number(field.dataset.maximum) * Number(field.dataset.weight);
    }, 0);
    preview.textContent = total.toFixed(2);
  };
  scoreForm.addEventListener("input", updatePreview);
  scoreForm.addEventListener("submit", (event) => {
    if (event.submitter?.value !== "submit") return;
    let firstInvalid;
    for (const row of scoreForm.querySelectorAll("[data-answer-row]")) {
      const controls = [...row.querySelectorAll("input, select, textarea")];
      const invalid = controls.find((control) => !control.validity.valid);
      const filled = controls.some((control) => {
        if (control.matches('[type="radio"], [type="checkbox"]')) return control.checked && control.value !== "";
        return control.value.trim() !== "";
      });
      const required = row.hasAttribute("data-required-answer");
      const message = invalid?.validationMessage || (required && !filled ? "请填写此必填项。" : "");
      row.querySelector("[data-answer-error]").textContent = message;
      if (message && !firstInvalid) firstInvalid = invalid || controls[0];
    }
    if (firstInvalid) {
      event.preventDefault();
      firstInvalid.focus();
    }
  });
  updatePreview();
}
