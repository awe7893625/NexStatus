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
local PREFS_PATH = (os.getenv("NEXSTATUS_CONFIG") or (HOME .. "/.config/nexstatus")) .. "/prefs.json"
local PY = ROOT .. "/nexstatus/collector.py"
local PYTHON = "/usr/bin/python3"
local PANEL_W = 380
local PANEL_H = 820

-- Chart: bar | circle
-- Theme: glass | paper | mono | nord | aurora (creative)
-- Glass lab: opacity / blur / saturate + named presets
local CHART_ORDER = { "bar", "circle" }
local THEME_ORDER = { "glass", "paper", "mono", "nord", "aurora" }
local GLASS_PRESET_ORDER = { "soft", "crystal", "dense", "smoke" }

local GLASS_PRESETS = {
  soft    = { name = "柔霧", opacity = 0.88, blur = 22, saturate = 130 },
  crystal = { name = "水晶", opacity = 0.72, blur = 48, saturate = 190 },
  dense   = { name = "厚玻", opacity = 0.93, blur = 64, saturate = 155 },
  smoke   = { name = "煙霧", opacity = 0.52, blur = 36, saturate = 115 },
}

-- RGB triples so opacity can be reapplied live
local THEMES = {
  glass = {
    name = "Glass",
    color_scheme = "dark",
    bg = { 28, 28, 30 },
    card = { 44, 44, 46 },
    border = "rgba(255,255,255,0.10)",
    text = "#F5F5F7",
    muted = "rgba(235,235,245,0.62)",
    sub = "rgba(235,235,245,0.48)",
    track = "rgba(120,120,128,0.28)",
    blue = "#0A84FF",
    glow1 = "rgba(10,132,255,0.14)",
    glow2 = "rgba(191,90,242,0.10)",
  },
  paper = {
    name = "Paper",
    color_scheme = "light",
    bg = { 250, 247, 240 },
    card = { 255, 255, 255 },
    border = "rgba(40,30,20,0.10)",
    text = "#1C1917",
    muted = "rgba(60,50,40,0.62)",
    sub = "rgba(60,50,40,0.48)",
    track = "rgba(80,70,60,0.14)",
    blue = "#C2410C",
    glow1 = "rgba(251,191,36,0.18)",
    glow2 = "rgba(194,65,12,0.08)",
  },
  mono = {
    name = "Mono",
    color_scheme = "dark",
    bg = { 12, 12, 12 },
    card = { 28, 28, 28 },
    border = "rgba(255,255,255,0.12)",
    text = "#FAFAFA",
    muted = "rgba(255,255,255,0.55)",
    sub = "rgba(255,255,255,0.40)",
    track = "rgba(255,255,255,0.12)",
    blue = "#FAFAFA",
    glow1 = "rgba(255,255,255,0.06)",
    glow2 = "rgba(255,255,255,0.03)",
  },
  nord = {
    name = "Nord",
    color_scheme = "dark",
    bg = { 46, 52, 64 },
    card = { 59, 66, 82 },
    border = "rgba(136,192,208,0.18)",
    text = "#ECEFF4",
    muted = "rgba(216,222,233,0.70)",
    sub = "rgba(216,222,233,0.50)",
    track = "rgba(76,86,106,0.80)",
    blue = "#88C0D0",
    glow1 = "rgba(136,192,208,0.14)",
    glow2 = "rgba(129,161,193,0.10)",
  },
  -- Creative: polar-light aurora glass
  aurora = {
    name = "Aurora",
    color_scheme = "dark",
    bg = { 14, 20, 36 },
    card = { 28, 38, 62 },
    border = "rgba(165,243,252,0.22)",
    text = "#F0FDFF",
    muted = "rgba(186,230,253,0.72)",
    sub = "rgba(186,230,253,0.48)",
    track = "rgba(100,130,190,0.32)",
    blue = "#67E8F9",
    glow1 = "rgba(56,189,248,0.30)",
    glow2 = "rgba(244,114,182,0.24)",
    creative = true,
  },
}

local prefs = {
  chart = "bar",
  theme = "glass",
  glass_preset = "crystal",
  opacity = 0.72,
  blur = 48,
  saturate = 190,
  radar = true, -- creative Pressure Radar + Quota Weather
}

local function clamp(n, lo, hi)
  n = tonumber(n)
  if not n then return lo end
  if n < lo then return lo end
  if n > hi then return hi end
  return n
end

local function applyGlassPreset(key)
  local p = GLASS_PRESETS[key]
  if not p then return end
  prefs.glass_preset = key
  prefs.opacity = p.opacity
  prefs.blur = p.blur
  prefs.saturate = p.saturate
end

local function markGlassCustom()
  prefs.glass_preset = "custom"
end

local function loadPrefs()
  local f = io.open(PREFS_PATH, "r")
  if not f then
    applyGlassPreset(prefs.glass_preset)
    return
  end
  local raw = f:read("*a")
  f:close()
  local ok, data = pcall(hs.json.decode, raw or "")
  if not (ok and type(data) == "table") then
    applyGlassPreset(prefs.glass_preset)
    return
  end
  if data.chart == "bar" or data.chart == "circle" then prefs.chart = data.chart end
  if THEMES[data.theme] then prefs.theme = data.theme end
  if data.radar == false then prefs.radar = false else prefs.radar = true end
  if type(data.glass_preset) == "string" and (GLASS_PRESETS[data.glass_preset] or data.glass_preset == "custom") then
    prefs.glass_preset = data.glass_preset
  end
  if GLASS_PRESETS[prefs.glass_preset] and data.opacity == nil then
    applyGlassPreset(prefs.glass_preset)
  else
    prefs.opacity = clamp(data.opacity or prefs.opacity, 0.35, 0.98)
    prefs.blur = clamp(data.blur or prefs.blur, 8, 80)
    prefs.saturate = clamp(data.saturate or prefs.saturate, 80, 240)
  end
end

local function savePrefs()
  local dir = PREFS_PATH:match("(.+)/[^/]+$")
  if dir then
    os.execute(string.format("mkdir -p %q", dir))
  end
  local f = io.open(PREFS_PATH, "w")
  if not f then return end
  f:write(hs.json.encode({
    chart = prefs.chart,
    theme = prefs.theme,
    glass_preset = prefs.glass_preset,
    opacity = prefs.opacity,
    blur = prefs.blur,
    saturate = prefs.saturate,
    radar = prefs.radar,
  }))
  f:close()
end

local function cycleList(list, cur)
  for i, v in ipairs(list) do
    if v == cur then
      return list[(i % #list) + 1]
    end
  end
  return list[1]
end

local function rgba(rgb, a)
  if type(rgb) == "string" then return rgb end
  local r, g, b = rgb[1] or 0, rgb[2] or 0, rgb[3] or 0
  return string.format("rgba(%d,%d,%d,%.3f)", r, g, b, a)
end

local function glassLabel()
  if prefs.glass_preset == "custom" then return "自訂" end
  local p = GLASS_PRESETS[prefs.glass_preset]
  return (p and p.name) or "玻璃"
end

loadPrefs()

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

local function meterBar(label, p, col)
  local w = p or 0
  local val = p and (tostring(p) .. "%") or "—"
  return string.format([[
    <div class="meter">
      <div class="meter-top">
        <span class="meter-label">%s</span>
        <span class="meter-val" style="color:%s">%s</span>
      </div>
      <div class="track"><div class="fill" style="width:%d%%;background:%s"></div></div>
    </div>
  ]], esc(label), col, val, w, col)
end

local function meterCircle(label, p, col, big)
  local w = p or 0
  local val = p and (tostring(p) .. "%") or "—"
  local cls = big and "ring-item ring-item-lg" or "ring-item"
  -- r≈15.9155 → circumference 100 for easy stroke-dasharray percent
  return string.format([[
    <div class="%s">
      <div class="ring-wrap">
        <svg viewBox="0 0 36 36" class="ring">
          <path class="ring-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"/>
          <path class="ring-fg" stroke="%s" stroke-dasharray="%d, 100"
            d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"/>
        </svg>
        <div class="ring-num" style="color:%s">%s</div>
      </div>
      <div class="ring-label">%s</div>
    </div>
  ]], cls, col, w, col, val, esc(label))
end

local function rowHTML(opts)
  -- opts: name, badge, main, sub, bars = {{label, pct}, ...}
  -- In circle mode, cards stay compact (text only); hero rings are rendered separately.
  local chart = prefs.chart or "bar"
  local meters = ""
  if chart ~= "circle" then
    for _, b in ipairs(opts.bars or {}) do
      local p = pct(b.pct)
      meters = meters .. meterBar(b.label, p, barColor(p))
    end
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
    meters
  )
end

-- Reference-style "Circular Percentage Loaders" hero strip (C / G / K [/ M])
local function heroRingsHTML(s)
  local host = s.host or {}
  local cl = s.claude or {}
  local cx = s.codex or {}
  local gk = s.grok or {}
  local items = {
    { "C Claude", cl.ok and cl.five_hour_pct or nil, "#D97757" },
    { "G Codex", cx.ok and cx.five_hour_pct or nil, "#10A37F" },
    { "K Grok", gk.ok and gk.used_pct or nil, "#BF5AF2" },
  }
  local mem = pct(host.mem_pct)
  local swap = tonumber(host.swap_mb) or 0
  if (swap >= 64) or (mem and mem >= 80) then
    table.insert(items, { "M Mem", mem, "#0A84FF" })
  end
  local html = '<section class="hero-loaders"><div class="hero-title">Circular Percentage Loaders</div><div class="hero-rings">'
  for _, it in ipairs(items) do
    local p = pct(it[2])
    local col = barColor(p)
    if it[3] then col = it[3] end
    -- keep semantic color when hot, else brand accent
    if p and p >= 70 then col = barColor(p) end
    html = html .. meterCircle(it[1], p, col, true)
  end
  html = html .. "</div></section>"
  return html
end

-- Creative: Pressure Radar + Quota Weather (overall burn mood)
local function pressureFromSnapshot(s)
  s = s or {}
  local host = s.host or {}
  local cl = s.claude or {}
  local cx = s.codex or {}
  local go = s.opencode_go or {}
  local gk = s.grok or {}
  local parts = {}
  local function add(key, label, ok, val)
    local p = pct(val)
    if ok and p ~= nil then
      table.insert(parts, { key = key, label = label, pct = p })
    end
  end
  add("C", "Claude", cl.ok, cl.five_hour_pct)
  add("G", "Codex", cx.ok, cx.five_hour_pct)
  add("O", "OpenCode", go.ok or go.live_status == "capped",
    go.live_status == "capped" and 100 or go.used_pct)
  add("K", "Grok", gk.ok, gk.used_pct)
  local mem = pct(host.mem_pct)
  local swap = tonumber(host.swap_mb) or 0
  if mem and (swap >= 64 or mem >= 70) then
    table.insert(parts, { key = "M", label = "Mem", pct = mem })
  end
  local maxP, sum, n = 0, 0, 0
  local hottest = nil
  for _, it in ipairs(parts) do
    sum = sum + it.pct
    n = n + 1
    if it.pct >= maxP then
      maxP = it.pct
      hottest = it
    end
  end
  -- Weighted: max pressure dominates (70%), average fills rest
  local avg = n > 0 and (sum / n) or 0
  local score = math.floor(maxP * 0.70 + avg * 0.30 + 0.5)
  local weather, mood
  if score < 35 then
    weather, mood = "☀️ 晴朗", "低壓 · 放心用"
  elseif score < 60 then
    weather, mood = "⛅ 多雲", "中壓 · 留意尖峰"
  elseif score < 85 then
    weather, mood = "🌧️ 陣雨", "高壓 · 快觸頂"
  else
    weather, mood = "⛈️ 暴雨", "危急 · 節省額度"
  end
  return {
    score = score,
    max = maxP,
    weather = weather,
    mood = mood,
    hottest = hottest,
    parts = parts,
  }
end

local function pressureRadarHTML(s)
  if prefs.radar == false then return "" end
  local pr = pressureFromSnapshot(s)
  local col = barColor(pr.score)
  local chips = ""
  for _, it in ipairs(pr.parts) do
    local c = barColor(it.pct)
    chips = chips .. string.format(
      '<span class="radar-chip" style="--c:%s"><b>%s</b>%d%%</span>',
      c, esc(it.key), it.pct
    )
  end
  if chips == "" then
    chips = '<span class="radar-chip">尚無資料</span>'
  end
  local hot = pr.hottest
      and string.format("最熱 %s %d%%", pr.hottest.label, pr.hottest.pct)
    or "—"
  return string.format([[
    <section class="radar">
      <div class="radar-left">
        <div class="radar-ring">
          <svg viewBox="0 0 36 36" class="ring">
            <path class="ring-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"/>
            <path class="ring-fg" stroke="%s" stroke-dasharray="%d, 100"
              d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"/>
          </svg>
          <div class="radar-score" style="color:%s">%d</div>
        </div>
      </div>
      <div class="radar-body">
        <div class="radar-title">壓力雷達 · 創意</div>
        <div class="radar-weather">%s</div>
        <div class="radar-mood">%s · %s</div>
        <div class="radar-chips">%s</div>
      </div>
    </section>
  ]], col, pr.score, col, pr.score, esc(pr.weather), esc(pr.mood), esc(hot), chips)
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

  local th = THEMES[prefs.theme] or THEMES.glass
  local chartLabel = (prefs.chart == "circle") and "圓圈" or "長條"
  local themeLabel = th.name or prefs.theme
  local gLabel = glassLabel()
  local op = clamp(prefs.opacity, 0.35, 0.98)
  local cardOp = clamp(op + 0.08, 0.40, 0.99)
  local blur = clamp(prefs.blur, 8, 80)
  local sat = clamp(prefs.saturate, 80, 240)
  local bgCss = rgba(th.bg, op)
  local cardCss = rgba(th.card, cardOp)
  local hero = ""
  if prefs.chart == "circle" then
    hero = heroRingsHTML(s)
  end
  local radar = pressureRadarHTML(s)
  local auroraCSS = ""
  if prefs.theme == "aurora" then
    auroraCSS = [[
  .shell.aurora::before {
    content: "";
    position: absolute; inset: 0; border-radius: 16px; pointer-events: none;
    background:
      radial-gradient(70% 50% at 15% 20%, rgba(56,189,248,0.28), transparent 55%),
      radial-gradient(60% 45% at 85% 30%, rgba(244,114,182,0.22), transparent 50%),
      radial-gradient(50% 40% at 50% 100%, rgba(52,211,153,0.16), transparent 55%);
    animation: auroraShift 9s ease-in-out infinite alternate;
    opacity: 0.9;
  }
  @keyframes auroraShift {
    from { filter: hue-rotate(0deg); transform: scale(1); }
    to { filter: hue-rotate(28deg); transform: scale(1.03); }
  }
  .shell.aurora { position: relative; overflow: hidden; }
  .shell.aurora > * { position: relative; z-index: 1; }
]]
  end

  return string.format([[<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  :root {
    color-scheme: %s;
    --bg: %s;
    --card: %s;
    --card-border: %s;
    --label: %s;
    --text: %s;
    --sub: %s;
    --track: %s;
    --blue: %s;
    --glow1: %s;
    --glow2: %s;
    --blur: %dpx;
    --sat: %d%%;
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
    padding: 10px 10px 8px;
    background:
      radial-gradient(120%% 80%% at 0%% 0%%, var(--glow1), transparent 52%%),
      radial-gradient(100%% 70%% at 100%% 100%%, var(--glow2), transparent 48%%),
      var(--bg);
    border-radius: 16px;
    border: 0.5px solid var(--card-border);
    box-shadow:
      0 22px 56px rgba(0,0,0,0.48),
      0 0 0 0.5px rgba(0,0,0,0.28) inset;
    backdrop-filter: blur(var(--blur)) saturate(var(--sat));
    -webkit-backdrop-filter: blur(var(--blur)) saturate(var(--sat));
    display: flex;
    flex-direction: column;
    gap: 0;
    overflow: hidden;
  }
  .data {
    flex: 1 1 auto;
    min-height: 0;
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: 7px;
    padding: 2px 2px 8px;
    -webkit-overflow-scrolling: touch;
  }
  .customize {
    flex: 0 0 auto;
    border-top: 1px solid var(--card-border);
    padding: 10px 4px 4px;
    margin-top: 2px;
    background: linear-gradient(180deg, rgba(0,0,0,0.12), transparent 28px);
    display: flex;
    flex-direction: column;
    gap: 7px;
  }
%s
  .top {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    padding: 2px 4px 2px;
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
    text-align: right;
  }
  .toolbar {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    padding: 0 2px 2px;
  }
  .customize-head {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.04em;
    color: var(--label);
    padding: 2px 4px 0;
  }
  .pill {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: var(--text);
    background: rgba(10,132,255,0.22);
    border: 1px solid rgba(10,132,255,0.35);
    border-radius: 999px;
    padding: 6px 11px;
    text-decoration: none;
  }
  .pill:active { opacity: 0.75; }
  .lab {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 6px;
    padding: 2px;
  }
  .lab-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 4px;
    background: var(--card);
    border: 1px solid var(--card-border);
    border-radius: 10px;
    padding: 7px 8px;
    font-size: 11px;
    color: var(--label);
    font-weight: 700;
  }
  .lab-row .lab-val {
    color: var(--text);
    font-variant-numeric: tabular-nums;
    min-width: 2.4em;
    text-align: center;
  }
  .step {
    width: 20px; height: 20px;
    display: flex; align-items: center; justify-content: center;
    border-radius: 6px;
    background: rgba(120,120,128,0.28);
    color: var(--text);
    text-decoration: none;
    font-size: 13px;
    font-weight: 700;
    line-height: 1;
  }
  .step:active { opacity: 0.7; }
  .radar {
    display: flex;
    gap: 12px;
    align-items: center;
    background: var(--card);
    border: 0.5px solid var(--card-border);
    border-radius: 14px;
    padding: 10px 12px;
  }
  .radar-ring {
    position: relative;
    width: 64px; height: 64px;
  }
  .radar-ring .ring { width: 100%%; height: 100%%; }
  .radar-score {
    position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    font-size: 16px; font-weight: 700;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.04em;
  }
  .radar-title {
    font-size: 10px; font-weight: 600; color: var(--label);
    letter-spacing: 0.02em; margin-bottom: 2px;
  }
  .radar-weather {
    font-size: 14px; font-weight: 700; letter-spacing: -0.02em;
  }
  .radar-mood {
    font-size: 11px; color: var(--sub); margin-top: 2px;
    font-variant-numeric: tabular-nums;
  }
  .radar-chips {
    display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px;
  }
  .radar-chip {
    font-size: 10px; font-weight: 600;
    color: var(--text);
    background: rgba(120,120,128,0.22);
    border-radius: 999px;
    padding: 2px 7px;
    font-variant-numeric: tabular-nums;
  }
  .radar-chip b { color: var(--c, var(--blue)); margin-right: 3px; }
  .hero-loaders {
    background: var(--card);
    border: 0.5px solid var(--card-border);
    border-radius: 14px;
    padding: 12px 12px 14px;
  }
  .hero-title {
    font-size: 11px;
    font-weight: 600;
    color: var(--label);
    letter-spacing: 0.02em;
    margin-bottom: 10px;
  }
  .hero-rings, .rings {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    justify-content: space-around;
  }
  .ring-item { width: 78px; text-align: center; }
  .ring-item-lg { width: 86px; }
  .ring-wrap { position: relative; width: 70px; height: 70px; margin: 0 auto; }
  .ring-item-lg .ring-wrap { width: 78px; height: 78px; }
  .ring { width: 100%%; height: 100%%; }
  .ring-bg {
    fill: none;
    stroke: var(--track);
    stroke-width: 3;
  }
  .ring-fg {
    fill: none;
    stroke-width: 3;
    stroke-linecap: round;
    transition: stroke-dasharray 0.35s cubic-bezier(0.22, 1, 0.36, 1);
  }
  .ring-num {
    position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    font-size: 14px; font-weight: 700;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.04em;
  }
  .ring-item-lg .ring-num { font-size: 15px; }
  .ring-label {
    margin-top: 7px;
    font-size: 10px;
    color: var(--label);
    font-weight: 600;
    line-height: 1.25;
  }
  .list {
    display: flex;
    flex-direction: column;
    gap: 7px;
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
    padding-top: 4px;
  }
  .btn {
    appearance: none;
    border: 0;
    border-radius: 10px;
    height: 36px;
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
    -webkit-user-select: none;
    user-select: none;
  }
  .btn:active { transform: scale(0.98); }
  .btn.primary {
    background: var(--blue);
    color: white;
  }
  .hint {
    grid-column: 1 / -1;
    text-align: center;
    font-size: 10px;
    color: var(--sub);
    margin-top: 2px;
  }
</style>
</head>
<body>
  <div class="shell%s">
    <div class="top">
      <div class="title">NexStatus<span>儀表板</span></div>
      <div class="stamp">%s<br/><span style="opacity:.8">%s · %s · 透%d%%</span></div>
    </div>

    <div class="data">
      %s
      %s
      <div class="list">
        %s
      </div>
    </div>

    <div class="customize">
      <div class="customize-head">客製化 · 直接在此面板切換（無需另開視窗）</div>
      <div class="toolbar">
        <a class="pill" href="#" data-action="cycle-chart">圖表：%s</a>
        <a class="pill" href="#" data-action="cycle-theme">主題：%s</a>
        <a class="pill" href="#" data-action="cycle-glass">玻璃：%s</a>
        <a class="pill" href="#" data-action="toggle-radar">雷達：%s</a>
      </div>
      <div class="lab">
        <div class="lab-row">
          <span>透明度</span>
          <a class="step" href="#" data-action="opacity-down">−</a>
          <span class="lab-val">%d%%</span>
          <a class="step" href="#" data-action="opacity-up">+</a>
        </div>
        <div class="lab-row">
          <span>模糊</span>
          <a class="step" href="#" data-action="blur-down">−</a>
          <span class="lab-val">%d</span>
          <a class="step" href="#" data-action="blur-up">+</a>
        </div>
        <div class="lab-row">
          <span>飽和</span>
          <a class="step" href="#" data-action="sat-down">−</a>
          <span class="lab-val">%d</span>
          <a class="step" href="#" data-action="sat-up">+</a>
        </div>
      </div>
      <div class="actions">
        <a class="btn primary" href="#" data-action="refresh">重新整理</a>
        <a class="btn" href="#" data-action="close">關閉</a>
        <div class="hint">設定會即時套用到上方資料區 · 記住在本機 prefs</div>
      </div>
    </div>
  </div>
  <script>
    function sendAction(action) {
      try {
        if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.nexBridge) {
          window.webkit.messageHandlers.nexBridge.postMessage({ action: action });
          return;
        }
      } catch (e) {}
      document.title = "NEX|" + action + "|" + Date.now();
    }
    document.addEventListener("click", function (e) {
      var t = e.target;
      while (t && !(t.getAttribute && t.getAttribute("data-action"))) {
        t = t.parentElement;
      }
      if (!t) return;
      e.preventDefault();
      e.stopPropagation();
      sendAction(t.getAttribute("data-action"));
    }, true);
  </script>
</body>
</html>]],
    th.color_scheme, bgCss, cardCss, th.border, th.muted, th.text, th.sub, th.track, th.blue, th.glow1, th.glow2,
    blur, sat,
    auroraCSS,
    (prefs.theme == "aurora") and " aurora" or "",
    esc(updated), esc(chartLabel), esc(themeLabel), math.floor(op * 100 + 0.5),
    -- data zone
    radar,
    hero,
    cards,
    -- customize zone
    esc(chartLabel), esc(themeLabel), esc(gLabel), prefs.radar and "開" or "關",
    math.floor(op * 100 + 0.5), blur, sat
  )
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

-- MenuBar open-click is outside the panel; ignore outside-dismiss briefly after show.
local suppressOutsideUntil = 0

local function redrawPanel()
  if panel then panel:html(buildHTML(readSnapshot())) end
end

local function handleAction(action)
  if type(action) ~= "string" then return end
  action = action:gsub("^/*", ""):gsub("[?#].*$", "")

  if action == "refresh" then
    refreshSnapshot(true)
    redrawPanel()
    M.refreshTitleOnly()
  elseif action == "cycle-chart" then
    prefs.chart = cycleList(CHART_ORDER, prefs.chart)
    savePrefs()
    redrawPanel()
  elseif action == "cycle-theme" then
    prefs.theme = cycleList(THEME_ORDER, prefs.theme)
    savePrefs()
    redrawPanel()
  elseif action == "cycle-glass" then
    local cur = prefs.glass_preset
    if cur == "custom" then cur = "crystal" end
    applyGlassPreset(cycleList(GLASS_PRESET_ORDER, cur))
    savePrefs()
    redrawPanel()
  elseif action == "toggle-radar" then
    prefs.radar = not prefs.radar
    savePrefs()
    redrawPanel()
  elseif action == "opacity-up" then
    prefs.opacity = math.floor(clamp((prefs.opacity or 0.72) + 0.05, 0.35, 0.98) * 100 + 0.5) / 100
    markGlassCustom()
    savePrefs()
    redrawPanel()
  elseif action == "opacity-down" then
    prefs.opacity = math.floor(clamp((prefs.opacity or 0.72) - 0.05, 0.35, 0.98) * 100 + 0.5) / 100
    markGlassCustom()
    savePrefs()
    redrawPanel()
  elseif action == "blur-up" then
    prefs.blur = clamp((prefs.blur or 48) + 6, 8, 80)
    markGlassCustom()
    savePrefs()
    redrawPanel()
  elseif action == "blur-down" then
    prefs.blur = clamp((prefs.blur or 48) - 6, 8, 80)
    markGlassCustom()
    savePrefs()
    redrawPanel()
  elseif action == "sat-up" then
    prefs.saturate = clamp((prefs.saturate or 190) + 15, 80, 240)
    markGlassCustom()
    savePrefs()
    redrawPanel()
  elseif action == "sat-down" then
    prefs.saturate = clamp((prefs.saturate or 190) - 15, 80, 240)
    markGlassCustom()
    savePrefs()
    redrawPanel()
  elseif action == "close" then
    hidePanel()
  end
  hs.printf("[nexstatus] action=%s theme=%s glass=%s op=%.2f blur=%d sat=%d",
    action, prefs.theme, tostring(prefs.glass_preset),
    prefs.opacity or 0, prefs.blur or 0, prefs.saturate or 0)
end

-- Public: fire a panel action
function M.fire(action)
  handleAction(action)
end

local function ensurePanel()
  if panel then return panel end

  -- Bridge: JS → Lua (primary)
  local uc = hs.webview.usercontent.new("nexBridge")
  uc:setCallback(function(msg)
    local body = msg and msg.body
    local action = nil
    if type(body) == "string" then
      action = body
    elseif type(body) == "table" then
      action = body.action or body.cmd or body[1]
    end
    if type(action) ~= "string" then return end
    action = action:gsub("^/*", ""):gsub("[?#].*$", "")
    hs.printf("[nexstatus] bridge action=%s", action)
    handleAction(action)
  end)

  panel = hs.webview.new(hs.geometry.rect(0, 0, PANEL_W, PANEL_H), {
    javaScriptEnabled = true,
    javaScriptCanOpenWindowsAutomatically = false,
    developerExtrasEnabled = false,
  }, uc)
  panel:windowStyle({ "borderless", "utility", "nonactivating" })
  panel:level(hs.drawing.windowLevels.floating)
  panel:allowGestures(false)
  panel:allowNewWindows(false)
  panel:shadow(true)
  panel:closeOnEscape(true)
  panel:transparent(true)
  panel:deleteOnClose(false)
  panel:bringToFront(true)

  -- Fallback: if messageHandlers fails, JS sets document.title = "NEX|action"
  if panel.frameTitleChangedCallback then
    panel:frameTitleChangedCallback(function(title)
      if type(title) == "string" and title:sub(1, 4) == "NEX|" then
        local action = title:sub(5)
        hs.printf("[nexstatus] title-fallback action=%s", action)
        handleAction(action)
      end
    end)
  end
  return panel
end

local function showPanel()
  refreshSnapshot(false)
  local s = readSnapshot()
  local html = buildHTML(s)
  ensurePanel()
  panel:html(html)
  positionPanel()
  panel:show()
  panel:bringToFront(true)
  -- Grace period: MenuBar click is outside the panel frame; without this,
  -- the outside-dismiss eventtap closes the dashboard on the same click.
  suppressOutsideUntil = hs.timer.secondsSinceEpoch() + 0.55
  if panel.hswindow and panel:hswindow() then
    pcall(function() panel:hswindow():focus() end)
  end
  hs.printf("[nexstatus] dashboard shown")
end

local function togglePanel()
  local visible = false
  if panel then
    pcall(function()
      local w = panel:hswindow()
      visible = w and w:isVisible() or false
    end)
  end
  if visible then
    hidePanel()
    hs.printf("[nexstatus] dashboard hidden")
  else
    showPanel()
  end
end

-- Public: open control panel (for debugging / scripts)
function M.openPanel()
  showPanel()
end


function M.refreshTitleOnly()
  if not item then return end
  local s = readSnapshot() or {}
  local host = s.host or {}
  local cl = s.claude or {}
  local cx = s.codex or {}
  local go = s.opencode_go or {}
  local gk = s.grok or {}

  -- Main bar: C=Claude · G=Code/Codex · K=Grok  →  e.g. C70% G49% K8%
  local function chip(letter, ok, val)
    if not ok or val == nil then
      return letter .. "—%"
    end
    return string.format("%s%d%%", letter, tonumber(val) or 0)
  end

  local parts = {
    chip("C", cl.ok, cl.five_hour_pct),
    chip("G", cx.ok, cx.five_hour_pct),
    chip("K", gk.ok, gk.used_pct),
  }

  -- Optional memory chip when swap is active or RAM is tight
  local mem = tonumber(host.mem_pct)
  local swap = tonumber(host.swap_mb) or 0
  local showMem = (swap >= 64) or (mem ~= nil and mem >= 80)
  if showMem and mem ~= nil then
    table.insert(parts, string.format("M%d%%", mem))
  end

  -- Force uppercase chips only (C70% G49% K10% M8%) — never lowercase
  local title = table.concat(parts, " "):upper()
  local pr = pressureFromSnapshot(s)
  if pr.score >= 90 then
    title = "⚡" .. title
  elseif pr.score >= 75 then
    title = "!" .. title
  end
  local tip = string.format(
    "NexStatus\n壓力雷達 %d · %s\nC = Claude 5h %s\nG = Codex 5h %s\nK = Grok %s\nOpenCode Go %s · MEM %s · Swap %.0f MB\n點一下開啟儀表板：上方資料、下方直接客製化",
    pr.score,
    pr.weather,
    pctText(cl.five_hour_pct),
    pctText(cx.five_hour_pct),
    pctText(gk.used_pct),
    pctText(go.used_pct),
    pctText(mem),
    swap
  )

  item:setTitle(" " .. title .. " ")
  item:setTooltip(tip)
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
  -- Always rebuild panel so bridge matches this code version
  if panel then
    pcall(function() panel:delete() end)
    panel = nil
  end

  item = hs.menubar.new(true)
  if not item then
    hs.printf("[nexstatus] failed to create menubar")
    return
  end

  -- Critical: no setMenu — a menu steals the click and user never sees the dashboard.
  pcall(function() item:setMenu(nil) end)

  -- Click MenuBar title chips → toggle the one tall data dashboard
  item:setClickCallback(function()
    hs.printf("[nexstatus] menubar clicked → toggle dashboard")
    togglePanel()
  end)

  -- Warm snapshot so first open is instant
  pcall(function() refreshSnapshot(false) end)
  M.refresh()
  timer = hs.timer.doEvery(15, function()
    M.refresh()
  end)

  -- Click outside panel to dismiss — but never on the open-click itself
  if M._tap then
    pcall(function() M._tap:stop() end)
    M._tap = nil
  end
  M._tap = hs.eventtap.new({ hs.eventtap.event.types.leftMouseDown }, function(_e)
    if hs.timer.secondsSinceEpoch() < suppressOutsideUntil then
      return false
    end
    if not panel then return false end
    local visible = false
    pcall(function()
      local w = panel:hswindow()
      visible = w and w:isVisible() or false
    end)
    if not visible then return false end

    local loc = hs.mouse.absolutePosition()
    -- Ignore clicks on the macOS menu bar strip (where NexStatus lives)
    local sf = hs.screen.mainScreen():fullFrame()
    if loc.y < sf.y + 40 then
      return false
    end

    local f = panel:frame()
    if loc.x < f.x or loc.x > f.x + f.w or loc.y < f.y or loc.y > f.y + f.h then
      hidePanel()
    end
    return false
  end)
  M._tap:start()

  hs.printf("[nexstatus] NexStatus ready — click MenuBar C%% G%% K%% to open dashboard (root=%s)", ROOT)
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
