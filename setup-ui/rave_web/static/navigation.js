const DEFAULT_VIEW = "dashboard";
const VALID_VIEWS = new Set([DEFAULT_VIEW, "network", "system", "diagnostics"]);

export function normalizeView(name) {
  return VALID_VIEWS.has(name) ? name : DEFAULT_VIEW;
}

export function selectView(pages, links, name) {
  const selected = normalizeView(name);
  pages.forEach((page) => { page.hidden = page.dataset.page !== selected; });
  links.forEach((link) => {
    const active = link.dataset.view === selected;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  return selected;
}
