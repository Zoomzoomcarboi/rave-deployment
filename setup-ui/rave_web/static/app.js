const pages = [...document.querySelectorAll("[data-page]")];
const links = [...document.querySelectorAll("[data-view]")];
const sidebar = document.querySelector(".sidebar");
const underlay = document.querySelector(".underlay");
const menuButton = document.querySelector(".menu-button");
const FETCH_TIMEOUT_MS = 1000;
const FAILURE_RETRY_MS = 1000;
const MIN_POLL_MS = 250;
const MAX_POLL_MS = 2000;
let pollTimer = null;
let staleTimer = null;
let freshnessGeneration = 0;

function closeMenu() {
  sidebar.classList.remove("visible");
  underlay.hidden = true;
  menuButton.setAttribute("aria-expanded", "false");
}

function showView(name) {
  const selected = pages.some((page) => page.dataset.page === name) ? name : "dashboard";
  pages.forEach((page) => { page.hidden = page.dataset.page !== selected; });
  links.forEach((link) => link.classList.toggle("active", link.dataset.view === selected));
  document.querySelector(".content").focus({ preventScroll: true });
  closeMenu();
}

function label(value) { return value.replaceAll("_", " "); }

function setDynamicState(selector, text, availability = "unavailable") {
  const element = document.querySelector(selector);
  element.className = `dynamic-state ${availability}`;
  element.textContent = text;
}

function componentCard(name, status) {
  const article = document.createElement("article");
  article.className = "card";
  const kicker = document.createElement("p");
  kicker.className = "card-kicker";
  kicker.textContent = name;
  const heading = document.createElement("h2");
  heading.textContent = label(status.availability);
  const reason = document.createElement("p");
  reason.textContent = label(status.reason);
  const pill = document.createElement("span");
  pill.className = `pill ${status.availability}`;
  pill.textContent = label(status.availability);
  article.append(kicker, heading, reason, pill);
  return article;
}

function invalidateDynamic(reason, availability = "unavailable") {
  freshnessGeneration += 1;
  if (staleTimer !== null) window.clearTimeout(staleTimer);
  staleTimer = null;
  const overall = document.querySelector("#overall-state");
  overall.className = `pill ${availability}`;
  overall.textContent = label(availability);
  document.querySelector("#component-cards").replaceChildren(
    componentCard("Management API", { availability, reason }),
  );
  setDynamicState("#network-mode", "Unavailable");
  document.querySelector("#network-detail").textContent = "Management network status unavailable.";
  setDynamicState("#os-version", "Unavailable");
  setDynamicState("#update-state", "Unavailable");
}

function installFreshness(validForMs) {
  freshnessGeneration += 1;
  const ownedGeneration = freshnessGeneration;
  if (staleTimer !== null) window.clearTimeout(staleTimer);
  staleTimer = window.setTimeout(() => {
    if (freshnessGeneration === ownedGeneration) invalidateDynamic("status_stale");
  }, validForMs);
}

async function fetchJson(path, signal) {
  const response = await fetch(path, { cache: "no-store", signal });
  if (!response.ok) throw new Error(`management API request failed: ${path}`);
  return response.json();
}

function scheduleRefresh(delayMs) {
  if (pollTimer !== null) window.clearTimeout(pollTimer);
  pollTimer = window.setTimeout(refreshState, delayMs);
}

async function refreshState() {
  const controller = new AbortController();
  const fetchTimeout = window.setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  let nextRefreshMs = FAILURE_RETRY_MS;
  try {
    const requests = ["/api/v1/status", "/api/v1/network", "/api/v1/system"].map(
      async (path) => {
        try {
          return await fetchJson(path, controller.signal);
        } catch (error) {
          controller.abort();
          throw error;
        }
      },
    );
    const settled = await Promise.allSettled(requests);
    const failed = settled.find((result) => result.status === "rejected");
    if (failed) throw failed.reason;
    const [status, network, system] = settled.map((result) => result.value);
    const overall = document.querySelector("#overall-state");
    overall.className = `pill ${status.overall}`;
    overall.textContent = label(status.overall);
    const cards = document.querySelector("#component-cards");
    cards.replaceChildren(...["camera", "perception", "hailo", "comma_link"].map((key) => componentCard(label(key), status[key])));
    setDynamicState("#network-mode", label(network.mode), network.availability);
    document.querySelector("#network-detail").textContent = network.actuation_available ? "Network provider available." : "Network actuation is unavailable in Gate 1.";
    setDynamicState("#os-version", system.os_version || "Unavailable", system.availability);
    setDynamicState("#update-state", label(system.update_status.availability), system.update_status.availability);
    installFreshness(status.valid_for_ms);
    nextRefreshMs = Math.max(MIN_POLL_MS, Math.min(MAX_POLL_MS, Math.floor(status.valid_for_ms / 2)));
  } catch (error) {
    invalidateDynamic(error.name === "AbortError" ? "status_timeout" : "status_unavailable", "error");
  } finally {
    window.clearTimeout(fetchTimeout);
    scheduleRefresh(nextRefreshMs);
  }
}

window.addEventListener("hashchange", () => showView(location.hash.slice(1)));
menuButton.addEventListener("click", () => {
  const visible = sidebar.classList.toggle("visible");
  underlay.hidden = !visible;
  menuButton.setAttribute("aria-expanded", String(visible));
});
underlay.addEventListener("click", closeMenu);
showView(location.hash.slice(1));
invalidateDynamic("status_starting");
refreshState();
