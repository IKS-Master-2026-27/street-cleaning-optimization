/* Custom dropdowns */

const CHEVRON =
  '<svg class="dd-chevron" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 4.5 6 8l3.5-3.5"/></svg>';
let openDropdown = null;

function enhanceSelects(root = document) {
  root.querySelectorAll("select:not([data-enhanced])").forEach(makeDropdown);
}

function makeDropdown(select) {
  select.dataset.enhanced = "1";
  const wrap = document.createElement("div");
  wrap.className = "dd" + (select.closest(".step") ? " block" : "");
  select.parentNode.insertBefore(wrap, select);
  wrap.appendChild(select);
  select.hidden = true;

  const label =
    select.getAttribute("aria-label") ||
    select.closest("label")?.firstChild?.textContent?.trim() ||
    "Choose";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "dd-btn";
  button.disabled = select.disabled;
  button.setAttribute("aria-haspopup", "listbox");
  button.setAttribute("aria-expanded", "false");
  button.setAttribute("aria-label", label);
  const list = document.createElement("ul");
  list.className = "dd-list";
  list.setAttribute("role", "listbox");
  list.setAttribute("aria-label", label);
  list.tabIndex = -1;
  list.hidden = true;
  wrap.append(button, list);

  const options = [];
  const addOption = (opt) => {
    const li = document.createElement("li");
    li.className = "dd-opt";
    li.setAttribute("role", "option");
    li.dataset.value = opt.value;
    li.textContent = opt.textContent;
    li.addEventListener("click", () => choose(opt.value));
    li.addEventListener("pointermove", () => setActive(options.indexOf(li)));
    options.push(li);
    list.appendChild(li);
  };
  for (const child of select.children) {
    if (child.tagName === "OPTGROUP") {
      const head = document.createElement("li");
      head.className = "dd-group";
      head.setAttribute("role", "presentation");
      head.textContent = child.label;
      list.appendChild(head);
      [...child.children].forEach(addOption);
    } else {
      addOption(child);
    }
  }

  let active = -1;
  const sync = () => {
    const current = select.options[select.selectedIndex];
    button.innerHTML = `<span class="dd-text">${esc(current ? current.textContent : "")}</span>${CHEVRON}`;
    options.forEach((li) =>
      li.setAttribute(
        "aria-selected",
        String(li.dataset.value === select.value),
      ),
    );
  };
  const setActive = (i) => {
    active = Math.max(0, Math.min(options.length - 1, i));
    options.forEach((li, j) => li.classList.toggle("active", j === active));
    options[active]?.scrollIntoView({ block: "nearest" });
  };
  const open = () => {
    if (openDropdown && openDropdown !== close) openDropdown();
    list.hidden = false;
    // below the field; above it only when there is clearly no room below
    const box = button.getBoundingClientRect();
    const below = innerHeight - box.bottom - 12,
      above = box.top - 12;
    const inline = wrap.classList.contains("block"); // sidebar: opens in place, never upwards
    const up = !inline && below < 180 && above > below;
    wrap.classList.toggle("up", up);
    list.style.maxHeight = inline
      ? "320px"
      : `${Math.max(120, Math.min(320, up ? above : below))}px`;
    button.setAttribute("aria-expanded", "true");
    setActive(
      Math.max(
        0,
        options.findIndex((li) => li.dataset.value === select.value),
      ),
    );
    list.focus({ preventScroll: true });
    openDropdown = close;
  };
  const close = (focusButton = false) => {
    list.hidden = true;
    button.setAttribute("aria-expanded", "false");
    if (openDropdown === close) openDropdown = null;
    if (focusButton) button.focus();
  };
  const choose = (value) => {
    close(true);
    if (value === select.value) return;
    select.value = value;
    sync();
    select.dispatchEvent(new Event("change", { bubbles: true }));
  };

  button.addEventListener("click", () => (list.hidden ? open() : close()));
  button.addEventListener("keydown", (e) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
      e.preventDefault();
      open();
    }
  });
  list.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive(active + 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive(active - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setActive(options.length - 1);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (options[active]) choose(options[active].dataset.value);
    } else if (e.key === "Escape") {
      e.preventDefault();
      close(true);
    } else if (e.key === "Tab") close();
  });
  sync();
}

document.addEventListener("pointerdown", (e) => {
  if (openDropdown && !e.target.closest(".dd")) openDropdown();
});
