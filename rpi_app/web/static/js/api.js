(function () {
  const phaseLabels = { WARMING: "预热中", CALIBRATING: "现场基线采集中", READY: "已就绪" };
  const stateLabels = {
    NORMAL: "系统正常", WARNING: "一般预警", CROWD: "拥挤预警",
    DANGER: "火情报警", FIRE: "火情报警", COMM_TIMEOUT: "通信异常"
  };
  window.HuianApi = {
    missing(value) { return value === null || value === undefined || value === ""; },
    text(value, fallback = "--") { return this.missing(value) ? fallback : String(value); },
    online(value) { return value === true ? "在线" : value === false ? "未连接" : "等待数据"; },
    bool(value, yes, no, waiting = "未连接") { return value === true ? yes : value === false ? no : waiting; },
    phase(value) { return this.missing(value) ? "未连接" : (phaseLabels[value] || String(value)); },
    number(value, digits = 0, suffix = "", fallback = "--") { return this.missing(value) ? fallback : `${Number(value).toFixed(digits)}${suffix}`; },
    direction(value) { return value === "LEFT" ? "←" : value === "RIGHT" ? "→" : ""; },
    systemState(value, fallback = "等待数据") { return this.missing(value) ? fallback : (stateLabels[value] || String(value)); },
    visionRisk(value) { return this.missing(value) ? "等待数据" : (stateLabels[value] || String(value)); },
    riskClass(id, value) { const node = document.getElementById(id); if (node) node.className = `risk-${value || ""}`; },
    async fetchStatus() { const response = await fetch("/api/status", { cache: "no-store" }); if (!response.ok) throw new Error("status unavailable"); return response.json(); },
    set(id, value) { const node = document.getElementById(id); if (node) node.textContent = value; },
    schedule(render) { const update = async () => { try { render(await this.fetchStatus()); } catch (_) { render({ snapshot_available: false }); } finally { setTimeout(update, 750); } }; update(); }
  };
}());