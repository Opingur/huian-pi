(() => {
  "use strict";

  const api = window.HuianApi;
  const byId = (id) => document.getElementById(id);
  const setText = (id, value) => { byId(id).textContent = value; };
  const hasValue = (value) => value !== null && value !== undefined && value !== "";
  const numberText = (value, digits) => hasValue(value) ? Number(value).toFixed(digits) : "\u2014";
  const labels = {
    NORMAL: "\u6b63\u5e38", WARNING: "\u4e00\u822c\u9884\u8b66", CROWD: "\u62e5\u6324\u9884\u8b66",
    DANGER: "\u706b\u60c5\u62a5\u8b66", FIRE: "\u706b\u60c5\u62a5\u8b66", COMM_TIMEOUT: "\u901a\u4fe1\u5f02\u5e38"
  };
  const riskLabel = (value) => labels[value] || "\u6682\u65e0\u6570\u636e";
  const eventText = (value) => !hasValue(value) || String(value).toLowerCase() === "none" ? "\u6682\u65e0\u4e8b\u4ef6" : String(value);

  const drawer = byId("side-drawer");
  const backdrop = byId("drawer-backdrop");
  const toggle = byId("sidebar-toggle");
  const close = byId("sidebar-close");
  const image = byId("dashboard-image");
  const frame = byId("monitor-frame");
  const fallback = byId("frame-fallback");
  let nextFrameAt = 0;

  function setDrawer(open, panelId) {
    document.body.classList.toggle("drawer-open", open);
    drawer.classList.toggle("is-open", open);
    backdrop.classList.toggle("hidden", !open);
    drawer.setAttribute("aria-hidden", String(!open));
    toggle.setAttribute("aria-expanded", String(open));
    if (open && panelId) byId(panelId).scrollIntoView({ block: "start", behavior: "smooth" });
    if (open && !panelId) close.focus();
  }
  toggle.addEventListener("click", () => setDrawer(!drawer.classList.contains("is-open")));
  close.addEventListener("click", () => setDrawer(false));
  backdrop.addEventListener("click", () => setDrawer(false));
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") setDrawer(false); });
  document.querySelectorAll("[data-panel]").forEach((button) => {
    button.addEventListener("click", () => setDrawer(true, button.dataset.panel));
  });

  function frameState(kind) {
    frame.className = "monitor-frame is-" + kind;
    fallback.classList.toggle("hidden", kind === "ready");
  }
  image.addEventListener("load", () => frameState("ready"));
  image.addEventListener("error", () => frameState("waiting"));

  function refreshFrame(status) {
    if (status.snapshot_available !== true) {
      frameState("waiting");
      return;
    }
    const now = Date.now();
    if (now < nextFrameAt) return;
    nextFrameAt = now + 750;
    image.src = "/api/frame.jpg?ts=" + now;
  }

  function updateStatus(status) {
    const ready = status.snapshot_available === true;
    const manual = status.manual_alarm === true;
    const cameraOnline = status.camera_online === true;
    const esp32Online = status.esp32_online === true;
    const systemState = status.system_state || status.vision_risk;
    const systemText = ready ? (manual ? "\u4eba\u5de5\u62a5\u8b66" : riskLabel(systemState)) : "\u7b49\u5f85\u6570\u636e";
    const riskText = ready ? riskLabel(status.vision_risk) : "\u6682\u65e0\u6570\u636e";
    const people = hasValue(status.total_people) ? String(status.total_people) : "\u2014";
    const crowd = numberText(status.crowd_index, 2);

    const runtime = byId("snapshot-state");
    runtime.className = "runtime-state " + (ready ? "is-live" : "is-waiting");
    runtime.textContent = ready ? "\u25cf \u7cfb\u7edf\u8fd0\u884c\u4e2d" : "\u25cf \u7b49\u5f85\u73b0\u573a\u7cfb\u7edf";

    setText("system-state", systemText);
    setText("total-people", people);
    setText("vision-risk", riskText);
    setText("crowd-index", crowd);
    setText("drawer-people", people + "\u4eba");
    setText("drawer-risk", riskText);
    setText("drawer-crowd", crowd);
    setText("current-event", eventText(status.current_event));
    setText("running-event", eventText(status.running_event));
    setText("vision-state", cameraOnline ? "\u6b63\u5f0f\u89c6\u89c9\u94fe\u8def\u6b63\u5728\u8fd0\u884c" : (ready ? "\u6444\u50cf\u5934\u672a\u8fde\u63a5" : "\u7b49\u5f85\u6570\u636e"));

    const smoke = status.mq2_warning === true ? "\u70df\u96fe\u62a5\u8b66" : (status.mq2_ready ? "\u76d1\u6d4b\u6b63\u5e38" : (ready ? "\u7b49\u5f85\u6821\u51c6\u6216\u8fde\u63a5" : "\u7b49\u5f85\u6570\u636e"));
    setText("smoke-state", smoke);
    setText("temperature", status.temperature_valid === true ? numberText(status.temperature_c, 1) : "\u2014");
    setText("humidity", hasValue(status.humidity_percent) ? numberText(status.humidity_percent, 1) : "\u2014");
    setText("device-camera", cameraOnline ? "\u5df2\u8fde\u63a5" : (ready ? "\u672a\u8fde\u63a5" : "\u7b49\u5f85\u6570\u636e"));
    setText("camera-online", cameraOnline ? "\u5df2\u8fde\u63a5" : (ready ? "\u672a\u8fde\u63a5" : "\u7b49\u5f85\u6570\u636e"));
    setText("esp32-online", esp32Online ? "\u5df2\u8fde\u63a5" : (ready ? "\u672a\u8fde\u63a5" : "\u7b49\u5f85\u8fde\u63a5"));
    setText("communication-state", esp32Online ? "UART \u6b63\u5e38" : (ready ? "\u7b49\u5f85\u72b6\u6001\u56de\u4f20" : "\u7b49\u5f85\u6570\u636e"));
    setText("manual-alarm", manual ? "\u4eba\u5de5\u62a5\u8b66\u5df2\u89e6\u53d1" : "\u672a\u89e6\u53d1");
    setText("manual-detail", manual ? "\u8bf7\u6559\u5e08\u53ca\u65f6\u67e5\u770b\u73b0\u573a\u60c5\u51b5\u3002" : "\u5f53\u524d\u672a\u6536\u5230\u6559\u5e08\u4eba\u5de5\u62a5\u8b66\u3002");
    const direction = byId("recommended-direction");
    direction.classList.toggle("hidden", !hasValue(status.recommended_direction));
    if (hasValue(status.recommended_direction)) setText("recommended-direction", String(status.recommended_direction));
    byId("manual-banner").classList.toggle("hidden", !manual);

    refreshFrame(status);
  }

  api.schedule(updateStatus);
})();