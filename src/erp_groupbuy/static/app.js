"use strict";
document.addEventListener("DOMContentLoaded", () => {
  const menu = document.querySelector(".menu-toggle");
  menu?.addEventListener("click", () => {
    const opened = document.body.classList.toggle("nav-open");
    menu.setAttribute("aria-expanded", String(opened));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      document.body.classList.remove("nav-open");
      menu?.setAttribute("aria-expanded", "false");
    }
  });
  document.querySelectorAll("[data-current-date]").forEach((node) => {
    node.textContent = new Intl.DateTimeFormat("zh-CN", {month:"long",day:"numeric",weekday:"short"}).format(new Date());
  });
  document.querySelectorAll("[data-dismiss]").forEach((button) => button.addEventListener("click", () => button.closest(".flash").remove()));
  document.querySelectorAll("[data-back]").forEach((button) => button.addEventListener("click", () => history.back()));
  document.querySelectorAll("[data-check-all]").forEach((control) => {
    control.addEventListener("change", () => {
      document.getElementsByName(control.dataset.checkAll).forEach((box) => { box.checked = control.checked; });
    });
  });
  document.querySelectorAll("form[method='post']").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
        event.preventDefault();
        return;
      }
      if (form.dataset.submitting === "true") {
        event.preventDefault();
        return;
      }
      form.dataset.submitting = "true";
      // Server-side request keys provide the actual idempotency guarantee.
      form.querySelectorAll("button:not([type='button'])").forEach((button) => { button.disabled = true; });
    });
  });
});
window.addEventListener("pageshow", () => {
  document.querySelectorAll("form[data-submitting]").forEach((form) => {
    delete form.dataset.submitting;
    form.querySelectorAll("button").forEach((button) => { button.disabled = false; });
  });
});
