/* 命令面板：Ctrl/Cmd+K 搜索公司、岗位与页面动作。
   依赖 app.js 暴露的全局词法绑定（state / call / go / goCompany / goJob / icon / esc）。 */
"use strict";

window.CommandPalette = (() => {
  let built = false;
  let open = false;
  let lastFocus = null;
  let active = 0;
  let pool = [];
  let items = [];
  let dataLoading = false;

  const ROUTES = [
    { label: "概览", sub: "OVERVIEW", hash: "#/", icon: "home" },
    { label: "岗位", sub: "JOBS", hash: "#/jobs", icon: "briefcase" },
    { label: "公司", sub: "COMPANIES", hash: "#/companies", icon: "building" },
    { label: "对比", sub: "COMPARE", hash: "#/compare", icon: "layers" },
    { label: "岗位对比", sub: "JOB COMPARE", hash: "#/job-compare", icon: "briefcase" },
    { label: "技能词云", sub: "SKILLS", hash: "#/skills", icon: "cloud" },
    { label: "简历", sub: "RESUME", hash: "#/resume", icon: "file" },
    { label: "模块", sub: "MODULES", hash: "#/modules", icon: "layers" },
    { label: "设置", sub: "CONFIG", hash: "#/settings", icon: "cog" },
  ];

  const ACTIONS = [
    {
      label: "对照简历找缺口", sub: "技能页 · 母版 skills[] 覆盖分析", icon: "check",
      run: () => go("#/skills?gap=1"),
    },
    {
      label: "采集新岗位", sub: "打开采集参数并聚焦关键词", icon: "play",
      run: () => {
        const focus = () => {
          const panel = document.querySelector("#crawl-panel");
          if (!panel) return;
          panel.open = true;
          panel.scrollIntoView({ block: "start", behavior: "smooth" });
          setTimeout(() => document.querySelector("#f-query")?.focus(), 80);
        };
        if (location.hash.startsWith("#/jobs")) focus();
        else { location.hash = "#/jobs"; setTimeout(focus, 120); }
      },
    },
    {
      label: "刷新数据库与配置", sub: "一次换新状态、数据、技能云与简历", icon: "refresh",
      run: () => refreshShell(true),
    },
    {
      label: "导出本地备份", sub: "关注与投递跟进 · JSON", icon: "download",
      run: () => exportBackup(),
    },
    {
      label: "只看已评分公司", sub: "公司页 · 本地筛选", icon: "filter",
      run: () => go("#/companies?grade=scored"),
    },
    {
      label: "查看关注的公司", sub: "公司页 · 本地关注清单", icon: "star",
      run: () => go("#/companies?grade=watch"),
    },
    {
      label: "查看关注的岗位", sub: "岗位页 · 本地关注清单", icon: "star",
      run: () => go("#/jobs?fit=watch"),
    },
    {
      label: "查看投递跟进", sub: "岗位页 · 已标记进度的岗位", icon: "briefcase",
      run: () => go("#/jobs?stage=tracked"),
    },
    {
      label: "全部待行动", sub: "岗位页 · Offer / 面试 / 超期未跟进", icon: "alert",
      run: () => go("#/jobs?stage=due"),
    },
    {
      label: "延后中的岗位", sub: "岗位页 · 按延后到期排序", icon: "clock",
      run: () => go("#/jobs?stage=snoozed"),
    },
    {
      label: "对比关注的公司", sub: "并排比较评分、五维与证据", icon: "layers",
      run: () => go("#/compare"),
    },
    {
      label: "面试中的岗位", sub: "岗位页 · 投递阶段筛选", icon: "chat",
      run: () => go("#/jobs?stage=interview"),
    },
    {
      label: "Offer 中的岗位", sub: "岗位页 · 投递阶段筛选", icon: "star",
      run: () => go("#/jobs?stage=offer"),
    },
    {
      label: "已接受的岗位", sub: "岗位页 · 投递阶段筛选", icon: "check",
      run: () => go("#/jobs?stage=accepted"),
    },
    {
      label: "配置模型与 Agent", sub: "设置页", icon: "cog",
      run: () => go("#/settings"),
    },
    {
      label: "键盘快捷键", sub: "↑↓ / ? Ctrl K 等", icon: "info",
      run: () => openKeysheet(),
    },
  ];

  function highlight(text, needle) {
    if (!needle) return esc(text);
    const lower = String(text).toLowerCase();
    const n = needle.toLowerCase();
    let at = lower.indexOf(n);
    if (at < 0) return esc(text);
    let out = "";
    let cursor = 0;
    while (at >= 0) {
      out += esc(String(text).slice(cursor, at)) + "<mark>" + esc(String(text).slice(at, at + n.length)) + "</mark>";
      cursor = at + n.length;
      at = lower.indexOf(n, cursor);
    }
    return out + esc(String(text).slice(cursor));
  }

  // 子序列匹配：连续命中加分，返回 -1 表示不匹配。
  function score(text, needle) {
    const hay = String(text || "").toLowerCase();
    const q = needle.toLowerCase();
    if (!q) return 0;
    let at = 0;
    let total = 0;
    let streak = 0;
    for (const ch of q) {
      const found = hay.indexOf(ch, at);
      if (found < 0) return -1;
      streak = found === at ? streak + 1 : 0;
      total += 8 - Math.min(6, found - at) + streak * 3;
      at = found + 1;
    }
    return total - Math.min(8, hay.length * 0.01);
  }

  const fitLabel = (job) => (job.fit
    ? `适配 ${fmt(job.fit.total)}${fitNeutral(job.fit) ? "（中性）" : ""}`
    : "未适配");
  const stageText = (job) => {
    const rec = trackOf(job.id);
    if (!rec) return "";
    const label = (stageMeta(rec.stage) || {}).label || rec.stage;
    const snoozed = snoozedLabel(rec);
    if (!rec.note && !snoozed) return label;
    const note = rec.note ? (rec.note.length > 24 ? rec.note.slice(0, 24) + "…" : rec.note) : "";
    return [label, note, snoozed].filter(Boolean).join(" · ");
  };
  const stageSearch = (job) => {
    const rec = trackOf(job.id);
    if (!rec) return "";
    return [(stageMeta(rec.stage) || {}).label || rec.stage, rec.note, snoozedLabel(rec), snoozeEnd(rec) ? "延后" : ""]
      .filter(Boolean).join(" ");
  };

  function allItems() {
    const list = [];
    ROUTES.forEach((route) => list.push({
      group: "页面", label: route.label, sub: route.sub, icon: route.icon,
      run: () => go(route.hash),
    }));
    ACTIONS.forEach((action) => list.push({
      group: "动作", label: action.label, sub: action.sub, icon: action.icon,
      run: action.run,
    }));
    if (recentItems().length) {
      list.push({
        group: "动作", label: "清空最近查看", sub: "命令面板 · 仅清除本机浏览记录", icon: "refresh",
        run: () => {
          clearRecent();
          document.dispatchEvent(new CustomEvent("recentchange"));
          toast("已清空最近查看");
        },
      });
    }
    const data = state.data || {};
    const companyByKey = new Map((data.companies || []).map((company) => [company.company_key, company]));
    const jobById = new Map((data.jobs || []).map((job) => [job.id, job]));
    const recents = recentItems().map((entry) => {
      if (entry.kind === "company") {
        const company = companyByKey.get(entry.id);
        if (!company) return null;
        return {
          group: "最近", label: company.name, icon: "clock", key: `company:${company.company_key}`,
          sub: [
            company.score?.total != null ? `${fmt(company.score.total)} 分` : "未评分",
            `${company.job_count ?? 0} 个岗位`, "最近查看",
          ].join(" · "),
          search: `${company.name} ${company.company_key || ""}`,
          run: () => goCompany(company.company_key),
        };
      }
      const job = jobById.get(entry.id);
      if (!job) return null;
      return {
        group: "最近", label: job.title, icon: "clock", key: `job:${job.id}`,
        sub: [job.company, job.city, fitLabel(job), stageText(job), "最近查看"]
          .filter(Boolean).join(" · "),
        search: `${job.title} ${job.company || ""} ${job.city || ""} ${stageSearch(job)}`,
        run: () => goJob(job.id),
      };
    }).filter(Boolean);
    const recentKeys = new Set(recents.map((item) => item.key));
    list.push(...recents);
    [...(data.companies || [])]
      .filter((company) => !recentKeys.has(`company:${company.company_key}`))
      .sort((a, b) => ((b.score?.total ?? -1) - (a.score?.total ?? -1)))
      .forEach((company) => list.push({
        group: "公司", label: company.name, icon: "building",
        sub: [
          company.score?.total != null ? `${fmt(company.score.total)} 分` : "未评分",
          `${company.job_count ?? 0} 个岗位`,
        ].join(" · "),
        search: `${company.name} ${company.company_key || ""}`,
        run: () => goCompany(company.company_key),
      }));
    [...(data.jobs || [])]
      .filter((job) => !recentKeys.has(`job:${job.id}`))
      .sort((a, b) => ((b.fit?.total ?? -1) - (a.fit?.total ?? -1)))
      .forEach((job) => list.push({
        group: "岗位", label: job.title, icon: "briefcase",
        sub: [job.company, job.city, fitLabel(job), stageText(job)].filter(Boolean).join(" · "),
        search: `${job.title} ${job.company || ""} ${job.city || ""} ${stageSearch(job)}`,
        run: () => goJob(job.id),
      }));
    return list;
  }

  function searchItems(query) {
    const needle = query.trim();
    if (!needle) {
      const recents = pool.filter((item) => item.group === "最近").slice(0, 4);
      const companies = pool.filter((item) => item.group === "公司").slice(0, 5);
      const jobs = pool.filter((item) => item.group === "岗位").slice(0, 5);
      return [...recents,
        ...pool.filter((item) => item.group !== "最近" && item.group !== "公司" && item.group !== "岗位"),
        ...companies, ...jobs];
    }
    return pool
      .map((item) => ({ item, rank: Math.max(score(item.label, needle), score(item.search || "", needle) - 1) }))
      .filter((entry) => entry.rank >= 0)
      .sort((a, b) => b.rank - a.rank)
      .slice(0, 20)
      .map((entry) => entry.item);
  }

  function build() {
    if (built) return;
    const host = document.createElement("div");
    host.id = "palette";
    host.hidden = true;
    host.innerHTML = `
      <div class="palette-scrim" data-palette-close></div>
      <div class="palette-panel" role="dialog" aria-modal="true" aria-label="快速搜索">
        <div class="palette-input">
          ${icon("search")}
          <input id="palette-q" type="text" autocomplete="off" spellcheck="false"
                 placeholder="搜索公司、岗位，或输入动作…" role="combobox"
                 aria-expanded="true" aria-controls="palette-list" aria-autocomplete="list">
          <kbd class="kbd">ESC</kbd>
        </div>
        <div class="palette-list" id="palette-list" role="listbox" aria-label="结果"></div>
        <div class="palette-foot">
          <span><kbd class="kbd">↑</kbd><kbd class="kbd">↓</kbd> 选择</span>
          <span><kbd class="kbd">Enter</kbd> 打开</span>
          <span><kbd class="kbd">Ctrl K</kbd> 关闭</span>
          <span class="palette-count" id="palette-count"></span>
        </div>
      </div>`;
    document.body.appendChild(host);
    host.addEventListener("click", (event) => {
      if (event.target.closest("[data-palette-close]")) close();
    });
    $("#palette-q").addEventListener("input", () => {
      active = 0;
      draw();
    });
    host.addEventListener("keydown", onKey);
    built = true;
  }

  function draw() {
    const query = ($("#palette-q")?.value || "").trim();
    const list = searchItems(query);
    items = list;
    const box = $("#palette-list");
    if (!list.length) {
      active = -1;
      box.innerHTML = `<div class="palette-empty">没有匹配结果<br><span>换个关键词，或先刷新数据</span></div>`;
      $("#palette-count").textContent = "";
      $("#palette-q").removeAttribute("aria-activedescendant");
      return;
    }
    active = Math.max(0, Math.min(list.length - 1, active));
    box.innerHTML = list.map((item, index) => `
      <div class="palette-item ${index === active ? "active" : ""}" id="pal-opt-${index}"
           role="option" aria-selected="${index === active}" data-index="${index}">
        ${icon(item.icon, "ni pal-icon")}
        <span class="pal-text">
          <b>${highlight(item.label, query)}</b>
          <em>${esc(item.sub)}</em>
        </span>
        <span class="pal-type">${esc(item.group)}</span>
      </div>`).join("");
    $("#palette-count").textContent = `${list.length} 项`;
    $("#palette-q").setAttribute("aria-activedescendant", `pal-opt-${active}`);
    $$(".palette-item", box).forEach((node, index) => {
      node.addEventListener("click", () => choose(list[index]));
      node.addEventListener("pointermove", () => {
        if (index === active) return;
        active = index;
        $$(".palette-item", box).forEach((el, i) => {
          el.classList.toggle("active", i === active);
          el.setAttribute("aria-selected", String(i === active));
        });
        $("#palette-q").setAttribute("aria-activedescendant", `pal-opt-${active}`);
      });
    });
    box.scrollTop = 0;
  }

  function choose(item) {
    if (!item) return;
    close();
    setTimeout(item.run, 0);
  }

  function onKey(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (!items.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      active = (active + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      const box = $("#palette-list");
      $$(".palette-item", box).forEach((el, i) => {
        el.classList.toggle("active", i === active);
        el.setAttribute("aria-selected", String(i === active));
      });
      $("#palette-q").setAttribute("aria-activedescendant", `pal-opt-${active}`);
      $(`#pal-opt-${active}`)?.scrollIntoView({ block: "nearest" });
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      choose(items[active]);
    }
  }

  function openPalette() {
    build();
    lastFocus = document.activeElement;
    open = true;
    active = 0;
    const host = $("#palette");
    host.hidden = false;
    document.documentElement.classList.add("palette-open");
    $("#palette-q").value = "";
    pool = allItems();
    draw();
    setTimeout(() => $("#palette-q")?.focus(), 20);
    if (!state.data && !dataLoading) {
      dataLoading = true;
      call("data").then((data) => {
        dataLoading = false;
        if (data) state.data = data;
        if (open) { pool = allItems(); draw(); }
      });
    }
  }

  function close() {
    if (!built || !open) return;
    open = false;
    const input = $("#palette-q");
    const trapped = !!input && document.activeElement === input;
    $("#palette").hidden = true;
    document.documentElement.classList.remove("palette-open");
    // 隐藏输入框仍持有焦点会吞掉所有单键快捷键
    if (trapped) input.blur();
    if (lastFocus && typeof lastFocus.focus === "function" && lastFocus !== document.body) lastFocus.focus();
  }

  function toggle() {
    if (open) close();
    else openPalette();
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      close();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      const sheet = document.querySelector("#keysheet");
      if (sheet && !sheet.hidden) closeKeysheet();
      toggle();
    }
  }, true);

  return { open: openPalette, close, toggle };
})();
