(() => {
  "use strict";

  const labels = {
    "01_000327_Track_ID.mp4": "000327：目标跟踪 / Track ID",
    "02_000345_Trend.mp4": "000345：人数趋势",
    "03_Fire_Response.mp4": "火情演示：安全响应",
  };
  const video = document.getElementById("showcase-video");
  const empty = document.getElementById("showcase-empty");
  const toolbar = document.getElementById("case-toolbar");

  function titleFor(item) {
    return labels[item.id] || item.name;
  }

  function selectShowcase(item, button) {
    document.querySelectorAll("[data-case-id]").forEach((node) => {
      node.classList.toggle("is-selected", node === button);
    });
    video.src = item.url;
    video.load();
    video.classList.remove("hidden");
    empty.classList.add("hidden");
  }

  async function loadShowcases() {
    try {
      const response = await fetch("/api/showcases", { cache: "no-store" });
      if (!response.ok) throw new Error("showcases unavailable");
      const payload = await response.json();
      const videos = Array.isArray(payload.videos) ? payload.videos : [];
      toolbar.replaceChildren();
      if (!videos.length) return;
      videos.forEach((item, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "case-button";
        button.dataset.caseId = item.id;
        button.textContent = titleFor(item);
        button.addEventListener("click", () => selectShowcase(item, button));
        toolbar.append(button);
        if (index === 0) selectShowcase(item, button);
      });
      toolbar.classList.remove("hidden");
    } catch (_) {
      empty.firstElementChild.textContent = "展示案例目录暂时不可读取";
    }
  }

  video.addEventListener("error", () => {
    empty.firstElementChild.textContent = "该展示视频无法播放";
    empty.classList.remove("hidden");
  });
  loadShowcases();
})();