import { selectView } from "/static/navigation.js";

const pages = [...document.querySelectorAll("[data-page]")];
const links = [...document.querySelectorAll("[data-view]")];
const sidebar = document.querySelector(".sidebar");
const underlay = document.querySelector(".underlay");
const menuButton = document.querySelector(".menu-button");
const menuButtonLabel = menuButton.querySelector(".sr-only");
const wifiRefresh = document.querySelector("#wifi-refresh");
const wifiList = document.querySelector("#wifi-network-list");
const wifiPassword = document.querySelector("#wifi-password");
const wifiPasswordHelp = document.querySelector("#wifi-password-help");
const wifiConnect = document.querySelector("#wifi-connect");
const wifiForm = document.querySelector("#wifi-connect-form");
const restoreProvisioning = document.querySelector("#restore-provisioning");
const handoffPanel = document.querySelector("#handoff-panel");
const FETCH_TIMEOUT_MS = 1000;
const FAILURE_RETRY_MS = 1000;
const MIN_POLL_MS = 250;
const MAX_POLL_MS = 2000;
const NETWORK_ACTION_TIMEOUT_MS = 120000;
const WIFI_SCAN_REQUEST_TIMEOUT_MS = 35000;
const NETWORK_ACTION_REQUEST_TIMEOUT_MS = 5000;
const OVERALL_COPY = {
  ready: ["RAVE is ready.", "Current status confirmed"],
  starting: ["RAVE is starting. Current status is not ready yet.", "Startup in progress"],
  degraded: ["RAVE is available with a reported limitation.", "Attention recommended"],
  unavailable: ["RAVE does not have a current trustworthy perception state.", "Current data required"],
  error: ["RAVE status could not be confirmed through the management API.", "Status check failed"],
};
const WIFI_SECURITY_POLICY = {
  none: {
    connectable: false,
    passwordEnabled: false,
    clearPassword: false,
    help: "Select a secured network to enter its password.",
  },
  open: {
    connectable: true,
    passwordEnabled: false,
    clearPassword: true,
    help: "This network is open; no password is required.",
  },
  wpa_personal: {
    connectable: true,
    passwordEnabled: true,
    clearPassword: false,
    help: "Enter the Wi-Fi password. RAVE never returns or displays a stored password.",
  },
  enterprise: {
    connectable: false,
    passwordEnabled: false,
    clearPassword: true,
    help: "This network security type is not supported by the provisioning flow.",
  },
  unsupported: {
    connectable: false,
    passwordEnabled: false,
    clearPassword: true,
    help: "This network security type is not supported by the provisioning flow.",
  },
};
let pollTimer = null;
let staleTimer = null;
let freshnessGeneration = 0;
let networkActionDeadline = null;
let scannedNetworks = new Map();
let selectedSsid = null;
let scanInProgress = false;

function closeMenu() {
  sidebar.classList.remove("visible");
  underlay.hidden = true;
  menuButton.setAttribute("aria-expanded", "false");
  menuButtonLabel.textContent = "Open navigation";
}

function showView(name) {
  selectView(pages, links, name);
  document.querySelector(".content").focus({ preventScroll: true });
  closeMenu();
}

function label(value) {
  return value.replaceAll("_", " ");
}

function setDynamicState(selector, text, availability = "unavailable") {
  const element = document.querySelector(selector);
  element.className = `dynamic-state ${availability}`;
  element.textContent = text;
}

function setNetworkAction(text, state = "") {
  const element = document.querySelector("#network-action-status");
  element.className = `action-status ${state}`.trim();
  element.textContent = text;
}

function renderOverall(availability) {
  const [summary, proof] = OVERALL_COPY[availability] || OVERALL_COPY.unavailable;
  const hero = document.querySelector("#status-hero");
  const overall = document.querySelector("#overall-state");
  hero.className = `status-hero ${availability}`;
  overall.className = `status-value ${availability}`;
  overall.textContent = label(availability);
  document.querySelector("#overall-summary").textContent = summary;
  document.querySelector("#overall-proof").textContent = proof;
}

function componentCard(name, status) {
  const article = document.createElement("article");
  article.className = "component-card";
  const header = document.createElement("div");
  header.className = "component-card-header";
  const kicker = document.createElement("p");
  kicker.className = "card-kicker";
  kicker.textContent = name;
  const dot = document.createElement("span");
  dot.className = `state-dot ${status.availability}`;
  dot.setAttribute("aria-hidden", "true");
  header.append(kicker, dot);
  const heading = document.createElement("h3");
  heading.textContent = label(status.availability);
  const reason = document.createElement("p");
  reason.textContent = label(status.reason);
  const pill = document.createElement("span");
  pill.className = `pill ${status.availability}`;
  pill.textContent = label(status.availability);
  article.append(header, heading, reason, pill);
  return article;
}

function invalidateDynamic(reason, availability = "unavailable") {
  freshnessGeneration += 1;
  if (staleTimer !== null) window.clearTimeout(staleTimer);
  staleTimer = null;
  renderOverall(availability);
  document.querySelector("#component-cards").replaceChildren(
    componentCard("Management API", { availability, reason }),
  );
  setDynamicState("#network-mode", "Unavailable");
  setDynamicState("#overview-network", "Unavailable");
  document.querySelector("#network-detail").textContent = "Management network status unavailable.";
  document.querySelector("#overview-network-detail").textContent = "Current network state unavailable.";
  const marker = document.querySelector("#network-state-marker");
  marker.className = "state-marker unavailable";
  marker.textContent = "Status unavailable";
  setDynamicState("#rave-setup-state", "Unavailable");
  setDynamicState("#os-version", "Unavailable");
  setDynamicState("#management-state", "Unavailable");
  setDynamicState("#overview-system", "Unavailable");
  setDynamicState("#temperature", "Unavailable");
  setDynamicState("#overview-temperature", "Unavailable");
  setDynamicState("#update-state", "Unavailable");
  setDynamicState("#time-sync-state", "Unavailable");
  document.querySelector("#web-version").textContent = "Unavailable";
  document.querySelector("#utc-time").textContent = "Unavailable";
  document.querySelector("#rtc-state").textContent = "Unavailable";
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

async function postJson(path, body, signal) {
  const response = await fetch(path, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) throw new Error(`management API request failed: ${path}`);
  return response.json();
}

function boundedRequest(timeoutMs) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  return {
    signal: controller.signal,
    cancel: () => window.clearTimeout(timeout),
  };
}

function showHandoff() {
  handoffPanel.hidden = false;
}

function updateTransitionMessage() {
  if (networkActionDeadline === null) return;
  if (performance.now() < networkActionDeadline) {
    setNetworkAction("Connection transition in progress. This page may be temporarily unreachable. Continue at rave-pi.local:8080 after joining the management network.", "transition");
    return;
  }
  networkActionDeadline = null;
  setNetworkAction("Unable to confirm the transition. Rejoin RAVE-Setup and refresh; the appliance restores it after a bounded failure.", "error");
}

function rejectNetworkAction(message) {
  networkActionDeadline = null;
  setNetworkAction(message, "error");
}

function renderNetworkStatus(network) {
  const interfaceName = network.management_interface || "Unavailable";
  const station = network.station_ssid ? ` (${network.station_ssid})` : "";
  const mode = label(network.mode);
  document.querySelector("#network-detail").textContent = `${mode}${station} on ${interfaceName}.`;
  setDynamicState("#overview-network", mode, network.availability);
  document.querySelector("#overview-network-detail").textContent = network.station_ssid
    ? `${network.station_ssid} on ${interfaceName}`
    : `${interfaceName} management interface`;
  const marker = document.querySelector("#network-state-marker");
  marker.className = `state-marker ${network.availability}`;
  marker.textContent = `${label(network.availability)} status`;
  setDynamicState(
    "#rave-setup-state",
    network.provisioning_ap_active ? "Active" : "Inactive",
    network.provisioning_ap_active ? "ready" : "degraded",
  );
  if (network.mode === "station_connected" && networkActionDeadline !== null) {
    networkActionDeadline = null;
    setNetworkAction("Station connection confirmed. Join the same Wi-Fi network, then open rave-pi.local:8080.", "ready");
    showHandoff();
  } else if (network.mode === "provisioning_ap" && network.last_error) {
    networkActionDeadline = null;
    setNetworkAction(`Station connection failed (${label(network.last_error)}). RAVE-Setup was restored.`, "error");
  } else {
    updateTransitionMessage();
  }
}

function renderTime(system) {
  const synchronized = system.time.synchronized;
  setDynamicState("#time-sync-state", synchronized ? "Synchronized" : "Unsynchronized", synchronized ? "ready" : "degraded");
  document.querySelector("#utc-time").textContent = new Date(system.time.current_utc).toISOString();
  document.querySelector("#rtc-state").textContent = system.time.rtc_available ? "Available" : "Unavailable";
}

function scheduleRefresh(delayMs) {
  if (pollTimer !== null) window.clearTimeout(pollTimer);
  pollTimer = window.setTimeout(refreshState, delayMs);
}

async function refreshState() {
  if (scanInProgress) {
    scheduleRefresh(FAILURE_RETRY_MS);
    return;
  }
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
    renderOverall(status.overall);
    document.querySelector("#component-cards").replaceChildren(
      ...["camera", "perception", "hailo", "comma_link"].map((key) => componentCard(label(key), status[key])),
    );
    setDynamicState("#network-mode", label(network.mode), network.availability);
    renderNetworkStatus(network);
    setDynamicState("#os-version", system.os_version || "Unavailable", system.availability);
    setDynamicState("#management-state", label(system.availability), system.availability);
    setDynamicState("#overview-system", label(system.availability), system.availability);
    setDynamicState("#update-state", label(system.update_status.availability), system.update_status.availability);
    document.querySelector("#web-version").textContent = system.web_version;
    const temperature = system.temperature_c === null ? "Unavailable" : `${system.temperature_c.toFixed(1)} °C`;
    const temperatureState = system.temperature_c === null ? "degraded" : system.availability;
    setDynamicState("#temperature", temperature, temperatureState);
    setDynamicState("#overview-temperature", temperature, temperatureState);
    renderTime(system);
    installFreshness(status.valid_for_ms);
    nextRefreshMs = Math.max(MIN_POLL_MS, Math.min(MAX_POLL_MS, Math.floor(status.valid_for_ms / 2)));
  } catch (error) {
    invalidateDynamic(error.name === "AbortError" ? "status_timeout" : "status_unavailable", "error");
    updateTransitionMessage();
  } finally {
    window.clearTimeout(fetchTimeout);
    scheduleRefresh(nextRefreshMs);
  }
}

function renderWifiEmpty(title, description, error = false) {
  const empty = document.createElement("div");
  empty.className = `empty-state${error ? " error" : ""}`;
  const icon = document.createElement("span");
  icon.className = "empty-state-icon";
  icon.setAttribute("aria-hidden", "true");
  const heading = document.createElement("strong");
  heading.textContent = title;
  const copy = document.createElement("p");
  copy.textContent = description;
  empty.append(icon, heading, copy);
  wifiList.replaceChildren(empty);
}

function signalBars(signalPercent) {
  const bars = document.createElement("span");
  bars.className = "signal-bars";
  bars.setAttribute("aria-hidden", "true");
  const level = Math.max(1, Math.min(4, Math.ceil(signalPercent / 25)));
  for (let index = 1; index <= 4; index += 1) {
    const bar = document.createElement("span");
    if (index <= level) bar.className = "active";
    bars.append(bar);
  }
  return bars;
}

function wifiNetworkOption(network) {
  const option = document.createElement("label");
  option.className = "wifi-network";
  const input = document.createElement("input");
  input.type = "radio";
  input.name = "ssid";
  input.value = network.ssid;
  input.addEventListener("change", () => {
    selectedSsid = network.ssid;
    updatePasswordRequirement();
  });
  const body = document.createElement("span");
  body.className = "wifi-network-body";
  const radio = document.createElement("span");
  radio.className = "wifi-radio-mark";
  radio.setAttribute("aria-hidden", "true");
  const copy = document.createElement("span");
  copy.className = "wifi-network-copy";
  const title = document.createElement("span");
  title.className = "wifi-network-title";
  const ssid = document.createElement("strong");
  ssid.textContent = network.ssid;
  title.append(ssid);
  if (network.connected) {
    const current = document.createElement("span");
    current.className = "network-badge current";
    current.textContent = "Current";
    title.append(current);
  }
  const security = document.createElement("small");
  security.textContent = `${label(network.security)} security`;
  copy.append(title, security);
  const signal = document.createElement("span");
  signal.className = "signal-wrap";
  signal.setAttribute("aria-label", `${network.signal_percent}% signal`);
  const value = document.createElement("span");
  value.className = "signal-value";
  value.textContent = `${network.signal_percent}%`;
  signal.append(signalBars(network.signal_percent), value);
  body.append(radio, copy, signal);
  option.append(input, body);
  return option;
}

function renderWifiNetworks(networks) {
  wifiList.replaceChildren(...networks.map(wifiNetworkOption));
}

function updatePasswordRequirement() {
  const selected = scannedNetworks.get(selectedSsid);
  const security = selected?.security || "none";
  const policy = WIFI_SECURITY_POLICY[security];
  wifiPassword.disabled = !policy.passwordEnabled;
  wifiPassword.required = policy.passwordEnabled;
  wifiConnect.disabled = !policy.connectable || scanInProgress;
  wifiPasswordHelp.textContent = policy.help;
  if (policy.clearPassword) wifiPassword.value = "";
}

async function scanWifi() {
  const request = boundedRequest(WIFI_SCAN_REQUEST_TIMEOUT_MS);
  scanInProgress = true;
  selectedSsid = null;
  wifiRefresh.disabled = true;
  wifiRefresh.querySelector("span:last-child").textContent = "Scanning…";
  wifiList.setAttribute("aria-busy", "true");
  renderWifiEmpty("Scanning nearby networks", "This can take a few seconds.");
  setNetworkAction("Scanning for management networks…", "transition");
  updatePasswordRequirement();
  try {
    const response = await fetchJson("/api/v1/network/wifi", request.signal);
    scannedNetworks = new Map(response.networks.map((network) => [network.ssid, network]));
    if (response.networks.length) renderWifiNetworks(response.networks);
    else renderWifiEmpty("No networks found", "Move closer to the access point, then scan again.");
    setNetworkAction(response.networks.length ? "Select a network to continue." : "No supported broadcast networks were found.");
  } catch (_error) {
    scannedNetworks = new Map();
    renderWifiEmpty("Scan unavailable", "The existing management mode was not changed. Select Refresh to try again.", true);
    setNetworkAction("Wi-Fi scan failed. The existing management mode was not changed; try Refresh again.", "error");
  } finally {
    request.cancel();
    scanInProgress = false;
    wifiRefresh.disabled = false;
    wifiRefresh.querySelector("span:last-child").textContent = "Refresh";
    wifiList.setAttribute("aria-busy", "false");
    updatePasswordRequirement();
  }
}

async function requestStation(event) {
  event.preventDefault();
  const selected = scannedNetworks.get(selectedSsid);
  if (!selected) return;
  const password = selected.security === "open" ? null : wifiPassword.value;
  networkActionDeadline = performance.now() + NETWORK_ACTION_TIMEOUT_MS;
  setNetworkAction("Requesting station transition. This RAVE-Setup page will disconnect; continue at rave-pi.local:8080.", "transition");
  wifiConnect.disabled = true;
  const request = boundedRequest(NETWORK_ACTION_REQUEST_TIMEOUT_MS);
  try {
    const response = await postJson(
      "/api/v1/network/connect",
      { ssid: selected.ssid, password },
      request.signal,
    );
    if (!response.accepted) throw new Error("station request rejected");
    setNetworkAction("Connection request accepted. Join the selected Wi-Fi network, then open rave-pi.local:8080.", "transition");
    showHandoff();
  } catch (_error) {
    rejectNetworkAction("Unable to confirm the station request. Rejoin the available management network and refresh.");
  } finally {
    request.cancel();
    wifiPassword.value = "";
    updatePasswordRequirement();
  }
}

async function requestProvisioning() {
  networkActionDeadline = performance.now() + NETWORK_ACTION_TIMEOUT_MS;
  setNetworkAction("Requesting RAVE-Setup. This page may temporarily disconnect.", "transition");
  restoreProvisioning.disabled = true;
  const request = boundedRequest(NETWORK_ACTION_REQUEST_TIMEOUT_MS);
  try {
    const response = await postJson("/api/v1/network/provisioning", {}, request.signal);
    if (!response.accepted) throw new Error("provisioning request rejected");
  } catch (_error) {
    rejectNetworkAction("Unable to confirm the RAVE-Setup request. Rejoin the available management network and refresh.");
  } finally {
    request.cancel();
    restoreProvisioning.disabled = false;
  }
}

window.addEventListener("hashchange", () => showView(location.hash.slice(1)));
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && sidebar.classList.contains("visible")) {
    closeMenu();
    menuButton.focus();
  }
});
links.forEach((link) => {
  link.addEventListener("click", (event) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    showView(link.dataset.view);
  });
});
menuButton.addEventListener("click", () => {
  const visible = sidebar.classList.toggle("visible");
  underlay.hidden = !visible;
  menuButton.setAttribute("aria-expanded", String(visible));
  menuButtonLabel.textContent = visible ? "Close navigation" : "Open navigation";
});
underlay.addEventListener("click", closeMenu);
wifiRefresh.addEventListener("click", scanWifi);
wifiForm.addEventListener("submit", requestStation);
restoreProvisioning.addEventListener("click", requestProvisioning);
showView(location.hash.slice(1));
invalidateDynamic("status_starting", "starting");
refreshState();
