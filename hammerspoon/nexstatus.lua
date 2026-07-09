-- NexStatus — Apple Control Center style glass MenuBar
-- Title: Cl · Cx · Go · G · M  |  Click → vibrancy card
-- Collector: nexstatus/collector.py → ~/.cache/nexstatus/status.json

local M = {}

local item = nil
local timer = nil
local panel = nil

local HOME = os.getenv("HOME") or ""
local ROOT = os.getenv("NEXSTATUS_HOME") or (HOME .. "/Developer/NexStatus")
local SNAP = (os.getenv("NEXSTATUS_CACHE") or (HOME .. "/.cache/nexstatus")) .. "/status.json"
local PY = ROOT .. "/nexstatus/collector.py"
local PYTHON = "/usr/bin/python3"
local PANEL_W = 348
local PANEL_H = 680

local function shell(cmd)
  local output, status = hs.execute(cmd, true)
  if status then
    return (output or ""):gsub("%s+$", "")
  end
  return ""
end

local function readSnapshot()
  local f = io.open(SNAP, "r")
  if not f then return nil end
  local raw = f:read("*a")
  f:close()
  if not raw or raw == "" then return nil end
  local ok, data = pcall(hs.json.decode, raw)
  if ok and type(data) == "table" then return data end
  return nil
end

local function refreshSnapshot(forceRemote)
  local flag = forceRemote and " --force" or ""
  shell(string.format("%s %q%s 2>/dev/null", PYTHON, PY, flag))
end

local function pct(v)
  if v == nil then return nil end
  return tonumber(v)
end

local function pctText(v)
  if v == nil then return "—" end
  return string.format("%d%%", v)
end

local function fmtReset(ts)
  if type(ts) ~= "number" then return "—" end
  local delta = math.floor(ts - os.time())
  if delta <= 0 then return "已重置" end
  local h = math.floor(delta / 3600)
  local m = math.floor((delta % 3600) / 60)
  if h >= 24 then
    return string.format("%d 天 %d 小時後", math.floor(h / 24), h % 24)
  end
  if h > 0 then
    return string.format("%d 小時 %d 分後", h, m)
  end
  return string.format("%d 分後", m)
end

local function barColor(v)
  if v == nil then return "#8E8E93" end
  if v >= 90 then return "#FF453A" end -- system red
  if v >= 70 then return "#FF9F0A" end -- system orange
  if v >= 40 then return "#0A84FF" end -- system blue
  return "#30D158" -- system green
end

local function esc(s)
  if s == nil then return "" end
  return tostring(s)
    :gsub("&", "&amp;")
    :gsub("<", "&lt;")
    :gsub(">", "&gt;")
    :gsub('"', "&quot;")
end

local function rowHTML(opts)
  -- opts: name, badge, main, sub, bars = {{label, pct}, ...}
  local bars = ""
  for _, b in ipairs(opts.bars or {}) do
    local p = pct(b.pct)
    local w = p or 0
    local col = barColor(p)
    local val = p and (tostring(p) .. "%") or "—"
    bars = bars .. string.format([[
      <div class="meter">
        <div class="meter-top">
          <span class="meter-label">%s</span>
          <span class="meter-val" style="color:%s">%s</span>
        </div>
        <div class="track"><div class="fill" style="width:%d%%;background:%s"></div></div>
      </div>
    ]], esc(b.label), col, val, w, col)
  end

  return string.format([[
    <section class="card">
      <header class="card-head">
        <div class="id">
          <span class="dot" style="background:%s"></span>
          <span class="name">%s</span>
          %s
        </div>
        <div class="main">%s</div>
      </header>
      <div class="sub">%s</div>
      %s
    </section>
  ]],
    opts.accent or "#0A84FF",
    esc(opts.name),
    opts.badge and ('<span class="badge">' .. esc(opts.badge) .. "</span>") or "",
    esc(opts.main or ""),
    esc(opts.sub or ""),
    bars
  )
end

local function buildHTML(s)
  s = s or {}
  local host = s.host or {}
  local cl = s.claude or {}
  local cx = s.codex or {}
  local go = s.opencode_go or {}
  local gk = s.grok or {}
  local goLocal = go["local"] or {}
  local goCaps = go.caps or {}

  local clMain = cl.ok and (pctText(cl.five_hour_pct) .. " · 5h") or "離線"
  local clSub = cl.ok
      and string.format("7 日 %s · 重置 %s", pctText(cl.seven_day_pct), fmtReset(cl.five_hour_resets_at))
    or (cl.error or "尚無 Claude usage 資料")

  local cxMain = cx.ok and (pctText(cx.five_hour_pct) .. " · 5h") or "離線"
  local cxSub = cx.ok
      and string.format("%s · 7 日 %s · %s", tostring(cx.plan_type or "plan"), pctText(cx.seven_day_pct), fmtReset(cx.five_hour_resets_at))
    or (cx.error or "尚無 Codex usage 資料")

  -- OpenCode Go
  local goMain, goSub, goBars
  if go.live_status == "capped" then
    local lim = tostring(go.limit_name or "limit")
    goMain = "已滿 · " .. lim
    local resetTxt = "—"
    if type(go.resets_in_sec) == "number" then
      resetTxt = fmtReset(os.time() + go.resets_in_sec)
    end
    goSub = string.format("%s · 重置 %s · 本機 5h %s 次",
      tostring(go.message or "額度已滿"):gsub(" To continue.*", ""),
      resetTxt,
      tostring(goLocal.req_5h or 0))
    goBars = {
      { label = "官方額度（" .. lim .. "）", pct = 100 },
    }
  elseif go.ok then
    goMain = pctText(go.used_pct) .. " · 估算"
    goSub = string.format(
      "$10/mo · 上限 5h $%s / 週 $%s / 月 $%s · 本機 5h %s 次 · ledger $%.2f/月(低估)",
      tostring(goCaps.five_hour_usd or 12),
      tostring(goCaps.weekly_usd or 30),
      tostring(goCaps.monthly_usd or 60),
      tostring(goLocal.req_5h or 0),
      tonumber(goLocal.shadow_usd_30d) or 0
    )
    goBars = {
      { label = "本機估算（非官方精確值）", pct = go.used_pct },
    }
  else
    goMain = "離線"
    goSub = go.error or "尚無 OpenCode Go key"
    goBars = {}
  end

  local gkMain = gk.ok and (pctText(gk.used_pct) .. " · 月額度") or "離線"
  local gkUsed = gk.used and string.format("%.0f", gk.used) or "—"
  local gkLim = gk.monthly_limit and string.format("%.0f", gk.monthly_limit) or "—"
  local gkSub = gk.ok
      and string.format("%s / %s credits · %s → %s",
        gkUsed, gkLim,
        tostring(gk.period_start or ""):sub(1, 10),
        tostring(gk.period_end or ""):sub(1, 10))
    or (gk.error or "請先 grok login")

  local memMain = string.format("MEM %s", pctText(host.mem_pct))
  local memSub = string.format("%.1f / %.0f GB · Swap %.0f MB · %s · CPU %s",
    host.mem_used_gb or 0,
    host.mem_total_gb or 0,
    host.swap_mb or 0,
    (host.pressure or "—"):gsub(" 🟢", ""):gsub(" 🟡", ""):gsub(" 🔴", ""),
    pctText(host.cpu_pct)
  )

  local cards = table.concat({
    rowHTML({
      name = "Claude",
      badge = cl.model or nil,
      accent = "#D97757",
      main = clMain,
      sub = clSub,
      bars = cl.ok and {
        { label = "5 小時視窗", pct = cl.five_hour_pct },
        { label = "7 日視窗", pct = cl.seven_day_pct },
      } or {},
    }),
    rowHTML({
      name = "Codex",
      badge = cx.plan_type,
      accent = "#10A37F",
      main = cxMain,
      sub = cxSub,
      bars = cx.ok and {
        { label = "5 小時視窗", pct = cx.five_hour_pct },
        { label = "7 日視窗", pct = cx.seven_day_pct },
      } or {},
    }),
    rowHTML({
      name = "OpenCode Go",
      badge = go.price or "$10/mo",
      accent = "#FF9F0A",
      main = goMain,
      sub = goSub,
      bars = goBars,
    }),
    rowHTML({
      name = "Grok",
      badge = "credits",
      accent = "#BF5AF2", -- system purple
      main = gkMain,
      sub = gkSub,
      bars = gk.ok and {
        { label = "本月額度", pct = gk.used_pct },
      } or {},
    }),
    rowHTML({
      name = "Mac",
      badge = "Mac",
      accent = "#0A84FF",
      main = memMain,
      sub = memSub,
      bars = {
        { label = "記憶體", pct = host.mem_pct },
        { label = "CPU", pct = host.cpu_pct },
      },
    }),
  }, "\n")

  local updated = ""
  if s.polled_at then
    updated = "更新 " .. tostring(s.polled_at):sub(12, 19) .. " UTC"
  end

  return string.format([[<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  :root {
    color-scheme: dark;
    --bg: rgba(28, 28, 30, 0.78);
    --card: rgba(44, 44, 46, 0.72);
    --card-border: rgba(255,255,255,0.08);
    --label: rgba(235,235,245,0.6);
    --text: #F5F5F7;
    --sub: rgba(235,235,245,0.48);
    --track: rgba(120,120,128,0.28);
    --sep: rgba(84,84,88,0.55);
    --blue: #0A84FF;
  }
  * { box-sizing: border-box; -webkit-font-smoothing: antialiased; }
  html, body {
    margin: 0; padding: 0;
    width: 100%%; height: 100%%;
    overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display",
      "Helvetica Neue", "PingFang TC", "Noto Sans TC", sans-serif;
    background: transparent;
    color: var(--text);
  }
  .shell {
    height: 100%%;
    padding: 11px 11px 10px;
    background:
      radial-gradient(120%% 80%% at 0%% 0%%, rgba(10,132,255,0.14), transparent 52%%),
      radial-gradient(100%% 70%% at 100%% 100%%, rgba(191,90,242,0.10), transparent 48%%),
      var(--bg);
    border-radius: 16px;
    border: 0.5px solid rgba(255,255,255,0.16);
    box-shadow:
      0 22px 56px rgba(0,0,0,0.48),
      0 0 0 0.5px rgba(0,0,0,0.28) inset;
    backdrop-filter: blur(48px) saturate(190%%);
    -webkit-backdrop-filter: blur(48px) saturate(190%%);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .top {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    padding: 2px 4px 4px;
  }
  .title {
    font-size: 13px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  .title span {
    color: var(--label);
    font-weight: 500;
    margin-left: 6px;
    font-size: 12px;
  }
  .stamp {
    font-size: 11px;
    color: var(--sub);
    font-variant-numeric: tabular-nums;
  }
  .list {
    display: flex;
    flex-direction: column;
    gap: 7px;
    flex: 1;
    min-height: 0;
    overflow: auto;
  }
  .card {
    background: var(--card);
    border: 0.5px solid var(--card-border);
    border-radius: 12px;
    padding: 9px 11px 10px;
  }
  .card-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .id {
    display: flex;
    align-items: center;
    gap: 7px;
    min-width: 0;
  }
  .dot {
    width: 8px; height: 8px;
    border-radius: 50%%;
    flex: 0 0 auto;
    box-shadow: 0 0 0 2px rgba(255,255,255,0.08);
  }
  .name {
    font-size: 13px;
    font-weight: 600;
    letter-spacing: -0.02em;
  }
  .badge {
    font-size: 10px;
    font-weight: 600;
    color: var(--label);
    background: rgba(120,120,128,0.24);
    border-radius: 999px;
    padding: 2px 7px;
    letter-spacing: 0.01em;
    text-transform: none;
  }
  .main {
    font-size: 15px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.03em;
    white-space: nowrap;
  }
  .sub {
    margin-top: 4px;
    font-size: 11px;
    line-height: 1.35;
    color: var(--sub);
    font-variant-numeric: tabular-nums;
  }
  .meter { margin-top: 8px; }
  .meter-top {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
  }
  .meter-label {
    font-size: 11px;
    color: var(--label);
    font-weight: 500;
  }
  .meter-val {
    font-size: 11px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .track {
    height: 4px;
    border-radius: 999px;
    background: var(--track);
    overflow: hidden;
  }
  .fill {
    height: 100%%;
    border-radius: 999px;
    transition: width 0.35s cubic-bezier(0.22, 1, 0.36, 1);
  }
  .actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    padding-top: 2px;
  }
  .btn {
    appearance: none;
    border: 0;
    border-radius: 10px;
    height: 34px;
    font: inherit;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: -0.01em;
    cursor: pointer;
    text-decoration: none;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text);
    background: rgba(120,120,128,0.28);
    transition: background 0.15s ease, transform 0.1s ease;
  }
  .btn:active { transform: scale(0.98); }
  .btn.primary {
    background: var(--blue);
    color: white;
  }
  .btn.ghost {
    background: transparent;
    color: var(--label);
    grid-column: 1 / -1;
    height: 28px;
    font-weight: 500;
  }
</style>
</head>
<body>
  <div class="shell">
    <div class="top">
      <div class="title">NexStatus<span>usage</span></div>
      <div class="stamp">%s</div>
    </div>
    <div class="list">
      %s
    </div>
    <div class="actions">
      <a class="btn primary" href="nexstatus://refresh">重新整理</a>
      <a class="btn" href="nexstatus://stats">Stats</a>
      <a class="btn ghost" href="nexstatus://close">關閉</a>
    </div>
  </div>
</body>
</html>]], esc(updated), cards)
end

local function positionPanel()
  if not panel then return end
  local screen = hs.screen.mainScreen()
  local sf = screen:fullFrame()
  -- Top-right under menu bar
  local x = sf.x + sf.w - PANEL_W - 14
  local y = sf.y + 28
  panel:frame(hs.geometry.rect(x, y, PANEL_W, PANEL_H))
end

local function hidePanel()
  if panel then
    panel:hide()
  end
end

local function showPanel()
  refreshSnapshot(false)
  local s = readSnapshot()
  local html = buildHTML(s)

  if not panel then
    panel = hs.webview.new(hs.geometry.rect(0, 0, PANEL_W, PANEL_H), {
      javaScriptEnabled = false,
      javaScriptCanOpenWindowsAutomatically = false,
      developerExtrasEnabled = false,
    })
    panel:windowStyle({ "borderless", "utility", "nonactivating" })
    panel:level(hs.drawing.windowLevels.floating)
    panel:allowGestures(false)
    panel:allowNewWindows(false)
    panel:shadow(true)
    panel:closeOnEscape(true)
    panel:transparent(true)
    panel:deleteOnClose(false)
    panel:bringToFront(true)

    local function handleAction(url)
      if type(url) ~= "string" or url:sub(1, 12) ~= "nexstatus://" then
        return false
      end
      local action = url:sub(13):gsub("[?#].*$", "")
      if action == "refresh" then
        refreshSnapshot(true)
        if panel then panel:html(buildHTML(readSnapshot())) end
        M.refreshTitleOnly()
      elseif action == "stats" then
        hs.execute("open -a Stats", true)
        hidePanel()
      elseif action == "close" then
        hidePanel()
      end
      return true
    end

    -- Prefer policyCallback (blocks navigation to nexstatus://)
    panel:policyCallback(function(action, _, details)
      local url = nil
      if type(details) == "table" then
        url = details.URL or details.url or details.mainDocumentURL
        if not url and type(details.request) == "table" then
          url = details.request.URL or details.request.url
        end
      elseif type(details) == "string" then
        url = details
      end
      if url and handleAction(tostring(url)) then
        return false
      end
      return true
    end)

    panel:navigationCallback(function(action, _, _, req)
      local url = req
      if type(req) == "table" then
        url = req.URL or req.url
      end
      if url and handleAction(tostring(url)) then
        return false
      end
      return true
    end)
  end

  panel:html(html)
  positionPanel()
  panel:show()
  panel:bringToFront(true)
end

local function togglePanel()
  if panel and panel:hswindow() and panel:hswindow():isVisible() then
    hidePanel()
  else
    showPanel()
  end
end

function M.refreshTitleOnly()
  if not item then return end
  local s = readSnapshot()
  local title
  if s and s.title then
    -- Title from python: "Cl7 Cx5 Go100 G8 M6" → "Cl7 · Cx5 · Go100 · G8 · M6"
    local parts = {}
    for token in tostring(s.title):gmatch("%S+") do
      table.insert(parts, token)
    end
    title = table.concat(parts, " · ")
  else
    title = "Cl— · Cx— · Go— · G— · M—"
  end
  item:setTitle(" " .. title .. " ")
  item:setTooltip("Claude · Codex · OpenCode Go · Grok · Memory\n點一下開啟總覽")
end

function M.refresh()
  if not item then return end
  refreshSnapshot(false)
  M.refreshTitleOnly()
  -- Live-update open panel
  if panel and panel:hswindow() and panel:hswindow():isVisible() then
    panel:html(buildHTML(readSnapshot()))
  end
end

function M.start()
  if item then return end
  item = hs.menubar.new(true)
  if not item then
    hs.printf("[nexstatus] failed to create menubar")
    return
  end
  -- Click opens glass panel (not native menu)
  item:setClickCallback(function()
    togglePanel()
  end)
  M.refresh()
  timer = hs.timer.doEvery(15, function()
    M.refresh()
  end)

  -- Click outside to dismiss (best-effort)
  M._tap = hs.eventtap.new({ hs.eventtap.event.types.leftMouseDown }, function(e)
    if not (panel and panel:hswindow() and panel:hswindow():isVisible()) then
      return false
    end
    local loc = hs.mouse.absolutePosition()
    local f = panel:frame()
    if loc.x < f.x or loc.x > f.x + f.w or loc.y < f.y or loc.y > f.y + f.h then
      hidePanel()
    end
    return false
  end)
  M._tap:start()

  hs.printf("[nexstatus] NexStatus MenuBar started (root=%s)", ROOT)
end

function M.stop()
  if timer then timer:stop(); timer = nil end
  if M._tap then M._tap:stop(); M._tap = nil end
  if panel then
    panel:delete()
    panel = nil
  end
  if item then item:delete(); item = nil end
  hs.printf("[nexstatus] NexStatus stopped")
end

return M
