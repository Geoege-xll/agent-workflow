/* 本脚本只驱动一份设计样稿内的示例状态，不实现生产工作区的文件加载或路由。
   所有可选状态均来自本页普通锚点与现有画面节点，不读取文档、不联网、不建立页面登记副本。 */
(() => {
  "use strict";

  const workspace = document.getElementById("workspace-design");
  const sidebar = document.getElementById("workspace-sidebar");
  const sidebarToggle = document.getElementById("workspace-sidebar-toggle");
  const sidebarToggleLabel = document.getElementById("workspace-sidebar-toggle-label");
  const returnButton = document.getElementById("workspace-back-to-navigation");
  const title = document.getElementById("workspace-page-title");
  const description = document.getElementById("workspace-page-description");
  const groupName = document.getElementById("workspace-current-group");
  const status = document.getElementById("workspace-status");
  const links = Array.from(workspace.querySelectorAll("a[data-demo-page]"));
  const screens = Array.from(workspace.querySelectorAll("[data-demo-screen]"));
  let currentLink = links[0];

  /* 只接受由本地示例链接明确指向的同页节点；未知 hash 不能转成文件路径。
     查找来源是 HTML 本身，新增或调整示例时不需要维护第二份脚本数组。 */
  function screenFor(link) {
    return screens.find((screen) => "#" + screen.id === link.getAttribute("href"));
  }

  /* 侧栏开关始终留在右侧页头，收起后仍可通过键盘或触控恢复。
     hidden 同时移除不可见侧栏的可聚焦项，避免 Tab 进入屏幕外的导航。 */
  function setSidebarExpanded(expanded) {
    sidebar.hidden = !expanded;
    workspace.classList.toggle("is-sidebar-collapsed", !expanded);
    sidebarToggle.setAttribute("aria-expanded", String(expanded));
    sidebarToggleLabel.textContent = expanded ? "收起侧栏" : "展开侧栏";
  }

  /* 每次切换同步唯一画面、可访问选中状态与可见文字标记。
     焦点和选中分开：主动选页后阅读页头，浏览器历史恢复时保留原来的焦点位置。 */
  function selectPage(link, moveFocus) {
    const screen = screenFor(link);
    if (!screen) return;
    currentLink = link;
    links.forEach((item) => {
      const selected = item === link;
      if (selected) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
      item.querySelector("[data-current-marker]").hidden = !selected;
    });
    screens.forEach((item) => { item.hidden = item !== screen; });
    title.textContent = screen.dataset.screenTitle;
    description.textContent = screen.dataset.screenDescription;
    groupName.textContent = screen.dataset.screenGroup;
    status.textContent = "当前预览：" + screen.dataset.screenTitle + "。";
    if (moveFocus) title.focus({ preventScroll: true });
  }

  /* 页面锚点可直接打开，也可沿浏览器前进/后退恢复。未知值只选择默认示例，
     不执行动态 HTML、脚本拼接或任意路径导航。 */
  function restoreFromHash() {
    const registered = links.find((link) => link.getAttribute("href") === window.location.hash);
    selectPage(registered || links[0], false);
    if (registered) registered.closest("details").open = true;
  }

  links.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const target = link.getAttribute("href");
      /* 只修改同文档锚点并保留前进/后退；pushState 避免原生锚点跳动把页头焦点滚出视野。
         目标严格来自本页链接，不依赖 file:// 下的跨文档操作。 */
      if (window.location.hash !== target) window.history.pushState(null, "", target);
      selectPage(link, true);
    });
  });

  sidebarToggle.addEventListener("click", () => {
    const expanded = sidebarToggle.getAttribute("aria-expanded") !== "true";
    setSidebarExpanded(expanded);
    status.textContent = expanded ? "页面侧栏已展开。" : "页面侧栏已收起，当前预览保持不变。";
  });

  returnButton.addEventListener("click", () => {
    /* 返回定位不改变页面选择；先恢复布局和所在分组，再移交焦点。 */
    setSidebarExpanded(true);
    currentLink.closest("details").open = true;
    /* 返回定位允许浏览器把目标滚入视野，避免短窗口或缩放后只移动焦点却看不到入口。 */
    currentLink.focus();
    status.textContent = "已返回页面导航，当前页面为" + title.textContent + "。";
  });

  window.addEventListener("hashchange", restoreFromHash);
  window.addEventListener("popstate", restoreFromHash);
  restoreFromHash();
})();
