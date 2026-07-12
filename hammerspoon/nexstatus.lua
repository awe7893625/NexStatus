-- NexStatus — Apple Control Center style glass MenuBar
-- Title: Cl · Cx · Go · G · M  |  Click → vibrancy card
-- Collector: nexstatus/collector.py → ~/.cache/nexstatus/status.json

local M = {}

-- Singleton: a reloaded module must stop the previous instance first, otherwise
-- the old timer/watchdog keeps a dead MenuBar ref and spawns a second chip.
if type(_G.NexStatus) == "table" and type(_G.NexStatus.stop) == "function" then
  pcall(function() _G.NexStatus.stop() end)
end
if _G.NexStatusMenuBar then
  pcall(function() _G.NexStatusMenuBar:delete() end)
  _G.NexStatusMenuBar = nil
end

local item = nil
local timer = nil
local panel = nil
local redrawPanel = nil
local collectorTask = nil
local collectorWatchdog = nil
local refreshQueued = false

local HOME = os.getenv("HOME") or ""
local ROOT = os.getenv("NEXSTATUS_HOME") or (HOME .. "/Developer/NexStatus")
local SNAP = (os.getenv("NEXSTATUS_CACHE") or (HOME .. "/.cache/nexstatus")) .. "/status.json"
local PREFS_PATH = (os.getenv("NEXSTATUS_CONFIG") or (HOME .. "/.config/nexstatus")) .. "/prefs.json"
local PY = ROOT .. "/nexstatus/collector.py"
local PYTHON = "/usr/bin/python3"
local PANEL_W = 420
local PANEL_H = 860

-- Chart: bar | circle
-- Theme: Claude / Codex studio language first, then glass material variants
-- Glass lab: opacity / blur / saturate + named presets
local CHART_ORDER = { "bar", "circle" }
local THEME_ORDER = { "notion", "tableau", "claude", "codex", "glass", "mono" }
local LEGACY_THEME = { nord = "glass", aurora = "claude" }
local GLASS_PRESET_ORDER = { "soft", "crystal", "dense", "smoke" }
local ACCENT_ORDER = { "theme", "coral", "green", "blue", "violet", "amber" }
local ACCENTS = {
  theme  = nil,
  coral  = "#D97757",
  green  = "#10B981",
  blue   = "#0A84FF",
  violet = "#BF5AF2",
  amber  = "#F59E0B",
}
local SECTION_ORDER = { "compute", "radar", "loaders", "providers" }
-- Per-grid tile orders (each card cell can be reordered independently).
local TILE_ORDER_DEFAULTS = {
  token_kpis = { "3d", "7d", "30d" },
  token_sources = { "claude", "codex", "free", "local", "other" },
  providers = { "claude", "codex", "go", "grok", "antigravity", "mac" },
}

local GLASS_PRESETS = {
  soft    = { name = "柔霧", opacity = 0.88, blur = 22, saturate = 130 },
  crystal = { name = "水晶", opacity = 0.72, blur = 48, saturate = 190 },
  dense   = { name = "厚玻", opacity = 0.93, blur = 64, saturate = 155 },
  smoke   = { name = "煙霧", opacity = 0.52, blur = 36, saturate = 115 },
}

-- Theme tokens — deliberately high-contrast personalities.
-- Chart/status colors are theme-owned so switching recolors the whole dashboard.
local THEMES = {
  notion = {
    name = "Notion",
    blurb = "黑白文件、留白與細線",
    color_scheme = "light",
    bg = { 250, 250, 249 }, card = { 255, 255, 255 },
    border = "rgba(55,53,47,0.16)", text = "#37352F",
    muted = "rgba(55,53,47,0.68)", sub = "rgba(55,53,47,0.48)",
    track = "rgba(55,53,47,0.12)", blue = "#2F80ED",
    glow1 = "rgba(255,255,255,0.75)", glow2 = "rgba(235,235,232,0.55)",
    fill = "rgba(55,53,47,0.055)", fill2 = "rgba(55,53,47,0.035)",
    hairline = "rgba(55,53,47,0.13)", inset = "rgba(255,255,255,0.92)",
    drop = "rgba(15,15,15,0.10)", shellBorder = "rgba(55,53,47,0.15)",
    swatch = "linear-gradient(145deg,#FFFFFF,#E9E9E7 60%,#37352F)",
    chart_free = "#0F9D75", chart_local = "#2F80ED",
    chart_primary = "#37352F", chart_secondary = "#787774",
    chart_warn = "#D9730D", chart_ok = "#0F9D75", radius = 12,
    material = { opacity = 0.94, blur = 12, saturate = 100 },
  },
  tableau = {
    name = "Tableau",
    blurb = "分析工作台、高辨識圖表",
    color_scheme = "dark",
    bg = { 14, 28, 48 }, card = { 24, 45, 72 },
    border = "rgba(130,180,225,0.24)", text = "#F4F8FC",
    muted = "rgba(205,225,244,0.76)", sub = "rgba(175,205,232,0.58)",
    track = "rgba(70,110,150,0.42)", blue = "#4E79A7",
    glow1 = "rgba(78,121,167,0.48)", glow2 = "rgba(242,142,43,0.22)",
    fill = "rgba(52,84,118,0.68)", fill2 = "rgba(18,36,58,0.76)",
    hairline = "rgba(145,190,230,0.18)", inset = "rgba(190,220,245,0.10)",
    drop = "rgba(0,8,20,0.55)", shellBorder = "rgba(100,155,205,0.28)",
    swatch = "linear-gradient(145deg,#4E79A7,#F28E2B 52%,#E15759)",
    chart_free = "#59A14F", chart_local = "#4E79A7",
    chart_primary = "#F28E2B", chart_secondary = "#E15759",
    chart_warn = "#EDC948", chart_ok = "#59A14F", radius = 10,
    material = { opacity = 0.91, blur = 18, saturate = 145 },
  },
  claude = {
    name = "Claude",
    blurb = "暖橙工作室暗色",
    color_scheme = "dark",
    bg = { 42, 28, 22 },
    card = { 58, 38, 30 },
    border = "rgba(255,180,120,0.22)",
    text = "#FFF7F0",
    muted = "rgba(255,220,190,0.78)",
    sub = "rgba(255,200,160,0.58)",
    track = "rgba(140,80,50,0.45)",
    blue = "#E07A4F",
    glow1 = "rgba(224,122,79,0.55)",
    glow2 = "rgba(255,170,80,0.28)",
    fill = "rgba(90,50,35,0.72)",
    fill2 = "rgba(50,30,22,0.78)",
    hairline = "rgba(255,190,140,0.18)",
    inset = "rgba(255,210,170,0.14)",
    drop = "rgba(30,12,6,0.55)",
    shellBorder = "rgba(255,170,110,0.28)",
    swatch = "linear-gradient(145deg,#E07A4F,#8B4518 45%,#2A1C16)",
    chart_free = "#F0B429",
    chart_local = "#E07A4F",
    chart_primary = "#E07A4F",
    chart_secondary = "#F5C28A",
    chart_warn = "#FFB020",
    chart_ok = "#D4A574",
    radius = 22,
    material = { opacity = 0.86, blur = 36, saturate = 150 },
  },
  codex = {
    name = "Codex",
    blurb = "終端機冷綠",
    color_scheme = "dark",
    bg = { 4, 14, 12 },
    card = { 10, 28, 24 },
    border = "rgba(50,255,180,0.18)",
    text = "#E8FFF6",
    muted = "rgba(160,255,220,0.72)",
    sub = "rgba(120,220,190,0.55)",
    track = "rgba(20,80,65,0.55)",
    blue = "#12D48A",
    glow1 = "rgba(18,212,138,0.42)",
    glow2 = "rgba(40,120,255,0.18)",
    fill = "rgba(12,48,40,0.82)",
    fill2 = "rgba(6,22,18,0.90)",
    hairline = "rgba(80,255,190,0.14)",
    inset = "rgba(120,255,200,0.10)",
    drop = "rgba(0,0,0,0.55)",
    shellBorder = "rgba(40,230,160,0.22)",
    swatch = "linear-gradient(145deg,#12D48A,#0A3D32 50%,#040E0C)",
    chart_free = "#12D48A",
    chart_local = "#4CC9F0",
    chart_primary = "#12D48A",
    chart_secondary = "#7CF5C8",
    chart_warn = "#F4D35E",
    chart_ok = "#12D48A",
    radius = 14,
    material = { opacity = 0.90, blur = 28, saturate = 140 },
  },
  glass = {
    name = "Glass",
    blurb = "系統藍紫玻璃",
    color_scheme = "dark",
    bg = { 18, 22, 48 },
    card = { 36, 42, 78 },
    border = "rgba(140,180,255,0.28)",
    text = "#F2F6FF",
    muted = "rgba(200,220,255,0.74)",
    sub = "rgba(170,200,255,0.55)",
    track = "rgba(80,100,180,0.40)",
    blue = "#5B8CFF",
    glow1 = "rgba(80,140,255,0.50)",
    glow2 = "rgba(190,90,255,0.32)",
    fill = "rgba(70,90,160,0.40)",
    fill2 = "rgba(40,50,100,0.50)",
    hairline = "rgba(160,190,255,0.20)",
    inset = "rgba(200,220,255,0.16)",
    drop = "rgba(8,10,30,0.50)",
    shellBorder = "rgba(150,190,255,0.30)",
    swatch = "linear-gradient(145deg,#5B8CFF,#BF5AF2 55%,#121630)",
    chart_free = "#34D399",
    chart_local = "#5B8CFF",
    chart_primary = "#5B8CFF",
    chart_secondary = "#BF5AF2",
    chart_warn = "#FF9F0A",
    chart_ok = "#34D399",
    radius = 30,
    material = { opacity = 0.70, blur = 54, saturate = 200 },
  },
  paper = {
    name = "Paper",
    blurb = "奶油紙亮色",
    color_scheme = "light",
    bg = { 252, 246, 232 },
    card = { 255, 252, 245 },
    border = "rgba(90,55,20,0.14)",
    text = "#1A1208",
    muted = "rgba(70,45,20,0.70)",
    sub = "rgba(90,55,25,0.55)",
    track = "rgba(140,100,50,0.16)",
    blue = "#C2410C",
    glow1 = "rgba(251,191,36,0.35)",
    glow2 = "rgba(255,255,255,0.80)",
    fill = "rgba(180,130,70,0.10)",
    fill2 = "rgba(255,255,255,0.70)",
    hairline = "rgba(100,60,20,0.12)",
    inset = "rgba(255,255,255,0.90)",
    drop = "rgba(90,55,20,0.12)",
    shellBorder = "rgba(120,75,30,0.16)",
    swatch = "linear-gradient(145deg,#FFF8E8,#F0D9A8 55%,#E8C48A)",
    chart_free = "#059669",
    chart_local = "#C2410C",
    chart_primary = "#C2410C",
    chart_secondary = "#D97706",
    chart_warn = "#B45309",
    chart_ok = "#059669",
    radius = 18,
    material = { opacity = 0.96, blur = 18, saturate = 110 },
  },
  mono = {
    name = "Mono",
    blurb = "純黑白高對比",
    color_scheme = "dark",
    bg = { 0, 0, 0 },
    card = { 14, 14, 14 },
    border = "rgba(255,255,255,0.28)",
    text = "#FFFFFF",
    muted = "rgba(255,255,255,0.72)",
    sub = "rgba(255,255,255,0.48)",
    track = "rgba(255,255,255,0.18)",
    blue = "#FFFFFF",
    glow1 = "rgba(255,255,255,0.08)",
    glow2 = "rgba(255,255,255,0.04)",
    fill = "rgba(255,255,255,0.08)",
    fill2 = "rgba(255,255,255,0.04)",
    hairline = "rgba(255,255,255,0.20)",
    inset = "rgba(255,255,255,0.10)",
    drop = "rgba(0,0,0,0.70)",
    shellBorder = "rgba(255,255,255,0.28)",
    swatch = "linear-gradient(145deg,#FFFFFF 0%,#666 35%,#000 100%)",
    chart_free = "#FFFFFF",
    chart_local = "#A0A0A0",
    chart_primary = "#FFFFFF",
    chart_secondary = "#888888",
    chart_warn = "#FFFFFF",
    chart_ok = "#CCCCCC",
    radius = 8,
    material = { opacity = 0.98, blur = 8, saturate = 80 },
  },
}

local prefs = {
  chart = "bar",
  theme = "claude",
  accent = "theme",
  glass_preset = "crystal",
  opacity = 0.78,
  blur = 42,
  saturate = 160,
  radar = true, -- creative Pressure Radar + Quota Weather
  density = "comfortable",
  edit_layout = false,
  section_order = { "compute", "radar", "loaders", "providers" },
  token_kpi_order = { "3d", "7d", "30d" },
  token_source_order = { "claude", "codex", "free", "local", "other" },
  provider_order = { "claude", "codex", "go", "grok", "antigravity", "mac" },
}

local function normalizedSectionOrder(value)
  -- Compute Lens is the fixed primary section. Only secondary sections are
  -- personalized, so an older preference file cannot demote free cloud data.
  local result, seen = { "compute" }, { compute = true }
  if type(value) == "table" then
    for _, id in ipairs(value) do
      if type(id) == "string" and not seen[id] then
        for _, allowed in ipairs(SECTION_ORDER) do
          if id == allowed then
            table.insert(result, id)
            seen[id] = true
            break
          end
        end
      end
    end
  end
  for _, id in ipairs(SECTION_ORDER) do
    if not seen[id] then table.insert(result, id) end
  end
  return result
end

local function normalizedTileOrder(group, value)
  local allowed = TILE_ORDER_DEFAULTS[group]
  if not allowed then return {} end
  local result, seen = {}, {}
  if type(value) == "table" then
    for _, id in ipairs(value) do
      if type(id) == "string" and not seen[id] then
        for _, candidate in ipairs(allowed) do
          if id == candidate then
            table.insert(result, id)
            seen[id] = true
            break
          end
        end
      end
    end
  end
  for _, id in ipairs(allowed) do
    if not seen[id] then table.insert(result, id) end
  end
  return result
end

local function tilePrefsKey(group)
  if group == "token_kpis" then return "token_kpi_order" end
  if group == "token_sources" then return "token_source_order" end
  if group == "providers" then return "provider_order" end
  return nil
end

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
  if type(data.theme) == "string" then
    local tid = LEGACY_THEME[data.theme] or data.theme
    if THEMES[tid] then prefs.theme = tid end
  end
  if type(data.accent) == "string" and (data.accent == "theme" or ACCENTS[data.accent]) then
    prefs.accent = data.accent
  end
  if data.radar == false then prefs.radar = false else prefs.radar = true end
  if data.density == "compact" or data.density == "comfortable" then
    prefs.density = data.density
  end
  prefs.edit_layout = data.edit_layout == true
  prefs.section_order = normalizedSectionOrder(data.section_order)
  prefs.token_kpi_order = normalizedTileOrder("token_kpis", data.token_kpi_order)
  prefs.token_source_order = normalizedTileOrder("token_sources", data.token_source_order)
  prefs.provider_order = normalizedTileOrder("providers", data.provider_order)
  if type(data.glass_preset) == "string" and (GLASS_PRESETS[data.glass_preset] or data.glass_preset == "custom") then
    prefs.glass_preset = data.glass_preset
  end
  if GLASS_PRESETS[prefs.glass_preset] and data.opacity == nil then
    applyGlassPreset(prefs.glass_preset)
  else
    prefs.opacity = clamp(data.opacity or prefs.opacity, 0.18, 0.98)
    prefs.blur = clamp(data.blur or prefs.blur, 8, 80)
    prefs.saturate = clamp(data.saturate or prefs.saturate, 80, 240)
  end
end

local function savePrefs()
  local dir = PREFS_PATH:match("(.+)/[^/]+$")
  if dir then
    os.execute(string.format("mkdir -p %q && chmod 700 %q", dir, dir))
  end
  local tempPath = PREFS_PATH .. ".tmp"
  local f = io.open(tempPath, "w")
  if not f then return end
  f:write(hs.json.encode({
    chart = prefs.chart,
    theme = prefs.theme,
    accent = prefs.accent,
    glass_preset = prefs.glass_preset,
    opacity = prefs.opacity,
    blur = prefs.blur,
    saturate = prefs.saturate,
    radar = prefs.radar,
    density = prefs.density,
    edit_layout = prefs.edit_layout,
    section_order = normalizedSectionOrder(prefs.section_order),
    token_kpi_order = normalizedTileOrder("token_kpis", prefs.token_kpi_order),
    token_source_order = normalizedTileOrder("token_sources", prefs.token_source_order),
    provider_order = normalizedTileOrder("providers", prefs.provider_order),
  }))
  f:close()
  os.execute(string.format("chmod 600 %q", tempPath))
  os.rename(tempPath, PREFS_PATH)
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

local function accentLabel()
  if prefs.accent == "theme" or not prefs.accent then return "跟隨主題" end
  local names = {
    coral = "Claude 橙",
    green = "Codex 綠",
    blue = "系統藍",
    violet = "紫羅蘭",
    amber = "琥珀",
  }
  return names[prefs.accent] or prefs.accent
end

local function resolvedTheme()
  return THEMES[prefs.theme] or THEMES.claude
end

local function resolvedAccent(th)
  th = th or resolvedTheme()
  if prefs.accent and prefs.accent ~= "theme" and ACCENTS[prefs.accent] then
    return ACCENTS[prefs.accent]
  end
  return th.blue
end

local function chromeTokens()
  local th = resolvedTheme()
  local op = clamp(prefs.opacity, 0.18, 0.98)
  local cardOp = clamp(op, 0.18, 0.98)
  local blur = clamp(prefs.blur, 8, 80)
  local sat = clamp(prefs.saturate, 80, 240)
  local accent = resolvedAccent(th)
  return {
    th = th,
    op = op,
    cardOp = cardOp,
    blur = blur,
    sat = sat,
    accent = accent,
    bgCss = rgba(th.bg, op),
    cardCss = rgba(th.card, cardOp),
    isLight = th.color_scheme == "light",
    radius = tonumber(th.radius) or 28,
    chart_free = th.chart_free or "#30D158",
    chart_local = th.chart_local or "#64D2FF",
    chart_primary = th.chart_primary or accent,
    chart_secondary = th.chart_secondary or accent,
    chart_warn = th.chart_warn or "#FF9F0A",
    chart_ok = th.chart_ok or "#30D158",
  }
end

-- Live-apply theme/material without full HTML rebuild (no flash).
local function applyChromeLive()
  if not panel then return false end
  local c = chromeTokens()
  local th = c.th
  local js = string.format([[
    (function () {
      var r = document.documentElement.style;
      var map = {
        "--bg": %q, "--card": %q, "--card-border": %q, "--label": %q,
        "--text": %q, "--sub": %q, "--track": %q, "--blue": %q,
        "--glow1": %q, "--glow2": %q, "--fill": %q, "--fill-2": %q,
        "--hairline": %q, "--inset": %q, "--drop": %q, "--shell-border": %q,
        "--blur": %q, "--sat": %q,
        "--radius": %q,
        "--chart-free": %q, "--chart-local": %q,
        "--chart-primary": %q, "--chart-secondary": %q,
        "--chart-warn": %q, "--chart-ok": %q
      };
      Object.keys(map).forEach(function (k) { r.setProperty(k, map[k]); });
      document.documentElement.style.colorScheme = %q;
      var shell = document.querySelector(".shell");
      if (shell) {
        shell.classList.toggle("is-light", %s);
        shell.classList.toggle("is-dark", %s);
        shell.setAttribute("data-theme", %q);
      }
      document.querySelectorAll(".theme-chip").forEach(function (el) {
        var id = (el.getAttribute("data-action") || "").replace("theme:", "");
        el.classList.toggle("is-active", id === %q);
      });
      document.querySelectorAll(".accent-dot").forEach(function (el) {
        var id = (el.getAttribute("data-action") || "").replace("accent:", "");
        el.classList.toggle("is-active", id === %q);
      });
      document.querySelectorAll(".seg-item[data-glass]").forEach(function (el) {
        el.classList.toggle("is-active", el.getAttribute("data-glass") === %q);
      });
      var stamp = document.querySelector(".stamp");
      if (stamp) {
        var bits = stamp.textContent.split(" · ");
        if (bits.length >= 3) {
          bits[2] = %q;
          bits[bits.length - 1] = "透" + %d + "%%";
          stamp.textContent = bits.join(" · ");
        }
      }
      var accentLab = document.querySelector("[data-accent-label]");
      if (accentLab) accentLab.textContent = %q;
      var glassLab = document.querySelector("[data-glass-label]");
      if (glassLab) glassLab.textContent = %q;
      var opLab = document.querySelector('[data-lab="opacity"]');
      if (opLab) opLab.textContent = %d + "%%";
      var blurLab = document.querySelector('[data-lab="blur"]');
      if (blurLab) blurLab.textContent = String(%d);
      var satLab = document.querySelector('[data-lab="sat"]');
      if (satLab) satLab.textContent = String(%d);
    })();
  ]],
    c.bgCss, c.cardCss, th.border, th.muted,
    th.text, th.sub, th.track, c.accent,
    th.glow1, th.glow2, th.fill or "rgba(120,120,128,0.16)", th.fill2 or "rgba(120,120,128,0.10)",
    th.hairline or th.border, th.inset or "rgba(255,255,255,0.10)",
    th.drop or "rgba(0,0,0,0.28)", th.shellBorder or th.border,
    tostring(c.blur) .. "px", tostring(c.sat) .. "%",
    tostring(c.radius) .. "px",
    c.chart_free, c.chart_local, c.chart_primary, c.chart_secondary, c.chart_warn, c.chart_ok,
    th.color_scheme,
    c.isLight and "true" or "false",
    (not c.isLight) and "true" or "false",
    prefs.theme,
    prefs.theme,
    prefs.accent or "theme",
    prefs.glass_preset or "crystal",
    th.name or prefs.theme,
    math.floor(c.op * 100 + 0.5),
    accentLabel(),
    glassLabel(),
    math.floor(c.op * 100 + 0.5),
    c.blur,
    c.sat
  )
  local ok = pcall(function() panel:evaluateJavaScript(js) end)
  return ok
end

-- Material-only tweaks can soft-apply; theme identity needs full redraw so
-- inline chart/ring colors (built in HTML) also switch.
local function softChromeOrRedraw(forceFull)
  if forceFull then
    if redrawPanel then redrawPanel() end
    return
  end
  if panel then
    local visible = false
    pcall(function()
      local w = panel:hswindow()
      visible = w and w:isVisible() or false
    end)
    if visible and applyChromeLive() then return end
  end
  if redrawPanel then redrawPanel() end
end

loadPrefs()

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
  if collectorTask then
    refreshQueued = refreshQueued or forceRemote
    return false
  end

  local args = { PY }
  if forceRemote then table.insert(args, "--force") end

  collectorTask = hs.task.new(PYTHON, function(exitCode, _stdout, _stderr)
    if collectorWatchdog then
      collectorWatchdog:stop()
      collectorWatchdog = nil
    end
    collectorTask = nil

    -- Only publish a completed atomic snapshot. A failed/timed-out collector
    -- leaves the last known-good dashboard intact.
    if exitCode == 0 then
      if M.refreshTitleOnly then M.refreshTitleOnly() end
      if redrawPanel then redrawPanel() end
    end

    if refreshQueued then
      local queuedForce = refreshQueued
      refreshQueued = false
      hs.timer.doAfter(0, function() refreshSnapshot(queuedForce) end)
    end
  end, args)

  if not collectorTask then return false end
  collectorTask:start()

  local activeTask = collectorTask
  collectorWatchdog = hs.timer.doAfter(8, function()
    if collectorTask == activeTask and activeTask:isRunning() then
      activeTask:terminate()
    end
  end)
  return true
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

local function fmtResetFull(ts)
  if type(ts) ~= "number" then return "日期未知" end
  return os.date("%Y/%m/%d %H:%M", ts) .. "（台北） · " .. fmtReset(ts)
end

local function fmtIsoReset(value)
  if type(value) ~= "string" or value == "" then return "日期未知" end
  return value:gsub("T", " "):gsub("Z$", " UTC")
end

local function providerUsageSheetHTML(id, title, subtitle, rows, source)
  local body = ""
  for _, row in ipairs(rows or {}) do
    body = body .. string.format([[
      <div class="usage-window-row">
        <div><span>%s</span><strong>%s</strong></div>
        <div class="usage-reset"><span>重置時間</span><b>%s</b></div>
      </div>
    ]], esc(row.label or "額度視窗"), esc(row.usage or "—"), esc(row.reset or "日期未知"))
  end
  if body == "" then body = '<div class="detail-empty">目前沒有可靠的重置日期；NexStatus 不會猜測。</div>' end
  return string.format([[
    <div class="sheet-backdrop" data-sheet-close="usage-%s" aria-hidden="true"></div>
    <section class="detail-sheet usage-sheet" id="usage-%s-sheet" role="dialog" aria-modal="true"
      aria-labelledby="usage-%s-title" aria-hidden="true">
      <div class="sheet-grabber"></div>
      <header class="sheet-head">
        <div><span>USAGE & RESET</span><h2 id="usage-%s-title">%s</h2></div>
        <button class="sheet-close" type="button" data-sheet-close="usage-%s" aria-label="關閉 %s 明細">×</button>
      </header>
      <p class="usage-subtitle">%s</p>
      <div class="sheet-scroll usage-scroll">%s
        <div class="meaning-note">資料來源：%s。時間無可靠證據時顯示未知，不以固定週期推算。</div>
      </div>
    </section>
  ]], esc(id), esc(id), esc(id), esc(id), esc(title), esc(id), esc(title),
    esc(subtitle or "額度視窗與重置時間"), body, esc(source or "unknown"))
end

local function barColor(v)
  if v == nil then return "#8E8E93" end
  local th = resolvedTheme()
  if v >= 90 then return "#FF453A" end
  if v >= 70 then return th.chart_warn or th.blue or "#FF9F0A" end
  if v >= 40 then return th.chart_primary or th.blue or "#0A84FF" end
  return th.chart_ok or th.chart_free or "#30D158"
end

local function applyThemeMaterial(tid)
  local th = THEMES[tid]
  if not th or type(th.material) ~= "table" then return end
  prefs.opacity = clamp(th.material.opacity or prefs.opacity, 0.18, 0.98)
  prefs.blur = clamp(th.material.blur or prefs.blur, 8, 80)
  prefs.saturate = clamp(th.material.saturate or prefs.saturate, 80, 240)
  prefs.glass_preset = "custom"
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

local PROVIDER_META = {
  claude = { label = "Claude", accent = "#D97757" },
  codex = { label = "Codex", accent = "#10A37F" },
  go = { label = "OpenCode Go", accent = "#FF9F0A" },
  grok = { label = "Grok", accent = "#BF5AF2" },
  antigravity = { label = "Antigravity", accent = "#4285F4" },
  mac = { label = "Mac", accent = "#0A84FF" },
}
local TOKEN_SOURCE_META = {
  claude = { label = "Claude", accent = "#D97757" },
  codex = { label = "Codex", accent = "#10A37F" },
  free = { label = "免費雲端", accent = "#30D158" },
  ["local"] = { label = "本地算力", accent = "#64D2FF" },
  other = { label = "其他", accent = "#8E8E93" },
}
local TOKEN_KPI_META = {
  ["3d"] = { label = "近 3 日", accent = "#0A84FF" },
  ["7d"] = { label = "近 7 日", accent = "#0A84FF" },
  ["30d"] = { label = "近 30 日", accent = "#0A84FF" },
}

local function themedSourceAccent(id, fallback)
  local th = resolvedTheme()
  if id == "free" then return th.chart_free or fallback end
  if id == "local" then return th.chart_local or fallback end
  if id == "claude" then return th.chart_primary or th.blue or fallback end
  if id == "codex" then return th.chart_secondary or th.blue or fallback end
  if id == "3d" or id == "7d" or id == "30d" then return th.chart_primary or th.blue or fallback end
  return fallback
end
local SECTION_META = {
  compute = { label = "算力與 Token", fixed = true },
  radar = { label = "壓力雷達" },
  loaders = { label = "額度圓環" },
  providers = { label = "服務與主機" },
}

-- Apple Settings–style reorder control (line.horizontal.3)
local SORT_GRIP_SVG = [[<svg class="sort-grip-icon" viewBox="0 0 22 14" width="22" height="14" aria-hidden="true"><path fill="currentColor" d="M1 1.5h20a1 1 0 0 1 0 2H1a1 1 0 1 1 0-2zm0 5h20a1 1 0 0 1 0 2H1a1 1 0 1 1 0-2zm0 5h20a1 1 0 0 1 0 2H1a1 1 0 1 1 0-2z"/></svg>]]

local function sortRowHTML(group, id, label, accent, fixed)
  if fixed then
    return string.format([[
      <div class="sort-row is-fixed" data-sort-group="%s" data-sort-id="%s" role="listitem">
        <span class="sort-leading"><span class="sort-dot" style="background:%s"></span></span>
        <span class="sort-label">%s</span>
        <span class="sort-trailing sort-fixed-label">固定</span>
      </div>
    ]], esc(group), esc(id), accent or "#8E8E93", esc(label))
  end
  return string.format([[
    <div class="sort-row" data-sort-group="%s" data-sort-id="%s" role="listitem">
      <span class="sort-leading"><span class="sort-dot" style="background:%s"></span></span>
      <span class="sort-label">%s</span>
      <button type="button" class="sort-grip" data-sort-grip="true" aria-label="重新排序 %s">%s</button>
    </div>
  ]], esc(group), esc(id), accent or "#8E8E93", esc(label), esc(label), SORT_GRIP_SVG)
end

local function sortListHTML(group, order, meta)
  local rows = ""
  for _, id in ipairs(order) do
    local m = meta[id] or { label = id, accent = "#8E8E93" }
    rows = rows .. sortRowHTML(group, id, m.label, m.accent, m.fixed == true)
  end
  return string.format(
    '<div class="sort-list" data-sort-list="%s" role="list">%s</div>',
    esc(group), rows
  )
end

local function sortSectionHTML(title, footer, listHtml)
  return string.format([[
    <section class="sort-section">
      <h3 class="sort-section-title">%s</h3>
      %s
      %s
    </section>
  ]], esc(title), listHtml,
    footer and ('<p class="sort-section-footer">' .. esc(footer) .. "</p>") or "")
end

local function layoutReorderSheetHTML()
  local sectionOrder = normalizedSectionOrder(prefs.section_order)
  local providerOrder = normalizedTileOrder("providers", prefs.provider_order)
  local sourceOrder = normalizedTileOrder("token_sources", prefs.token_source_order)
  local kpiOrder = normalizedTileOrder("token_kpis", prefs.token_kpi_order)
  -- Mirrors iOS Settings edit/reorder: nav bar + Done, inset grouped lists,
  -- right-edge drag control only (HIG Lists and tables).
  return string.format([[
    <div class="sheet-backdrop" data-sheet-close="layout" aria-hidden="true"></div>
    <section class="detail-sheet layout-sheet" id="layout-sheet" role="dialog" aria-modal="true"
      aria-labelledby="layout-sheet-title" aria-hidden="true">
      <div class="sheet-grabber"></div>
      <header class="layout-nav" role="navigation">
        <button type="button" class="layout-nav-btn layout-nav-cancel" data-action="layout-done" aria-label="取消">取消</button>
        <h2 id="layout-sheet-title" class="layout-nav-title">編輯排序</h2>
        <button type="button" class="layout-nav-btn layout-nav-done" data-action="layout-done" aria-label="完成">完成</button>
      </header>
      <div class="sheet-scroll layout-scroll">
        %s
        %s
        %s
        %s
        <button type="button" class="layout-reset" data-action="reset-layout">還原預設排序</button>
      </div>
    </section>
  ]],
    sortSectionHTML("服務卡片", "按住右側控制項拖移，調整 Claude、Codex 等卡片順序。",
      sortListHTML("providers", providerOrder, PROVIDER_META)),
    sortSectionHTML("Token 來源", nil, sortListHTML("token_sources", sourceOrder, TOKEN_SOURCE_META)),
    sortSectionHTML("時間窗", nil, sortListHTML("token_kpis", kpiOrder, TOKEN_KPI_META)),
    sortSectionHTML("儀表板區塊", "「算力與 Token」固定在最上方。",
      sortListHTML("sections", sectionOrder, SECTION_META))
  )
end

local function rowHTML(opts)
  -- opts: id, name, badge, main, sub, bars = {{label, pct}, ...}
  -- In circle mode, cards stay compact (text only); hero rings are rendered separately.
  local chart = prefs.chart or "bar"
  local meters = ""
  if chart ~= "circle" then
    for _, b in ipairs(opts.bars or {}) do
      local p = pct(b.pct)
      meters = meters .. meterBar(b.label, p, barColor(p))
    end
  end
  local openAttrs = ""
  local chevron = ""
  if opts.usage_sheet ~= false then
    openAttrs = string.format(' data-sheet-open="usage-%s" tabindex="0" role="button" aria-label="開啟 %s Usage 與重置時間"',
      esc(opts.id or "unknown"), esc(opts.name or "Usage"))
    chevron = '<span class="usage-chevron" aria-hidden="true">›</span>'
  end

  return string.format([[
    <article class="card provider-usage-card"%s>
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
      %s
    </article>
  ]],
    openAttrs,
    opts.accent or "#0A84FF",
    esc(opts.name),
    opts.badge and ('<span class="badge">' .. esc(opts.badge) .. "</span>") or "",
    esc(opts.main or ""),
    esc(opts.sub or ""),
    meters, chevron
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
  local ag = s.antigravity or {}
  add("C", "Claude", cl.ok, cl.five_hour_pct)
  add("G", "Codex", cx.ok, cx.five_hour_pct)
  add("O", "OpenCode", go.ok or go.live_status == "capped",
    go.live_status == "capped" and 100 or go.used_pct)
  add("K", "Grok", gk.ok, gk.used_pct)
  add("A", "Antigravity", ag.ok, ag.used_pct or ag.session_used_pct)
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

local function compactNumber(v)
  local n = tonumber(v)
  if n == nil then return "—" end
  if n >= 1000000000 then return string.format("%.1fB", n / 1000000000) end
  if n >= 1000000 then return string.format("%.1fM", n / 1000000) end
  if n >= 1000 then return string.format("%.1fK", n / 1000) end
  return string.format("%.0f", n)
end

local function money(v)
  local n = tonumber(v)
  if n == nil then return "—" end
  return string.format("$%.2f", n)
end

local function ledgerOverviewHTML(s)
  local ledger = s.ledger or {}
  if ledger.ok ~= true then
    local status = tostring(ledger.status or "missing")
    local labels = {
      missing = "尚未找到成本帳本（cost.db）",
      incompatible = "成本帳本讀取失敗，稍後自動重試",
      busy = "成本帳本忙碌中，請稍候",
      error = "成本帳本暫時不可用",
    }
    local detail = ""
    local warnings = ((ledger.quality or {}).warnings or {})
    if type(warnings) == "table" and warnings[1] then
      detail = string.format('<div class="ledger-empty-detail">%s</div>', esc(tostring(warnings[1])))
    end
    return string.format([[
      <section class="ledger-overview ledger-unavailable" aria-label="成本帳本狀態">
        <div class="section-kicker">COST LEDGER · 更新中</div>
        <div class="ledger-empty">%s</div>
        %s
        <button type="button" class="layout-reset" style="margin-top:12px;color:var(--blue)" data-action="refresh">重新整理帳本</button>
      </section>
    ]], esc(labels[status] or labels.error), detail)
  end

  local totals = ledger.totals or {}
  local fixedValue = totals.fixed_verified and money(totals.fixed_commitment_usd) or "—"
  local fixedNote = totals.fixed_verified and "已驗月費" or "待帳單確認"
  local totalTokens = (tonumber(totals.input_tokens) or 0) + (tonumber(totals.output_tokens) or 0)

  local machineRows = ""
  local machineLabels = { unknown = "Unassigned" }
  for _, item in ipairs(ledger.machines or {}) do
    if type(item) == "table" then
      local key = tostring(item.id or "unknown")
      local events = tonumber(item.events) or 0
      local evidence = events > 0
          and string.format("%s tokens · %d events", compactNumber(item.tokens), events)
        or "No events this month"
      machineRows = machineRows .. string.format([[
      <div class="machine-row">
        <span class="machine-name">%s</span>
        <span class="machine-evidence%s">%s</span>
      </div>
    ]], esc(machineLabels[key] or key), events == 0 and " is-empty" or "", esc(evidence))
    end
  end
  if machineRows == "" then
    machineRows = [[<div class="machine-row"><span class="machine-name">—</span><span class="machine-evidence is-empty">No machine tags</span></div>]]
  end

  local sourceRows = ""
  local classLabels = {
    subscription = "訂閱",
    free_cloud = "免費雲",
    local_compute = "本地",
    metered_paid = "按量付費",
    unknown = "未知",
  }
  local sourceLabels = {
    ["claude-code-oauth-quota"] = "Claude Code",
    ["codex-plus-subscription"] = "Codex",
    ["opencode-go-subscription"] = "OpenCode Go",
    ["nim-free-quota"] = "NVIDIA NIM",
    ["cerebras-free"] = "Cerebras",
    ["local-ollama"] = "Ollama",
    ["local-mlx"] = "MLX",
  }
  for i, item in ipairs(ledger.sources or {}) do
    if i > 3 then break end
    if type(item) == "table" then
      local sourceId = tostring(item.id or "unknown")
      sourceRows = sourceRows .. string.format([[
        <div class="source-chip">
          <span>%s</span><b>%s</b><small>%s</small>
        </div>
      ]], esc(sourceLabels[sourceId] or sourceId), esc(compactNumber(item.tokens)),
        esc(classLabels[tostring(item.class or "unknown")] or "未知"))
    end
  end
  if sourceRows == "" then sourceRows = '<div class="source-chip"><span>來源</span><b>—</b><small>無資料</small></div>' end

  local warningLabels = {
    fixed_subscription_missing = "七月固定月費尚未登錄",
    fixed_subscription_unverified = "固定月費尚未驗帳",
    fixed_subscription_table_missing = "固定月費資料表缺少",
    fixed_allocation_unavailable = "月費分攤暫不可用",
    naive_timestamps_assumed_local = "部分時間以台北本地時間解讀",
    invalid_timestamps_skipped = "少量無效時間事件已略過",
    unknown_quota_source = "存在未知額度來源",
    machine_attribution_missing = "存在未歸屬機器事件",
    ledger_stale = "帳本資料已過期",
    period_has_no_events = "本月尚無事件",
  }
  local warnings = {}
  for _, code in ipairs((ledger.quality or {}).warnings or {}) do
    if #warnings >= 3 then break end
    table.insert(warnings, warningLabels[tostring(code)] or "資料品質待確認")
  end
  local qualityHTML = ""
  if #warnings > 0 then
    qualityHTML = '<div class="quality-banner" role="status">' .. esc(table.concat(warnings, " · ")) .. '</div>'
  end

  return string.format([[
    <section class="ledger-overview" aria-label="本月成本帳本總覽">
      <div class="ledger-head">
        <div><div class="section-kicker">COST LEDGER · %s</div><div class="ledger-title">本月成本與算力</div></div>
        <div class="ledger-status"><span class="status-dot"></span>%s</div>
      </div>
      <div class="kpi-grid">
        <div class="kpi"><span>按量實付</span><strong>%s</strong><small>不含月費</small></div>
        <div class="kpi"><span>固定承諾</span><strong>%s</strong><small>%s</small></div>
        <div class="kpi"><span>影子價值</span><strong>%s</strong><small>獨立情境值</small></div>
        <div class="kpi"><span>本月活動</span><strong>%s</strong><small>%s events</small></div>
      </div>
      <div class="machine-list">%s</div>
      <div class="priority-head">主要算力來源</div>
      <div class="source-strip">%s</div>
      %s
    </section>
  ]], esc(tostring(ledger.period or "—")), esc((ledger.quality or {}).level == "ok" and "已對帳" or "需留意"),
    esc(money(totals.cash_metered_usd)), esc(fixedValue), esc(fixedNote),
    esc(money(totals.shadow_value_usd)), esc(compactNumber(totalTokens)), esc(tostring(totals.events or 0)),
    machineRows, sourceRows, qualityHTML)
end

local function ledgerDetailHTML(s)
  local ledger = s.ledger or {}
  local totals = ledger.totals or {}
  local function rows(items, labels)
    local html = ""
    for _, item in ipairs(items or {}) do
      if type(item) == "table" then
        local id = tostring(item.id or "unknown")
        html = html .. string.format([[
          <div class="detail-row">
            <div><b>%s</b><small>%s events · %s tokens</small></div>
            <div class="detail-money"><b>%s</b><small>影子 %s</small></div>
          </div>
        ]], esc((labels or {})[id] or id), esc(tostring(item.events or 0)),
          esc(compactNumber(item.tokens)), esc(money(item.cash_usd)), esc(money(item.shadow_usd)))
      end
    end
    return html ~= "" and html or '<div class="detail-empty">尚無本月資料</div>'
  end

  local sourceLabels = {
    ["claude-code-oauth-quota"] = "Claude Code 訂閱",
    ["codex-plus-subscription"] = "Codex 訂閱",
    ["opencode-go-subscription"] = "OpenCode Go 訂閱",
    ["nim-free-quota"] = "NVIDIA NIM 免費額度",
    ["cerebras-free"] = "Cerebras 免費額度",
    ["local-ollama"] = "Ollama 本地算力",
    ["local-mlx"] = "MLX 本地算力",
  }
  local machineLabels = { unknown = "Unassigned" }
  local classLabels = {
    subscription = "訂閱制", free_cloud = "免費雲端", local_compute = "本地算力",
    metered_paid = "按量付費", unknown = "未知來源",
  }
  local fixed = totals.fixed_verified and money(totals.fixed_commitment_usd) or "待帳單確認"
  return string.format([[
    <div class="sheet-backdrop" data-sheet-close="ledger" aria-hidden="true"></div>
    <section class="detail-sheet" id="ledger-sheet" role="dialog" aria-modal="true"
      aria-labelledby="ledger-sheet-title" aria-hidden="true">
      <div class="sheet-grabber"></div>
      <header class="sheet-head">
        <div><span>成本帳本 · %s</span><h2 id="ledger-sheet-title">本月完整明細</h2></div>
        <button class="sheet-close" type="button" data-sheet-close="ledger" aria-label="關閉成本明細">×</button>
      </header>
      <div class="sheet-summary">
        <div><span>按量實付</span><b>%s</b></div>
        <div><span>固定承諾</span><b>%s</b></div>
        <div><span>影子價值</span><b>%s</b></div>
      </div>
      <div class="sheet-scroll">
        <h3>算力來源</h3>%s
        <h3>機器歸屬</h3>%s
        <h3>成本分類</h3>%s
        <div class="meaning-note">影子價值是替代成本情境，不等於現金支出；未知與未驗帳會保持未知。</div>
      </div>
    </section>
  ]], esc(tostring(ledger.period or "—")), esc(money(totals.cash_metered_usd)), esc(fixed),
    esc(money(totals.shadow_value_usd)), rows(ledger.sources, sourceLabels),
    rows(ledger.machines, machineLabels), rows(ledger.classes, classLabels))
end

local TOKEN_SOURCE_LABELS = {
  ["claude-code-oauth-quota"] = "Claude Code",
  ["codex-plus-subscription"] = "Codex",
  ["opencode-go-subscription"] = "OpenCode Go",
  ["grok-build-subscription"] = "Grok Build",
  ["antigravity-google-ai-pro-subscription"] = "Antigravity",
  ["nim-free-quota"] = "NVIDIA NIM",
  ["cerebras-free"] = "Cerebras",
  ["local-ollama"] = "Ollama",
  ["local-mlx"] = "MLX",
}

local function share(value, total)
  local v, t = tonumber(value) or 0, tonumber(total) or 0
  if t <= 0 then return 0 end
  return math.floor(v * 1000 / t + 0.5) / 10
end

local function tokenTrendHTML(points, days, label)
  local list = points or {}
  local startIndex = math.max(1, #list - (days or 30) + 1)
  local maxTokens = 0
  for index = startIndex, #list do
    maxTokens = math.max(maxTokens, tonumber(list[index].tokens) or 0)
  end
  local bars = ""
  for index = startIndex, #list do
    local point = list[index] or {}
    local tokens = tonumber(point.tokens) or 0
    local height = maxTokens > 0 and math.max(5, math.floor(tokens * 100 / maxTokens + .5)) or 5
    bars = bars .. string.format('<span style="height:%d%%" title="%s · %s Token"></span>',
      height, esc(point.date or "—"), esc(compactNumber(tokens)))
  end
  return string.format([[
    <div class="token-trend" role="img" aria-label="%s每日 Token 趨勢">
      <div class="trend-head"><span>%s</span><small>每日 Token</small></div>
      <div class="trend-bars">%s</div>
    </div>
  ]], esc(label or "近 30 日"), esc(label or "近 30 日趨勢"), bars)
end

local function computeTrendLineHTML(points)
  local list = points or {}
  local maxTokens = 0
  for _, point in ipairs(list) do
    maxTokens = math.max(maxTokens, tonumber(point.free_cloud) or 0, tonumber(point.local_compute) or 0)
  end
  local freePoints, localPoints = {}, {}
  local count = math.max(1, #list)
  for index, point in ipairs(list) do
    local x = count > 1 and ((index - 1) * 300 / (count - 1)) or 0
    local freeY = maxTokens > 0 and (74 - (tonumber(point.free_cloud) or 0) * 62 / maxTokens) or 74
    local localY = maxTokens > 0 and (74 - (tonumber(point.local_compute) or 0) * 62 / maxTokens) or 74
    table.insert(freePoints, string.format("%.1f,%.1f", x, freeY))
    table.insert(localPoints, string.format("%.1f,%.1f", x, localY))
  end
  local latest = list[#list] or {}
  return string.format([[
    <div class="compute-line-chart" role="img" aria-label="近 30 日免費雲端與本地算力 Token 線圖">
      <div class="trend-head"><span>近 30 日算力走勢</span><small>每日 Token</small></div>
      <svg viewBox="0 0 300 82" preserveAspectRatio="none" aria-hidden="true">
        <path class="chart-grid" d="M0 12H300 M0 43H300 M0 74H300" />
        <polyline class="compute-line free-line" points="%s" />
        <polyline class="compute-line local-line" points="%s" />
      </svg>
      <div class="line-legend">
        <span class="free-legend">免費雲 <b>%s</b></span>
        <span class="local-legend">本地 <b>%s</b></span>
      </div>
    </div>
  ]], table.concat(freePoints, " "), table.concat(localPoints, " "),
    esc(compactNumber(latest.free_cloud or 0)), esc(compactNumber(latest.local_compute or 0)))
end

local function tokenSourceLineHTML(points, days, label)
  local list = points or {}
  local startIndex = math.max(1, #list - (days or 30) + 1)
  local series = {
    { id="claude", label="Claude", class="claude-line" },
    { id="codex", label="Codex", class="codex-line" },
    { id="free_cloud", label="免費雲", class="free-line" },
    { id="local_compute", label="本地", class="local-line" },
    { id="other", label="其他", class="other-line" },
  }
  local maxTokens, periodTotal = 0, 0
  for index = startIndex, #list do
    local point = list[index] or {}
    periodTotal = periodTotal + (tonumber(point.tokens) or 0)
    for _, item in ipairs(series) do maxTokens = math.max(maxTokens, tonumber(point[item.id]) or 0) end
  end
  local count = math.max(1, #list - startIndex + 1)
  local lines, legends = "", ""
  for _, item in ipairs(series) do
    local coords, total = {}, 0
    for index = startIndex, #list do
      local value = tonumber((list[index] or {})[item.id]) or 0
      total = total + value
      local x = count > 1 and ((index - startIndex) * 300 / (count - 1)) or 0
      local y = maxTokens > 0 and (82 - value * 70 / maxTokens) or 82
      table.insert(coords, string.format("%.1f,%.1f", x, y))
    end
    lines = lines .. string.format('<polyline class="source-line %s" points="%s" />', item.class, table.concat(coords, " "))
    legends = legends .. string.format('<div class="source-legend %s-legend"><span>%s</span><b>%s</b><small>%.1f%%</small></div>',
      item.id:gsub("_", "-"), esc(item.label), esc(compactNumber(total)), share(total, periodTotal))
  end
  return string.format([[
    <div class="source-line-chart" role="img" aria-label="%s五類 Token 來源線圖">
      <div class="trend-head"><span>%s</span><small>同尺度 · 每日 Token</small></div>
      <svg viewBox="0 0 300 90" preserveAspectRatio="none" aria-hidden="true">
        <path class="chart-grid" d="M0 12H300 M0 47H300 M0 82H300" />%s
      </svg>
      <div class="source-legends">%s</div>
    </div>
  ]], esc(label), esc(label), lines, legends)
end

local function tokenLedgerOverviewHTML(s)
  local ledger = s.ledger or {}
  if ledger.ok ~= true then return ledgerOverviewHTML(s) end
  local windows = ledger.windows or {}
  local trend = ledger.trend_30d or {}
  local recent, week, month = windows["3d"] or {}, windows["7d"] or {}, windows["30d"] or {}
  local compute = ledger.compute_capacity or {}
  local free = compute.free_cloud or {}
  local localCompute = compute.local_compute or {}
  local sourceTokens = {}
  for _, item in ipairs(month.sources or {}) do
    sourceTokens[tostring(item.id or "unknown")] = tonumber(item.tokens) or 0
  end
  local claudeTokens = sourceTokens["claude-code-oauth-quota"] or 0
  local codexTokens = sourceTokens["codex-plus-subscription"] or 0
  local freeTokens = tonumber(free.tokens) or 0
  local localTokens = tonumber(localCompute.tokens) or 0
  local otherTokens = math.max(0, (tonumber(month.tokens) or 0) - claudeTokens - codexTokens - freeTokens - localTokens)
  local function metricChip(tileId, label, tokens, sheet, extraClass)
    return string.format([[
      <div class="source-chip token-source %s" data-sheet-open="%s" tabindex="0" role="button">
        <span>%s</span><b>%s</b><small>%.1f%%</small>
      </div>
    ]], extraClass or "", sheet, esc(label), esc(compactNumber(tokens)), share(tokens, month.tokens))
  end
  local sourceTiles = {
    claude = metricChip("claude", "Claude", claudeTokens, "ledger", "claude-metric"),
    codex = metricChip("codex", "Codex", codexTokens, "ledger", "codex-metric"),
    free = metricChip("free", "免費雲端", freeTokens, "compute", "free-metric"),
    other = metricChip("other", "其他", otherTokens, "ledger", "other-metric"),
  }
  sourceTiles["local"] = metricChip("local", "本地算力", localTokens, "compute", "local-metric")
  local topSources = ""
  for _, id in ipairs(normalizedTileOrder("token_sources", prefs.token_source_order)) do
    topSources = topSources .. (sourceTiles[id] or "")
  end
  if topSources == "" then topSources = '<div class="source-chip"><span>平台</span><b>—</b><small>無資料</small></div>' end

  local warningLabels = {
    naive_timestamps_assumed_local = "部分時間以台北時間解讀",
    invalid_timestamps_skipped = "少量無效事件已略過",
    unknown_quota_source = "存在未知平台來源",
    machine_attribution_missing = "存在未歸屬機器",
    ledger_stale = "Token 帳本資料已過期",
  }
  local warnings = {}
  for _, code in ipairs((ledger.quality or {}).warnings or {}) do
    if warningLabels[tostring(code)] and #warnings < 2 then table.insert(warnings, warningLabels[tostring(code)]) end
  end
  local quality = #warnings > 0
      and '<div class="quality-banner" role="status">' .. esc(table.concat(warnings, " · ")) .. '</div>' or ""

  local kpiTiles = {
    ["3d"] = string.format(
      [[<button type="button" class="kpi window-kpi" data-sheet-open="ledger" data-window-target="3d"><span>近 3 日</span><strong>%s</strong><small>%.1f%%／近 30 日</small></button>]],
      esc(compactNumber(recent.tokens)), share(recent.tokens, month.tokens)
    ),
    ["7d"] = string.format(
      [[<button type="button" class="kpi window-kpi" data-sheet-open="ledger" data-window-target="7d"><span>近 7 日</span><strong>%s</strong><small>%.1f%%／近 30 日</small></button>]],
      esc(compactNumber(week.tokens)), share(week.tokens, month.tokens)
    ),
    ["30d"] = string.format(
      [[<button type="button" class="kpi window-kpi" data-sheet-open="ledger" data-window-target="30d"><span>近 30 日</span><strong>%s</strong><small>%s events</small></button>]],
      esc(compactNumber(month.tokens)), esc(tostring(month.events or 0))
    ),
  }
  local kpiHtml = ""
  for _, id in ipairs(normalizedTileOrder("token_kpis", prefs.token_kpi_order)) do
    kpiHtml = kpiHtml .. (kpiTiles[id] or "")
  end

  local totals = ledger.totals or {}
  local shadow = money(totals.shadow_value_usd)
  local cash = money(totals.cash_metered_usd)
  local events = tostring(totals.events or month.events or 0)
  local costStrip = string.format([[
    <div class="cost-strip" data-sheet-open="ledger" tabindex="0" role="button" aria-label="本月成本摘要">
      <div class="cost-chip"><span>Shadow</span><b>%s</b></div>
      <div class="cost-chip"><span>Cash</span><b>%s</b></div>
      <div class="cost-chip"><span>Events</span><b>%s</b></div>
    </div>
  ]], esc(shadow), esc(cash), esc(events))

  return string.format([[
    <section class="ledger-overview token-overview" aria-label="Token 使用研究總覽">
      <div class="ledger-head">
        <div><div class="section-kicker">TOKEN LEDGER · %s</div><div class="ledger-title">Token 使用研究</div></div>
        <div class="ledger-actions">
          <button type="button" data-sheet-open="compute">算力</button>
          <button type="button" data-sheet-open="ledger">Token</button>
        </div>
      </div>
      %s
      <div class="kpi-grid token-kpis">%s</div>
      %s
      <div class="token-share-track"><span style="width:%.1f%%"></span></div>
      <div class="priority-head">近 30 日 Token 來源</div>
      <div class="source-strip">%s</div>
      %s
    </section>
  ]], esc(tostring(ledger.period or "—")), costStrip, kpiHtml, computeTrendLineHTML(trend),
    share(week.tokens, month.tokens), topSources, quality)
end

local function tokenRows(items, total, labels, limit)
  local html = ""
  for index, item in ipairs(items or {}) do
    if index > (limit or 12) then break end
    local id = tostring(item.id or "unknown")
    local percent = share(item.tokens, total)
    html = html .. string.format([[
      <div class="token-row">
        <div class="token-row-head"><span>%s</span><b>%s <small>%.1f%%</small></b></div>
        <div class="token-row-track"><span style="width:%.1f%%"></span></div>
      </div>
    ]], esc((labels or {})[id] or id), esc(compactNumber(item.tokens)), percent, percent)
  end
  return html ~= "" and html or '<div class="detail-empty">這個時間窗尚無 Token 資料</div>'
end

local function tokenWindowPanel(name, window, active, trend)
  window = window or {}
  local localItems = {}
  for _, item in ipairs(window.sources or {}) do
    if tostring(item.class or "") == "local_compute" then table.insert(localItems, item) end
  end
  return string.format([[
    <div class="window-panel%s" data-window-panel="%s">
      <div class="window-hero"><span>總 Token</span><strong>%s</strong><small>%s events · 本地 %.1f%%</small></div>
      %s
      <h3>各平台 Token</h3>%s
      <h3>本地算力</h3>%s
      <h3>各專案 Token</h3>%s
    </div>
  ]], active and " is-active" or "", esc(name), esc(compactNumber(window.tokens)),
    esc(tostring(window.events or 0)), tonumber(window.local_share_pct) or 0,
    tokenSourceLineHTML(trend, name == "7d" and 7 or (name == "3d" and 3 or 30), "近 " .. name .. " Token 來源趨勢"),
    tokenRows(window.sources, window.tokens, TOKEN_SOURCE_LABELS, 12),
    tokenRows(localItems, window.local_tokens, TOKEN_SOURCE_LABELS, 8),
    tokenRows(window.projects, window.tokens, nil, 12))
end

local function tokenLedgerDetailHTML(s)
  local ledger = s.ledger or {}
  local windows = ledger.windows or {}
  return string.format([[
    <div class="sheet-backdrop" data-sheet-close="ledger" aria-hidden="true"></div>
    <section class="detail-sheet token-sheet" id="ledger-sheet" role="dialog" aria-modal="true"
      aria-labelledby="ledger-sheet-title" aria-hidden="true">
      <div class="sheet-grabber"></div>
      <header class="sheet-head">
        <div><span>TOKEN ANALYTICS</span><h2 id="ledger-sheet-title">Token 使用分析</h2></div>
        <button class="sheet-close" type="button" data-sheet-close="ledger" aria-label="關閉 Token 分析">×</button>
      </header>
      <div class="window-tabs" role="tablist" aria-label="Token 時間範圍">
        <button class="is-active" type="button" data-window="7d">近 7 日</button>
        <button type="button" data-window="3d">近 3 日</button>
        <button type="button" data-window="30d">近 30 日</button>
      </div>
      <div class="sheet-scroll">
        %s%s%s
        <div class="meaning-note">平台與專案比例以所選時間窗 Token 總量計算；本地算力包含 local-ollama 與 local-mlx 等明確本地來源。</div>
      </div>
    </section>
  ]], tokenWindowPanel("7d", windows["7d"], true, ledger.trend_30d), tokenWindowPanel("3d", windows["3d"], false, ledger.trend_30d),
    tokenWindowPanel("30d", windows["30d"], false, ledger.trend_30d))
end

local function computeCapacityOverviewHTML(s)
  local compute = (s.ledger or {}).compute_capacity or {}
  local free = compute.free_cloud or {}
  local localCompute = compute.local_compute or {}
  local combined = compute.combined or {}
  local slotCount = free.credential_slot_count or free.api_key_count or 0
  local coverage = tonumber(free.coverage_score)
  local coverageText = coverage and string.format("覆蓋 %.1f%%", coverage) or "覆蓋未知"
  local purpose = "尚無已歸屬 Key 用途"
  local firstKey = (free.keys or {})[1]
  if type(firstKey) == "table" and type((firstKey.scenarios or {})[1]) == "table" then
    purpose = tostring(firstKey.scenarios[1].label or purpose)
  end
  return string.format([[
    <section class="compute-overview" aria-label="免費雲端與本地算力總覽">
      <div class="ledger-head">
        <div><div class="section-kicker">COMPUTE CAPACITY · 近 30 日</div><div class="ledger-title">免費雲端＋本地算力</div></div>
        <div class="ledger-status"><span class="status-dot compute-dot"></span>點擊看 Slot</div>
      </div>
      <div class="compute-grid">
        <div class="compute-stat free-stat"><span>免費雲端 · 第一級</span><strong>%s</strong><small>%s 個匿名 credential slot</small></div>
        <div class="compute-stat local-stat"><span>本地算力</span><strong>%s</strong><small>Ollama／MLX</small></div>
        <div class="compute-stat combined-stat"><span>合計</span><strong>%s</strong><small>免費 %.1f%% · 本地 %.1f%%</small></div>
      </div>
      <div class="compute-ratio" aria-label="免費雲與本地算力比例">
        <span class="free-ratio" style="width:%.1f%%"></span><span class="local-ratio" style="width:%.1f%%"></span>
      </div>
      <div class="compute-trust"><span>%s</span><b>%s 筆未歸屬事件</b></div>
      <div class="compute-purpose"><span>主要用途</span><b>%s</b></div>
    </section>
  ]], esc(compactNumber(free.tokens)), esc(tostring(slotCount)),
    esc(compactNumber(localCompute.tokens)), esc(compactNumber(combined.tokens)),
    tonumber(free.share_pct) or 0, tonumber(localCompute.share_pct) or 0,
    tonumber(free.share_pct) or 0, tonumber(localCompute.share_pct) or 0,
    esc(coverageText), esc(tostring(free.unattributed_events or 0)), esc(purpose))
end

local function keyDetailRows(keys, freeTotal)
  local html = ""
  for _, key in ipairs(keys or {}) do
    if type(key) == "table" then
      local scenarios, sources = "", ""
      for _, item in ipairs(key.scenarios or {}) do
        scenarios = scenarios .. string.format('<li><span>%s</span><b>%s</b></li>',
          esc(item.label or "未標記用途"), esc(compactNumber(item.tokens)))
      end
      for _, item in ipairs(key.sources or {}) do
        local sourceId = tostring(item.id or "unknown")
        sources = sources .. string.format('<span class="key-source">%s · %s</span>',
          esc(TOKEN_SOURCE_LABELS[sourceId] or sourceId), esc(compactNumber(item.tokens)))
      end
      html = html .. string.format([[
        <details class="key-card">
          <summary>
            <span><b>%s</b><small>%s events · %.1f%% 免費雲</small></span>
            <strong>%s</strong>
          </summary>
          <div class="key-body">
            <div class="key-sources">%s</div>
            <h4>使用場景</h4><ul>%s</ul>
          </div>
        </details>
      ]], esc(key.id or "key-unknown"), esc(tostring(key.events or 0)), share(key.tokens, freeTotal),
        esc(compactNumber(key.tokens)), sources, scenarios ~= "" and scenarios or '<li><span>未標記用途</span></li>')
    end
  end
  return html ~= "" and html or '<div class="detail-empty">目前沒有可辨識的免費雲 credential slot；這不代表使用量為零。</div>'
end

local function computeCapacityDetailHTML(s)
  local compute = (s.ledger or {}).compute_capacity or {}
  local free = compute.free_cloud or {}
  local localCompute = compute.local_compute or {}
  local combined = compute.combined or {}
  local slotCount = free.credential_slot_count or free.api_key_count or 0
  local coverage = tonumber(free.coverage_score)
  local coverageText = coverage and string.format("%.1f%%", coverage) or "未知"
  return string.format([[
    <div class="sheet-backdrop" data-sheet-close="compute" aria-hidden="true"></div>
    <section class="detail-sheet compute-sheet" id="compute-sheet" role="dialog" aria-modal="true"
      aria-labelledby="compute-sheet-title" aria-hidden="true">
      <div class="sheet-grabber"></div>
      <header class="sheet-head">
        <div><span>COMPUTE CAPACITY · 近 30 日</span><h2 id="compute-sheet-title">免費雲端與本地算力</h2></div>
        <button class="sheet-close" type="button" data-sheet-close="compute" aria-label="關閉算力明細">×</button>
      </header>
      <div class="sheet-summary compute-summary">
        <div><span>免費雲端</span><b>%s</b><small>%s credential slots</small></div>
        <div><span>本地算力</span><b>%s</b><small>%.1f%%</small></div>
        <div><span>兩者合計</span><b>%s</b><small>100%%</small></div>
      </div>
      <div class="sheet-scroll">
        <div class="coverage-callout"><span>資料覆蓋</span><strong>%s</strong><small>%s · 未歸屬不等於零使用</small></div>
        <h3>Credential Slot 與用途</h3>
        %s
        <div class="meaning-note">Slot 是穩定匿名歸因單位，不是平台數，也不顯示原始 API 金鑰。另有 %s 筆、%s Token 尚未歸屬到 Slot。</div>
        <h3>免費雲端平台</h3>%s
        <h3>本地算力來源</h3>%s
      </div>
    </section>
  ]], esc(compactNumber(free.tokens)), esc(tostring(slotCount)),
    esc(compactNumber(localCompute.tokens)), tonumber(localCompute.share_pct) or 0,
    esc(compactNumber(combined.tokens)), esc(coverageText), esc(tostring(free.confidence_state or "unknown")), keyDetailRows(free.keys, free.tokens),
    esc(tostring(free.unattributed_events or 0)), esc(compactNumber(free.unattributed_tokens)),
    tokenRows(free.sources, free.tokens, TOKEN_SOURCE_LABELS, 12),
    tokenRows(localCompute.sources, localCompute.tokens, TOKEN_SOURCE_LABELS, 12))
end

local function computeLensHTML(s)
  return string.format('<div class="compute-lens">%s</div>', tokenLedgerOverviewHTML(s))
end

local function sectionFrame(id, title, content, options)
  options = options or {}
  if content == nil or content == "" then return "" end
  local clickable = options.sheet and string.format(' data-sheet-open="%s" tabindex="0" role="button"', esc(options.sheet)) or ""
  local chevron = options.sheet and '<span class="section-chevron">›</span>' or ""
  -- Reorder lives in the dedicated 排序 sheet — dashboard stays clean.
  return string.format([[
    <section class="dashboard-section" data-section-id="%s" draggable="false">
      <div class="section-content"%s>%s%s</div>
    </section>
  ]], esc(id), clickable, content or "", chevron)
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

  local ag = s.antigravity or {}
  local agMain = "離線"
  local agSub = ag.error or "啟動 agy / Antigravity CLI 後顯示"
  local agBars = {}
  if ag.ok then
    local agStale = ag.stale == true
    agMain = pctText(ag.used_pct or ag.session_used_pct)
      .. (agStale and " · 快取" or " · 最緊模型窗")
    agSub = string.format(
      "%s%s · Prompt %s/%s · Flow %s/%s · 重置 %s",
      tostring(ag.plan or "—"),
      agStale and " · 上次連線" or "",
      tostring(ag.prompt_credits_available or "—"),
      tostring(ag.prompt_credits_monthly or "—"),
      tostring(ag.flow_credits_available or "—"),
      tostring(ag.flow_credits_monthly or "—"),
      tostring(ag.next_reset or "—"):sub(1, 16)
    )
    agBars = {
      { label = "Session（最緊模型）", pct = ag.used_pct or ag.session_used_pct },
    }
    local models = ag.models or {}
    local scored = {}
    for _, m in ipairs(models) do
      if type(m) == "table" and m.used_pct ~= nil then
        table.insert(scored, m)
      end
    end
    table.sort(scored, function(a, b)
      return (a.used_pct or 0) > (b.used_pct or 0)
    end)
    for i = 1, math.min(3, #scored) do
      table.insert(agBars, {
        label = tostring(scored[i].label or "model"),
        pct = scored[i].used_pct,
      })
    end
  end

  local providerCards = {
    claude = rowHTML({
      id = "claude",
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
    codex = rowHTML({
      id = "codex",
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
    go = rowHTML({
      id = "go",
      name = "OpenCode Go",
      badge = go.price or "$10/mo",
      accent = "#FF9F0A",
      main = goMain,
      sub = goSub,
      bars = goBars,
    }),
    grok = rowHTML({
      id = "grok",
      name = "Grok",
      badge = "credits",
      accent = "#BF5AF2",
      main = gkMain,
      sub = gkSub,
      bars = gk.ok and {
        { label = "本月額度", pct = gk.used_pct },
      } or {},
    }),
    antigravity = rowHTML({
      id = "antigravity",
      name = "Antigravity",
      badge = ag.ok and tostring(ag.plan or "CLI") or "CLI",
      accent = "#4285F4",
      main = agMain,
      sub = agSub,
      bars = agBars,
    }),
    mac = rowHTML({
      id = "mac",
      usage_sheet = false,
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
  }
  local orderedProviders = {}
  for _, id in ipairs(normalizedTileOrder("providers", prefs.provider_order)) do
    if providerCards[id] then table.insert(orderedProviders, providerCards[id]) end
  end
  local cards = table.concat(orderedProviders, "\n")

  local updated = ""
  if s.polled_at then
    updated = "更新 " .. tostring(s.polled_at):sub(12, 19) .. " UTC"
  end

  local chrome = chromeTokens()
  local th = chrome.th
  local chartLabel = (prefs.chart == "circle") and "圓圈" or "長條"
  local themeLabel = th.name or prefs.theme
  local gLabel = glassLabel()
  local aLabel = accentLabel()
  local op = chrome.op
  local blur = chrome.blur
  local sat = chrome.sat
  local bgCss = chrome.bgCss
  local cardCss = chrome.cardCss
  local isLight = chrome.isLight
  local accent = chrome.accent
  local hero = ""
  if prefs.chart == "circle" then
    hero = heroRingsHTML(s)
  end
  local radar = pressureRadarHTML(s)
  local sections = {
    compute = sectionFrame("compute", "算力與 Token", computeLensHTML(s), { fixed = true }),
    radar = sectionFrame("radar", "壓力雷達", radar),
    loaders = sectionFrame("loaders", "額度圓環", hero),
    providers = sectionFrame("providers", "服務與主機", '<div class="list">' .. cards .. '</div>'),
  }
  local orderedSections = ""
  for _, id in ipairs(normalizedSectionOrder(prefs.section_order)) do
    orderedSections = orderedSections .. (sections[id] or "")
  end
  local goResetAt = type(go.resets_in_sec) == "number" and (os.time() + go.resets_in_sec) or nil
  local agRows = {}
  for index, model in ipairs(ag.models or {}) do
    if index > 8 then break end
    table.insert(agRows, {
      label = tostring(model.label or "Antigravity model"),
      usage = pctText(model.used_pct),
      reset = fmtIsoReset(model.reset_time),
    })
  end
  if #agRows == 0 and ag.next_reset then
    table.insert(agRows, { label = "最緊模型視窗", usage = pctText(ag.used_pct), reset = fmtIsoReset(ag.next_reset) })
  end
  local providerSheets = providerUsageSheetHTML("claude", "Claude Usage", "5 小時與 7 日訂閱額度", {
      { label = "5 小時視窗", usage = pctText(cl.five_hour_pct), reset = fmtResetFull(cl.five_hour_resets_at) },
      { label = "7 日視窗", usage = pctText(cl.seven_day_pct), reset = fmtResetFull(cl.seven_day_resets_at) },
    }, cl.source)
    .. providerUsageSheetHTML("codex", "Codex Usage", tostring(cx.plan_type or "plan") .. " 訂閱額度", {
      { label = "5 小時視窗", usage = pctText(cx.five_hour_pct), reset = fmtResetFull(cx.five_hour_resets_at) },
      { label = "7 日視窗", usage = pctText(cx.seven_day_pct), reset = fmtResetFull(cx.seven_day_resets_at) },
    }, cx.source)
    .. providerUsageSheetHTML("go", "OpenCode Go Usage", tostring(go.limit_name or "官方額度"), {
      { label = tostring(go.limit_name or "目前限制"), usage = pctText(go.used_pct), reset = fmtResetFull(goResetAt) },
    }, go.live_status == "capped" and "OpenCode 官方 429" or "本機成本帳估算")
    .. providerUsageSheetHTML("grok", "Grok Usage", "月額度與 credits", {
      { label = "月額度", usage = pctText(gk.used_pct), reset = fmtIsoReset(gk.period_end) },
    }, gk.source)
    .. providerUsageSheetHTML("antigravity", "Antigravity Usage", "各模型視窗", agRows, ag.source)
  local detailSheets = tokenLedgerDetailHTML(s) .. computeCapacityDetailHTML(s)
    .. providerSheets .. layoutReorderSheetHTML()

  local themeCards = ""
  for _, tid in ipairs(THEME_ORDER) do
    local tmeta = THEMES[tid]
    if tmeta then
      themeCards = themeCards .. string.format(
        [[<button type="button" class="theme-chip%s" data-action="theme:%s" role="option" aria-selected="%s" title="%s">
            <span class="theme-chip-swatch" style="background:%s"></span>
            <span class="theme-chip-name">%s</span>
          </button>]],
        (prefs.theme == tid) and " is-active" or "",
        esc(tid),
        (prefs.theme == tid) and "true" or "false",
        esc((tmeta.blurb or tmeta.name)),
        tmeta.swatch or "#888",
        esc(tmeta.name)
      )
    end
  end

  local accentDots = ""
  local accentTitles = {
    theme = "跟隨主題",
    coral = "Claude 橙",
    green = "Codex 綠",
    blue = "系統藍",
    violet = "紫羅蘭",
    amber = "琥珀",
  }
  for _, aid in ipairs(ACCENT_ORDER) do
    local color = ACCENTS[aid]
    if aid == "theme" then color = th.blue end
    accentDots = accentDots .. string.format(
      [[<button type="button" class="accent-dot%s" data-action="accent:%s" aria-label="%s" title="%s" style="--dot:%s"></button>]],
      (prefs.accent == aid) and " is-active" or "",
      esc(aid),
      esc(accentTitles[aid] or aid),
      esc(accentTitles[aid] or aid),
      color or th.blue
    )
  end

  local glassSeg = ""
  for _, gid in ipairs(GLASS_PRESET_ORDER) do
    local gmeta = GLASS_PRESETS[gid]
    glassSeg = glassSeg .. string.format(
      [[<button type="button" class="seg-item%s" data-action="glass:%s" data-glass="%s">%s</button>]],
      (prefs.glass_preset == gid) and " is-active" or "",
      esc(gid), esc(gid), esc((gmeta and gmeta.name) or gid)
    )
  end

  local auroraCSS = ""

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
    --fill: %s;
    --fill-2: %s;
    --hairline: %s;
    --inset: %s;
    --drop: %s;
    --shell-border: %s;
    --blur: %dpx;
    --sat: %d%%;
    --radius: %dpx;
    --chart-free: %s;
    --chart-local: %s;
    --chart-primary: %s;
    --chart-secondary: %s;
    --chart-warn: %s;
    --chart-ok: %s;
    --ease: cubic-bezier(.22,1,.36,1);
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
  @keyframes panelIn {
    from { opacity: 0; transform: translateY(-8px) scale(.985); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }
  .shell {
    height: 100%%;
    padding: 14px 12px 10px;
    background:
      radial-gradient(130%% 90%% at 0%% 0%%, var(--glow1), transparent 55%%),
      radial-gradient(110%% 80%% at 100%% 100%%, var(--glow2), transparent 50%%),
      var(--bg);
    border-radius: var(--radius, 30px);
    border: 0.5px solid var(--shell-border);
    box-shadow:
      0 28px 70px var(--drop),
      0 1px 0 var(--inset) inset,
      0 0 0 0.5px rgba(0,0,0,0.18) inset;
    animation: panelIn .28s cubic-bezier(.22,1,.36,1) both;
    backdrop-filter: blur(var(--blur)) saturate(var(--sat));
    -webkit-backdrop-filter: blur(var(--blur)) saturate(var(--sat));
    display: flex;
    flex-direction: column;
    gap: 0;
    overflow: hidden;
    transition: background .28s var(--ease), border-color .28s var(--ease),
      border-radius .28s var(--ease), box-shadow .28s var(--ease);
  }
  .shell.is-light {
    box-shadow:
      0 22px 54px var(--drop),
      0 1px 0 var(--inset) inset,
      0 0 0 0.5px rgba(70,50,30,0.08) inset;
  }
  /* Theme personalities — large structural differences, not just tint. */
  .shell[data-theme="notion"] { padding:18px 15px 12px; }
  .shell[data-theme="notion"] .ledger-overview,
  .shell[data-theme="notion"] .card,
  .shell[data-theme="notion"] .kpi {
    border-radius:8px; box-shadow:none; background:var(--card); border:1px solid var(--hairline);
  }
  .shell[data-theme="notion"] .section-kicker { letter-spacing:.03em; text-transform:none; }
  .shell[data-theme="notion"] .title { font-family:ui-serif,"New York",Georgia,serif; letter-spacing:-.025em; }
  .shell[data-theme="notion"] .source-line-chart { background:var(--fill-2); border:1px solid var(--hairline); }
  .shell[data-theme="tableau"] { padding:10px 10px 8px; }
  .shell[data-theme="tableau"] .ledger-overview,
  .shell[data-theme="tableau"] .card { border-radius:10px; box-shadow:0 10px 24px var(--drop); }
  .shell[data-theme="tableau"] .kpi { border-radius:7px; border-left:3px solid var(--chart-primary); }
  .shell[data-theme="tableau"] .source-line-chart { border-radius:8px; border:1px solid var(--hairline); }
  .shell[data-theme="tableau"] .priority-head,
  .shell[data-theme="tableau"] .section-kicker { text-transform:uppercase; letter-spacing:.09em; }
  .shell[data-theme="claude"] .title span { color: var(--blue); }
  .shell[data-theme="claude"] .ledger-overview {
    background:
      linear-gradient(145deg, rgba(224,122,79,.22), transparent 55%%),
      var(--card);
  }
  .shell[data-theme="codex"] {
    font-variant-numeric: tabular-nums;
  }
  .shell[data-theme="codex"] .ledger-overview,
  .shell[data-theme="codex"] .card {
    border-style: solid;
    border-width: 1px;
    box-shadow: 0 0 0 1px rgba(18,212,138,.08), 0 12px 28px var(--drop);
  }
  .shell[data-theme="codex"] .title {
    letter-spacing: 0.04em;
    text-transform: uppercase;
    font-size: 13px;
  }
  .shell[data-theme="glass"] { border-radius: 30px; }
  .shell[data-theme="glass"] .ledger-overview,
  .shell[data-theme="glass"] .card {
    border-radius: 24px;
    backdrop-filter: blur(24px) saturate(180%%);
    -webkit-backdrop-filter: blur(24px) saturate(180%%);
  }
  .shell[data-theme="paper"] {
    background:
      radial-gradient(90%% 70%% at 10%% 0%%, rgba(255,255,255,.95), transparent 50%%),
      radial-gradient(80%% 60%% at 100%% 100%%, rgba(251,191,36,.20), transparent 55%%),
      var(--bg);
  }
  .shell[data-theme="paper"] .card,
  .shell[data-theme="paper"] .ledger-overview {
    box-shadow: 0 1px 0 #fff inset, 0 8px 22px rgba(90,55,20,.10);
  }
  .shell[data-theme="mono"] .card,
  .shell[data-theme="mono"] .ledger-overview,
  .shell[data-theme="mono"] .kpi {
    border-radius: 6px;
    border: 1px solid rgba(255,255,255,.22);
    background: #0A0A0A;
  }
  .shell[data-theme="mono"] .customize .btn.primary {
    background: #0A84FF; color: #fff !important;
  }
  .shell[data-theme="mono"] .title span { color: #fff; opacity: .55; }
  .data {
    flex: 1 1 auto;
    min-height: 0;
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 2px 2px 6px;
    -webkit-overflow-scrolling: touch;
    overscroll-behavior: contain;
    scroll-behavior: smooth;
  }
  .data::-webkit-scrollbar { width: 0; height: 0; }
  .dashboard-section { position: relative; border-radius: 24px; }
  .section-content { position: relative; border-radius: inherit; outline: none; }
  .section-content[data-sheet-open] { cursor: pointer; }
  .section-content[data-sheet-open]:focus-visible { box-shadow: 0 0 0 3px rgba(10,132,255,.45); }
  .section-chevron {
    position: absolute; top: 16px; right: 15px; width: 25px; height: 25px;
    display: flex; align-items: center; justify-content: center; border-radius: 50%%;
    color: var(--label); background: rgba(120,120,128,.18); font-size: 22px; line-height: 1;
  }
  .sheet-close {
    appearance: none; border: 0; color: var(--text); background: rgba(120,120,128,.24);
    border-radius: 9px; min-width: 48px; height: 30px; padding: 0 10px; font: inherit;
    font-size: 13px; font-weight: 650; cursor: pointer;
  }
  /* Apple Settings / HIG: inset grouped list + edit-mode reorder control */
  .layout-sheet {
    background:
      linear-gradient(180deg, rgba(28,28,30,.98), rgba(28,28,30,.94)) !important;
  }
  .layout-nav {
    display: grid;
    grid-template-columns: 72px 1fr 72px;
    align-items: center;
    min-height: 44px;
    margin: 2px 0 10px;
    padding: 0 2px;
  }
  .layout-nav-title {
    margin: 0; text-align: center;
    font-size: 17px; font-weight: 600; letter-spacing: -0.02em;
  }
  .layout-nav-btn {
    appearance: none; border: 0; margin: 0; padding: 8px 4px;
    background: transparent; font: inherit; font-size: 17px;
    cursor: pointer; -webkit-tap-highlight-color: transparent;
  }
  .layout-nav-cancel {
    justify-self: start; color: var(--blue); font-weight: 400;
  }
  .layout-nav-done {
    justify-self: end; color: var(--blue); font-weight: 600;
  }
  .layout-nav-btn:active { opacity: .45; }
  .layout-scroll {
    display: flex; flex-direction: column; gap: 0;
    padding-bottom: 20px;
  }
  .sort-section { margin: 0 0 22px; }
  .sort-section-title {
    margin: 0 16px 7px;
    font-size: 13px; font-weight: 400;
    letter-spacing: -0.01em;
    color: rgba(235,235,245,.55);
    text-transform: none;
  }
  .sort-section-footer {
    margin: 7px 16px 0;
    font-size: 13px; line-height: 1.35;
    color: rgba(235,235,245,.45);
  }
  .sort-list {
    margin: 0 12px;
    border-radius: 12px;
    background: rgba(44,44,46,.92);
    overflow: hidden;
    border: .5px solid rgba(255,255,255,.06);
  }
  .sort-row {
    display: grid;
    grid-template-columns: 28px minmax(0, 1fr) 44px;
    align-items: center;
    min-height: 44px;
    padding: 0 4px 0 14px;
    background: transparent;
    position: relative;
    transition: background .12s ease, box-shadow .12s ease, opacity .12s ease;
    user-select: none; -webkit-user-select: none;
  }
  .sort-row + .sort-row::before {
    content: "";
    position: absolute; left: 42px; right: 0; top: 0; height: .5px;
    background: rgba(84,84,88,.65);
  }
  .sort-row.is-fixed {
    grid-template-columns: 28px minmax(0, 1fr) auto;
    padding-right: 14px;
    opacity: .78;
  }
  .sort-row.is-dragging {
    z-index: 60;
    border-radius: 12px;
    background: rgba(58,58,60,.98);
    box-shadow: 0 10px 28px rgba(0,0,0,.40);
    opacity: .98;
  }
  .sort-row.is-dragging::before { display: none; }
  .sort-placeholder {
    min-height: 44px;
    background: rgba(10,132,255,.08);
  }
  .sort-leading {
    display: flex; align-items: center; justify-content: flex-start;
  }
  .sort-dot {
    width: 9px; height: 9px; border-radius: 50%%;
    box-shadow: 0 0 0 .5px rgba(255,255,255,.12);
  }
  .sort-label {
    font-size: 17px; font-weight: 400;
    letter-spacing: -0.02em;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .sort-fixed-label {
    font-size: 15px; font-weight: 400;
    color: rgba(235,235,245,.42);
    padding-right: 2px;
  }
  .sort-grip {
    appearance: none; border: 0; margin: 0; padding: 0;
    width: 44px; height: 44px;
    display: inline-flex; align-items: center; justify-content: center;
    color: rgba(235,235,245,.42);
    background: transparent;
    cursor: grab; touch-action: none;
    -webkit-tap-highlight-color: transparent;
  }
  .sort-grip:active, .sort-row.is-dragging .sort-grip {
    cursor: grabbing; color: rgba(235,235,245,.72);
  }
  .sort-grip-icon { display: block; pointer-events: none; }
  .layout-reset {
    appearance: none; border: 0;
    margin: 4px 12px 8px; padding: 14px 16px;
    width: calc(100%% - 24px);
    border-radius: 12px;
    color: #FF453A;
    background: rgba(44,44,46,.92);
    border: .5px solid rgba(255,255,255,.06);
    font: inherit; font-size: 17px; font-weight: 400;
    cursor: pointer; text-align: center;
  }
  .layout-reset:active { opacity: .55; }
  .shell.is-compact .data { gap: 8px; }
  .shell.is-compact .card { padding: 9px 12px; }
  .shell.is-compact .sub, .shell.is-compact .meter { display: none; }
  .shell.is-compact .ledger-overview { padding: 12px; }
  .shell.is-compact .machine-list, .shell.is-compact .priority-head, .shell.is-compact .source-strip { display: none; }
  .customize {
    flex: 0 0 auto;
    border-top: .5px solid rgba(255,255,255,0.10);
    padding: 10px 6px 6px;
    margin-top: 2px;
    background:
      linear-gradient(180deg, rgba(0,0,0,0.18), transparent 40px),
      rgba(28,28,30,0.42);
    display: flex;
    flex-direction: column;
    gap: 8px;
    backdrop-filter: blur(28px) saturate(170%%);
    -webkit-backdrop-filter: blur(28px) saturate(170%%);
  }
  .shell.is-light .customize {
    border-top-color: rgba(60,60,67,0.12);
    background:
      linear-gradient(180deg, rgba(255,255,255,0.55), transparent 40px),
      rgba(242,242,247,0.55);
  }
%s
  .top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 2px 4px 2px;
  }
  .top-actions { display: flex; gap: 6px; }
  .top-button {
    appearance: none; border: .5px solid var(--hairline); border-radius: 999px;
    padding: 7px 12px; color: var(--text); background: var(--fill);
    font: inherit; font-size: 11px; font-weight: 650; cursor: pointer;
    min-height: 30px; transition: transform .12s ease, opacity .12s ease, background .15s ease;
  }
  .top-button:active { transform: scale(.97); opacity: .88; }
  .top-button.is-active { color: #fff; background: var(--blue); border-color: transparent; }
  .title {
    font-size: 15px;
    font-weight: 700;
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
    text-align: left;
    padding: 1px 4px 8px;
  }
  .ledger-overview {
    background:
      linear-gradient(145deg, var(--inset), transparent 55%%),
      var(--card);
    border: 0.5px solid var(--card-border);
    border-radius: 22px;
    padding: 14px;
    box-shadow:
      0 1px 0 var(--inset) inset,
      0 14px 32px var(--drop);
  }
  .ledger-head {
    display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
    margin-bottom: 12px;
  }
  .section-kicker {
    font-size: 10px; font-weight: 700; letter-spacing: 0.08em; color: var(--label);
  }
  .ledger-title {
    margin-top: 3px; font-size: 17px; font-weight: 750; letter-spacing: -0.035em;
  }
  .ledger-status {
    display: flex; align-items: center; gap: 5px;
    font-size: 11px; color: var(--sub); white-space: nowrap;
  }
  .status-dot {
    width: 7px; height: 7px; border-radius: 50%%; background: var(--chart-warn);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--chart-warn) 22%%, transparent);
  }
  .kpi-grid {
    display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px;
  }
  .kpi {
    min-width: 0; padding: 10px 11px;
    border-radius: 14px;
    background: var(--fill);
    border: 0.5px solid var(--hairline);
  }
  .kpi span, .kpi small { display: block; color: var(--sub); font-size: 11px; }
  .kpi strong {
    display: block; margin: 4px 0 2px; font-size: 22px; line-height: 1;
    letter-spacing: -0.055em; font-variant-numeric: tabular-nums; white-space: nowrap;
  }
  .machine-list {
    display: grid; gap: 6px; margin-top: 12px; padding-top: 10px;
    border-top: 0.5px solid var(--card-border);
  }
  .machine-row { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; }
  .machine-name { font-weight: 650; }
  .machine-evidence { color: var(--sub); font-variant-numeric: tabular-nums; text-align: right; }
  .machine-evidence.is-empty { opacity: 0.72; }
  .priority-head { margin: 12px 0 6px; font-size: 11px; font-weight: 650; color: var(--label); }
  .source-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
  .source-chip {
    min-width: 0; padding: 8px 9px; border-radius: 12px;
    background: var(--fill);
    border: 0.5px solid var(--hairline);
  }
  .source-chip span, .source-chip b, .source-chip small {
    display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .source-chip span { font-size: 10px; color: var(--sub); }
  .source-chip b { margin-top: 3px; font-size: 13px; font-variant-numeric: tabular-nums; }
  .source-chip small { margin-top: 1px; font-size: 10px; color: var(--label); }
  .quality-banner {
    margin-top: 10px; padding: 8px 10px; border-radius: 11px;
    color: #FFD18A; background: rgba(255,159,10,0.12);
    border: 0.5px solid rgba(255,159,10,0.25); font-size: 11px; line-height: 1.35;
  }
  .ledger-unavailable { padding: 16px; }
  .ledger-empty { margin-top: 6px; font-size: 14px; font-weight: 650; }
  .ledger-empty-detail { margin-top: 6px; font-size: 12px; color: var(--sub); }
  .cost-strip {
    display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px;
    margin: 0 0 10px; cursor: pointer;
  }
  .cost-chip {
    min-width: 0; padding: 10px 11px; border-radius: 14px;
    background: var(--fill); border: 0.5px solid var(--hairline);
  }
  .cost-chip span { display: block; font-size: 11px; color: var(--sub); }
  .cost-chip b {
    display: block; margin-top: 4px; font-size: 16px; letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
  }
  /*
   * Customize strip uses locked Apple Control Center tokens.
   * Theme may recolor the dashboard, but control labels stay readable.
   */
  .customize {
    --ctl-text: rgba(245,245,247,0.98);
    --ctl-sub: rgba(235,235,245,0.68);
    --ctl-fill: rgba(120,120,128,0.30);
    --ctl-fill-2: rgba(120,120,128,0.20);
    --ctl-border: rgba(255,255,255,0.14);
    --ctl-surface: rgba(44,44,46,0.78);
    --ctl-active: rgba(10,132,255,0.28);
  }
  .shell.is-light .customize {
    --ctl-text: rgba(28,28,30,0.96);
    --ctl-sub: rgba(60,60,67,0.68);
    --ctl-fill: rgba(120,120,128,0.14);
    --ctl-fill-2: rgba(120,120,128,0.10);
    --ctl-border: rgba(60,60,67,0.16);
    --ctl-surface: rgba(255,255,255,0.82);
    --ctl-active: rgba(10,132,255,0.14);
  }
  .appearance summary {
    list-style: none; cursor: pointer; padding: 11px 14px;
    border-radius: 12px; font-size: 15px; font-weight: 600;
    color: var(--ctl-text); background: var(--ctl-surface);
    border: .5px solid var(--ctl-border);
    -webkit-user-select: none; user-select: none;
    backdrop-filter: blur(20px) saturate(160%%);
    -webkit-backdrop-filter: blur(20px) saturate(160%%);
  }
  .appearance summary::-webkit-details-marker { display: none; }
  .appearance summary::after { content: "⌄"; float: right; font-size: 13px; color: var(--ctl-sub); }
  .appearance[open] summary::after { content: "⌃"; }
  .appearance-body {
    display: flex; flex-direction: column; gap: 12px;
    padding: 12px 2px 4px;
  }
  .ctl-group {
    display: flex; flex-direction: column; gap: 8px;
    min-height: 0;
  }
  .ctl-label {
    font-size: 12px; font-weight: 600;
    color: var(--ctl-sub);
    letter-spacing: -0.01em;
    padding: 0 2px;
  }
  .picker-row {
    display: flex; align-items: center; justify-content: space-between;
    gap: 10px; min-height: 18px;
  }
  .picker-row .ctl-label { padding: 0; }
  .picker-meta {
    font-size: 12px; color: var(--ctl-sub); font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  /* Fixed 5-col chip grid — never reflows when selection changes */
  .theme-picker {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 6px;
  }
  .theme-chip {
    appearance: none; border: .5px solid var(--ctl-border);
    border-radius: 12px; padding: 8px 4px 7px;
    min-height: 68px;
    background: var(--ctl-fill-2);
    color: var(--ctl-text);
    font: inherit; cursor: pointer;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 6px;
    transition: border-color .15s ease, background .15s ease, box-shadow .15s ease;
  }
  .theme-chip-swatch {
    width: 28px; height: 28px; border-radius: 8px; flex: 0 0 auto;
    border: .5px solid rgba(255,255,255,0.18);
    box-shadow: 0 1px 0 rgba(255,255,255,0.12) inset, 0 4px 10px rgba(0,0,0,0.18);
  }
  .shell.is-light .theme-chip-swatch {
    border-color: rgba(60,60,67,0.14);
    box-shadow: 0 1px 0 #fff inset, 0 3px 8px rgba(0,0,0,0.08);
  }
  .theme-chip-name {
    font-size: 10px; font-weight: 700; letter-spacing: -0.01em;
    color: var(--ctl-text); line-height: 1.1; text-align: center;
  }
  .theme-chip.is-active {
    border-color: rgba(10,132,255,0.55);
    background: var(--ctl-active);
    box-shadow: 0 0 0 1px rgba(10,132,255,0.22);
  }
  .theme-chip:active { opacity: .88; }
  .accent-row {
    display: flex; gap: 10px; align-items: center;
    min-height: 32px; padding: 2px 2px 0;
  }
  .accent-dot {
    appearance: none; border: 0; width: 28px; height: 28px; border-radius: 50%%;
    background: var(--dot, #0A84FF); cursor: pointer; padding: 0; flex: 0 0 auto;
    box-shadow: 0 0 0 1.5px var(--ctl-border), 0 1px 0 rgba(255,255,255,0.12) inset;
    transition: box-shadow .14s ease, transform .1s ease;
  }
  .accent-dot.is-active {
    box-shadow: 0 0 0 2px var(--ctl-surface), 0 0 0 4px #0A84FF;
    transform: scale(1.05);
  }
  .accent-dot:active { transform: scale(.95); }
  .seg {
    display: grid; grid-template-columns: repeat(4, minmax(0,1fr));
    gap: 2px; padding: 3px; border-radius: 11px;
    min-height: 38px;
    background: var(--ctl-fill-2); border: .5px solid var(--ctl-border);
  }
  .seg-item {
    appearance: none; border: 0; border-radius: 9px;
    min-height: 32px; padding: 6px 2px; font: inherit;
    font-size: 12px; font-weight: 650; color: var(--ctl-sub);
    background: transparent; cursor: pointer;
    transition: background .12s ease, color .12s ease;
  }
  .seg-item.is-active {
    color: var(--ctl-text); background: var(--ctl-fill);
    box-shadow: 0 1px 0 rgba(255,255,255,0.10) inset;
  }
  .seg-item:active { opacity: .85; }
  .toolbar {
    display: flex; gap: 6px; flex-wrap: wrap;
    min-height: 34px; padding: 0 1px;
  }
  .pill {
    appearance: none;
    font: inherit;
    font-size: 12px;
    font-weight: 650;
    letter-spacing: -0.01em;
    color: var(--ctl-text);
    background: var(--ctl-fill);
    border: .5px solid var(--ctl-border);
    border-radius: 999px;
    padding: 7px 12px;
    min-height: 32px;
    cursor: pointer;
    text-decoration: none;
  }
  .pill:active { opacity: 0.78; }
  .lab {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 6px;
  }
  .lab-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 4px;
    min-height: 40px;
    background: var(--ctl-surface);
    border: .5px solid var(--ctl-border);
    border-radius: 11px;
    padding: 6px 8px;
    font-size: 11px;
    color: var(--ctl-sub);
    font-weight: 650;
  }
  .lab-row .lab-val {
    color: var(--ctl-text);
    font-variant-numeric: tabular-nums;
    min-width: 2.6em;
    text-align: center;
    font-weight: 700;
  }
  .step {
    appearance: none; border: 0;
    width: 26px; height: 26px;
    display: flex; align-items: center; justify-content: center;
    border-radius: 8px;
    background: var(--ctl-fill);
    color: var(--ctl-text);
    text-decoration: none;
    font: inherit;
    font-size: 14px;
    font-weight: 700;
    line-height: 1;
    cursor: pointer;
  }
  .step:active { opacity: 0.7; transform: scale(.96); }
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
    border-radius: 20px;
    padding: 11px 13px 12px;
    box-shadow: 0 1px 0 var(--inset) inset, 0 10px 24px var(--drop);
  }
  .sheet-backdrop {
    position: fixed; inset: 0; z-index: 20; opacity: 0; pointer-events: none;
    background: rgba(0,0,0,.36); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
    transition: opacity .26s ease;
  }
  .detail-sheet {
    position: fixed; z-index: 21; left: 8px; right: 8px; bottom: 8px; height: 78%%;
    display: flex; flex-direction: column; padding: 10px 14px 14px;
    border-radius: 28px; border: .5px solid var(--shell-border);
    background:
      linear-gradient(160deg, var(--inset), transparent 40%%),
      var(--card);
    backdrop-filter: blur(54px) saturate(180%%); -webkit-backdrop-filter: blur(54px) saturate(180%%);
    box-shadow: 0 -16px 50px var(--drop), 0 1px 0 var(--inset) inset;
    transform: translateY(calc(100%% + 18px)); opacity: 0;
    transition: transform .36s cubic-bezier(.22,1,.36,1), opacity .24s ease;
  }
  body.sheet-open .sheet-backdrop[aria-hidden="false"] { opacity: 1; pointer-events: auto; }
  body.sheet-open .detail-sheet[aria-hidden="false"] { transform: translateY(0); opacity: 1; }
  .sheet-grabber { width: 38px; height: 5px; margin: 0 auto 10px; border-radius: 9px; background: var(--fill); }
  .sheet-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  .sheet-head span { font-size: 10px; color: var(--sub); font-weight: 700; letter-spacing: .08em; }
  .sheet-head h2 { margin: 3px 0 0; font-size: 22px; letter-spacing: -.045em; color: var(--text); }
  .sheet-close { border-radius: 50%%; font-size: 20px; background: var(--fill); color: var(--text); }
  .sheet-summary { display: grid; grid-template-columns: repeat(3,1fr); gap: 7px; margin: 14px 0 8px; }
  .sheet-summary div { padding: 10px; border-radius: 15px; background: var(--fill); border: .5px solid var(--hairline); }
  .sheet-summary span, .sheet-summary b { display: block; }
  .sheet-summary span { font-size: 10px; color: var(--sub); }
  .sheet-summary b { margin-top: 4px; font-size: 15px; font-variant-numeric: tabular-nums; color: var(--text); }
  .sheet-scroll { min-height: 0; overflow: auto; padding: 2px 1px 8px; overscroll-behavior: contain; }
  .sheet-scroll h3 { margin: 14px 4px 6px; font-size: 11px; color: var(--sub); letter-spacing: .05em; }
  .detail-row { display: flex; justify-content: space-between; gap: 12px; padding: 10px 11px; border-radius: 14px; background: var(--fill); border: .5px solid var(--hairline); margin-bottom: 6px; }
  .detail-row b, .detail-row small { display: block; }
  .detail-row b { font-size: 12px; color: var(--text); }
  .detail-row small { margin-top: 3px; color: var(--sub); font-size: 10px; }
  .detail-money { text-align: right; font-variant-numeric: tabular-nums; }
  .provider-usage-card { position:relative; cursor:pointer; padding-right:34px; }
  .provider-usage-card:focus-visible { outline:0; box-shadow:0 0 0 3px color-mix(in srgb,var(--blue) 40%%,transparent); }
  .usage-chevron { position:absolute; right:13px; top:50%%; transform:translateY(-50%%); color:var(--sub); font-size:24px; font-weight:300; }
  .usage-subtitle { margin:8px 2px 12px; color:var(--sub); font-size:11px; }
  .usage-window-row { display:grid; grid-template-columns:minmax(0,.72fr) minmax(0,1.28fr); gap:10px; margin-bottom:8px; padding:13px; border-radius:16px; background:var(--fill); border:.5px solid var(--hairline); }
  .usage-window-row span,.usage-window-row strong,.usage-window-row b { display:block; }
  .usage-window-row span { color:var(--sub); font-size:10px; }
  .usage-window-row strong { margin-top:5px; font-size:22px; font-variant-numeric:tabular-nums; }
  .usage-reset { text-align:right; }
  .usage-reset b { margin-top:5px; font-size:11px; line-height:1.45; font-variant-numeric:tabular-nums; }
  .detail-empty, .meaning-note { padding: 11px; border-radius: 14px; color: var(--sub); background: var(--fill-2); font-size: 11px; line-height: 1.45; }
  .token-dot { background: var(--chart-free); box-shadow: 0 0 0 3px color-mix(in srgb, var(--chart-free) 25%%, transparent); }
  .token-overview .ledger-status { padding-right: 28px; }
  .token-share-track, .token-row-track { height: 5px; overflow: hidden; border-radius: 99px; background: var(--track); }
  .token-share-track { margin-top: 11px; }
  .token-share-track span, .token-row-track span { display: block; height: 100%%; border-radius: inherit; background: linear-gradient(90deg,var(--chart-primary),var(--chart-secondary)); }
  .local-kpi strong { color: var(--chart-local); }
  .token-trend { margin-top:11px; padding:10px 11px 8px; border-radius:15px; background:rgba(120,120,128,.11); }
  .trend-head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:7px; color:var(--sub); font-size:9px; }
  .trend-head span { color:var(--text); font-weight:700; }
  .trend-bars { display:flex; align-items:flex-end; gap:2px; height:48px; }
  .trend-bars span { flex:1; min-width:2px; border-radius:3px 3px 1px 1px; background:linear-gradient(180deg,var(--chart-secondary),var(--chart-primary)); opacity:.88; transition:height .22s cubic-bezier(.22,1,.36,1),opacity .15s; }
  .trend-bars span:hover { opacity:1; }
  .compute-line-chart { margin-top:11px; padding:10px 11px 9px; border-radius:15px; background:linear-gradient(180deg,color-mix(in srgb,var(--chart-local) 14%%, transparent),var(--fill-2)); overflow:hidden; }
  .compute-line-chart svg { display:block; width:100%%; height:82px; overflow:visible; }
  .chart-grid { fill:none; stroke:var(--hairline); stroke-width:.7; vector-effect:non-scaling-stroke; }
  .compute-line { fill:none; stroke-width:2.3; stroke-linecap:round; stroke-linejoin:round; vector-effect:non-scaling-stroke; }
  .free-line { stroke:var(--chart-free); filter:drop-shadow(0 2px 4px color-mix(in srgb,var(--chart-free) 35%%, transparent)); }
  .local-line { stroke:var(--chart-local); filter:drop-shadow(0 2px 4px color-mix(in srgb,var(--chart-local) 35%%, transparent)); }
  .line-legend { display:flex; justify-content:space-between; gap:12px; margin-top:3px; font-size:9px; color:var(--sub); }
  .line-legend span::before { content:""; display:inline-block; width:7px; height:7px; margin-right:5px; border-radius:50%%; }
  .free-legend::before { background:var(--chart-free); }
  .local-legend::before { background:var(--chart-local); }
  .line-legend b { margin-left:4px; color:var(--text); font-variant-numeric:tabular-nums; }
  .source-line-chart { margin:10px 0 12px; padding:11px; border-radius:17px; background:rgba(120,120,128,.11); }
  .source-line-chart svg { display:block; width:100%%; height:110px; }
  .source-line { fill:none; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; vector-effect:non-scaling-stroke; }
  .claude-line { stroke:#D97757; }
  .codex-line { stroke:#10A37F; }
  .other-line { stroke:#BF5AF2; }
  .source-legends { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px; margin-top:7px; }
  .source-legend { display:grid; grid-template-columns:auto 1fr auto; align-items:baseline; gap:5px; padding:7px 8px; border-radius:11px; background:rgba(120,120,128,.13); font-size:9px; }
  .source-legend span::before { content:""; display:inline-block; width:7px; height:7px; margin-right:5px; border-radius:50%%; }
  .source-legend b { text-align:right; font-size:10px; font-variant-numeric:tabular-nums; }
  .source-legend small { color:var(--sub); }
  .claude-legend span::before { background:#D97757; }
  .codex-legend span::before { background:#10A37F; }
  .free-cloud-legend span::before { background:var(--chart-free); }
  .local-compute-legend span::before { background:var(--chart-local); }
  .other-legend span::before { background:#BF5AF2; }
  .source-legend:last-child { grid-column:1 / -1; }
  .window-tabs { display: grid; grid-template-columns: repeat(3,1fr); gap: 5px; margin: 13px 0 7px; padding: 4px; border-radius: 14px; background: var(--fill); }
  .window-tabs button { appearance: none; border: 0; border-radius: 10px; height: 32px; color: var(--sub); background: transparent; font: inherit; font-size: 11px; font-weight: 700; cursor: pointer; }
  .window-tabs button.is-active { color: var(--text); background: var(--card); box-shadow: 0 1px 4px var(--drop), 0 1px 0 var(--inset) inset; }
  .window-panel { display: none; }
  .window-panel.is-active { display: block; }
  .window-hero { display: flex; align-items: baseline; gap: 8px; padding: 13px; border-radius: 17px; background: linear-gradient(145deg,rgba(10,132,255,.24),rgba(100,210,255,.08)); }
  .window-hero span { color: rgba(235,235,245,.58); font-size: 10px; }
  .window-hero strong { margin-left: auto; font-size: 24px; letter-spacing: -.05em; font-variant-numeric: tabular-nums; }
  .window-hero small { color: rgba(235,235,245,.58); font-size: 10px; }
  .token-row { padding: 9px 11px; margin-bottom: 6px; border-radius: 14px; background: rgba(120,120,128,.13); }
  .token-row-head { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 6px; font-size: 11px; }
  .token-row-head span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .token-row-head b { white-space: nowrap; font-variant-numeric: tabular-nums; }
  .token-row-head small { color: rgba(235,235,245,.52); font-weight: 500; }
  .compute-overview {
    padding: 16px; border-radius: 24px; border: .5px solid rgba(255,255,255,.13);
    background: linear-gradient(145deg,rgba(48,209,88,.13),rgba(100,210,255,.05)),var(--card);
    box-shadow: 0 18px 38px rgba(0,0,0,.14),0 1px 0 rgba(255,255,255,.13) inset;
  }
  .compute-lens {
    overflow: hidden; border-radius: 28px; border: .5px solid rgba(255,255,255,.14);
    background: linear-gradient(155deg,rgba(48,209,88,.12),rgba(100,210,255,.04) 42%%,rgba(255,255,255,.035)),var(--card);
    box-shadow: 0 24px 48px rgba(0,0,0,.18),0 1px 0 rgba(255,255,255,.13) inset;
  }
  .compute-lens .compute-overview { border:0; border-radius:0; background:transparent; box-shadow:none; padding-bottom:13px; }
  .compute-lens .token-overview { border:0; border-radius:0; background:transparent; box-shadow:none; padding:16px; }
  .lens-divider { height:.5px; margin:0 16px; background:rgba(255,255,255,.12); }
  .lens-token-head { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:13px 16px 0; }
  .lens-token-head span,.lens-token-head strong { display:block; }
  .lens-token-head span { color:var(--sub); font-size:9px; font-weight:750; letter-spacing:.09em; }
  .lens-token-head strong { margin-top:2px; font-size:15px; letter-spacing:-.025em; }
  .lens-detail-link { appearance:none; border:0; border-radius:99px; padding:7px 10px; color:var(--chart-local); background:color-mix(in srgb,var(--chart-local) 14%%, transparent); font:inherit; font-size:10px; font-weight:700; cursor:pointer; }
  .compute-lens .kpi { padding:9px 10px; }
  .compute-lens .kpi strong { font-size:20px; }
  .window-kpi { appearance:none; border:0; color:inherit; text-align:left; font:inherit; cursor:pointer; }
  .window-kpi:hover { background:rgba(120,120,128,.24); }
  .window-kpi:focus-visible { box-shadow:0 0 0 3px rgba(10,132,255,.42); outline:0; }
  .compute-lens .token-kpis { grid-template-columns:repeat(3,minmax(0,1fr)); }
  .compute-lens .source-strip { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .compute-lens .source-chip { min-height:70px; }
  .other-metric { grid-column:1 / -1; min-height:58px !important; }
  .claude-metric b { color:#D97757; }
  .codex-metric b { color:#10A37F; }
  .free-metric b { color:var(--chart-free); }
  .local-metric b { color:var(--chart-local); }
  .ledger-actions { display:flex; gap:5px; }
  .ledger-actions button { appearance:none; border:0; border-radius:99px; padding:6px 9px; color:var(--sub); background:rgba(120,120,128,.18); font:inherit; font-size:9px; font-weight:700; cursor:pointer; }
  .ledger-actions button:hover { color:var(--text); background:rgba(120,120,128,.28); }
  .compute-dot { background: var(--chart-local); box-shadow: 0 0 0 3px color-mix(in srgb, var(--chart-local) 22%%, transparent); }
  .compute-overview .ledger-status { padding-right: 28px; }
  .compute-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .compute-stat { padding: 11px; border-radius: 15px; background: rgba(120,120,128,.14); }
  .compute-stat span,.compute-stat strong,.compute-stat small { display: block; }
  .compute-stat span,.compute-stat small { color: var(--sub); font-size: 10px; }
  .compute-stat strong { margin: 4px 0 2px; font-size: 20px; letter-spacing: -.045em; }
  .combined-stat { grid-column: 1/-1; display: grid; grid-template-columns: 1fr auto; align-items: center; }
  .combined-stat span,.combined-stat small { grid-column: 1; }
  .combined-stat strong { grid-column: 2; grid-row: 1/3; font-size: 24px; }
  .free-stat strong { color: #30D158; } .local-stat strong { color: #64D2FF; }
  .compute-ratio { display: flex; height: 7px; margin-top: 11px; overflow: hidden; border-radius: 99px; background: rgba(120,120,128,.2); }
  .compute-ratio span { height: 100%%; } .free-ratio { background: var(--chart-free); } .local-ratio { background: var(--chart-local); }
  .compute-purpose { display: flex; gap: 8px; align-items: baseline; margin-top: 10px; font-size: 10px; }
  .compute-purpose span { color: var(--sub); } .compute-purpose b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .compute-trust { display:flex; justify-content:space-between; gap:8px; margin-top:9px; font-size:10px; color:var(--sub); }
  .compute-trust b { color:var(--text); font-weight:650; }
  .coverage-callout { display:grid; grid-template-columns:1fr auto; align-items:baseline; gap:3px 10px; margin:10px 1px 2px; padding:11px 12px; border-radius:15px; background:rgba(48,209,88,.10); border:1px solid rgba(48,209,88,.18); }
  .coverage-callout span,.coverage-callout small { color:var(--sub); font-size:10px; }
  .coverage-callout strong { font-size:17px; font-variant-numeric:tabular-nums; }
  .coverage-callout small { grid-column:1 / -1; }
  .fixed-badge { color:var(--sub); font-size:10px; font-weight:700; letter-spacing:.02em; }
  .dashboard-section.is-fixed .move-controls { visibility:hidden; }
  .compute-summary div { position: relative; }
  .compute-summary small { display: block; margin-top: 3px; color: rgba(235,235,245,.52); font-size: 9px; }
  .key-card { margin-bottom: 7px; border-radius: 15px; background: rgba(120,120,128,.14); overflow: hidden; }
  .key-card summary { list-style: none; display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 11px; cursor: pointer; }
  .key-card summary::-webkit-details-marker { display: none; }
  .key-card summary span,.key-card summary b,.key-card summary small { display: block; }
  .key-card summary b { font-size: 12px; } .key-card summary small { margin-top: 3px; color: rgba(235,235,245,.52); font-size: 9px; }
  .key-card summary strong { font-size: 15px; font-variant-numeric: tabular-nums; }
  .key-card summary::after { content: "⌄"; color: rgba(235,235,245,.52); }
  .key-card[open] summary::after { content: "⌃"; }
  .key-body { padding: 0 11px 11px; border-top: .5px solid rgba(255,255,255,.08); }
  .key-sources { display: flex; flex-wrap: wrap; gap: 5px; padding-top: 9px; }
  .key-source { padding: 4px 7px; border-radius: 99px; color: rgba(235,235,245,.70); background: rgba(120,120,128,.22); font-size: 9px; }
  .key-body h4 { margin: 10px 0 5px; color: rgba(235,235,245,.52); font-size: 10px; }
  .key-body ul { list-style: none; margin: 0; padding: 0; }
  .key-body li { display: flex; justify-content: space-between; gap: 10px; padding: 6px 0; color: rgba(235,235,245,.72); font-size: 10px; border-bottom: .5px solid rgba(255,255,255,.06); }
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
    border: .5px solid var(--ctl-border, var(--hairline));
    border-radius: 12px;
    height: 40px;
    font: inherit;
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -0.01em;
    cursor: pointer;
    text-decoration: none;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--ctl-text, var(--text));
    background: var(--ctl-fill, var(--fill));
    transition: background 0.15s ease, transform 0.1s ease;
    -webkit-user-select: none;
    user-select: none;
  }
  .btn:active { transform: scale(0.98); }
  .btn.primary {
    background: #0A84FF;
    color: #ffffff !important;
    border-color: transparent;
    text-shadow: none;
  }
  /* Accent may recolor primary, but label must stay white for contrast */
  .customize .btn.primary { background: var(--blue, #0A84FF); color: #fff !important; }
  .shell.is-light .sheet-backdrop { background: rgba(40,28,16,.28); }
  .hint {
    grid-column: 1 / -1;
    text-align: center;
    font-size: 11px;
    color: var(--ctl-sub, var(--sub));
    margin-top: 2px;
    font-weight: 500;
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: 0.001ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.001ms !important;
    }
  }
  @media (prefers-reduced-transparency: reduce) {
    html, body { background: Canvas; }
    .shell, .ledger-overview, .card, .radar, .hero-loaders {
      backdrop-filter: none !important;
      -webkit-backdrop-filter: none !important;
      background: Canvas !important;
    }
  }
</style>
</head>
<body>
  <div class="shell%s" data-theme="%s">
    <div class="top">
      <div class="title">NexStatus<span>成本中心</span></div>
      <div class="top-actions">
        <button type="button" class="top-button" data-action="toggle-density" aria-label="切換顯示密度">%s</button>
        <button type="button" class="top-button" data-sheet-open="layout" aria-label="編輯排序">編輯</button>
      </div>
    </div>
    <div class="stamp">%s · %s · %s · 透%d%%</div>

    <div class="data">
      %s
    </div>

    <div class="customize">
      <details class="appearance">
        <summary>外觀與顯示</summary>
        <div class="appearance-body">
          <div class="ctl-group">
            <div class="ctl-label">主題</div>
            <div class="theme-picker" role="listbox" aria-label="主題">%s</div>
          </div>
          <div class="ctl-group">
            <div class="picker-row">
              <span class="ctl-label">強調色</span>
              <span class="picker-meta" data-accent-label>%s</span>
            </div>
            <div class="accent-row" role="listbox" aria-label="強調色">%s</div>
          </div>
          <div class="ctl-group">
            <div class="picker-row">
              <span class="ctl-label">材質</span>
              <span class="picker-meta" data-glass-label>%s</span>
            </div>
            <div class="seg" role="group" aria-label="玻璃材質">%s</div>
          </div>
          <div class="ctl-group">
            <div class="ctl-label">微調</div>
            <div class="lab">
              <div class="lab-row">
                <span>材質不透明度</span>
                <button type="button" class="step" data-action="opacity-down" aria-label="降低透明度">−</button>
                <span class="lab-val" data-lab="opacity">%d%%</span>
                <button type="button" class="step" data-action="opacity-up" aria-label="提高透明度">+</button>
              </div>
              <div class="lab-row">
                <span>模糊</span>
                <button type="button" class="step" data-action="blur-down" aria-label="降低模糊">−</button>
                <span class="lab-val" data-lab="blur">%d</span>
                <button type="button" class="step" data-action="blur-up" aria-label="提高模糊">+</button>
              </div>
              <div class="lab-row">
                <span>飽和</span>
                <button type="button" class="step" data-action="sat-down" aria-label="降低飽和度">−</button>
                <span class="lab-val" data-lab="sat">%d</span>
                <button type="button" class="step" data-action="sat-up" aria-label="提高飽和度">+</button>
              </div>
            </div>
          </div>
          <div class="toolbar">
            <button type="button" class="pill" data-action="cycle-chart">圖表：%s</button>
            <button type="button" class="pill" data-action="toggle-radar">雷達：%s</button>
            <button type="button" class="pill" data-action="reset-layout">重設排序</button>
          </div>
        </div>
      </details>
      <div class="actions">
        <button type="button" class="btn primary" data-action="refresh">重新整理</button>
        <button type="button" class="btn" data-action="close">關閉</button>
        <div class="hint">設定記住在本機 · 控制列保持高對比可讀</div>
      </div>
    </div>
  </div>
  %s
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
    var suppressSortClick = false;
    document.addEventListener("click", function (e) {
      var actionBtn = e.target.closest && e.target.closest("[data-action]");
      if (actionBtn && actionBtn.getAttribute("data-action")) {
        e.preventDefault();
        e.stopPropagation();
        sendAction(actionBtn.getAttribute("data-action"));
        return;
      }
      if (e.target.closest && e.target.closest("[data-sort-grip]")) {
        e.preventDefault(); e.stopPropagation(); return;
      }
      var opener = e.target.closest && e.target.closest("[data-sheet-open]");
      var closer = e.target.closest && e.target.closest("[data-sheet-close]");
      if (opener) {
        if (suppressSortClick) {
          e.preventDefault(); e.stopPropagation(); return;
        }
        e.preventDefault();
        var sheetName = opener.getAttribute("data-sheet-open");
        var sheet = document.getElementById(sheetName + "-sheet");
        if (!sheet) return;
        document.querySelectorAll(".detail-sheet").forEach(function (item) { item.setAttribute("aria-hidden", "true"); });
        document.querySelectorAll(".sheet-backdrop").forEach(function (item) { item.setAttribute("aria-hidden", "true"); });
        document.body.classList.add("sheet-open");
        sheet.setAttribute("aria-hidden", "false");
        document.querySelector('[data-sheet-close="' + sheetName + '"].sheet-backdrop').setAttribute("aria-hidden", "false");
        var requestedWindow = opener.getAttribute("data-window-target");
        if (requestedWindow) {
          document.querySelectorAll("[data-window]").forEach(function (button) {
            button.classList.toggle("is-active", button.getAttribute("data-window") === requestedWindow);
          });
          document.querySelectorAll("[data-window-panel]").forEach(function (view) {
            view.classList.toggle("is-active", view.getAttribute("data-window-panel") === requestedWindow);
          });
        }
        return;
      }
      if (closer) {
        e.preventDefault();
        document.body.classList.remove("sheet-open");
        document.querySelectorAll(".detail-sheet,.sheet-backdrop").forEach(function (item) { item.setAttribute("aria-hidden", "true"); });
        return;
      }
      var windowButton = e.target.closest && e.target.closest("[data-window]");
      if (windowButton) {
        e.preventDefault();
        var selected = windowButton.getAttribute("data-window");
        document.querySelectorAll("[data-window]").forEach(function (button) {
          button.classList.toggle("is-active", button === windowButton);
        });
        document.querySelectorAll("[data-window-panel]").forEach(function (view) {
          view.classList.toggle("is-active", view.getAttribute("data-window-panel") === selected);
        });
        return;
      }
      var t = e.target;
      while (t && !(t.getAttribute && t.getAttribute("data-action"))) {
        t = t.parentElement;
      }
      if (!t) return;
      e.preventDefault();
      e.stopPropagation();
      sendAction(t.getAttribute("data-action"));
    }, true);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && document.body.classList.contains("sheet-open")) {
        document.body.classList.remove("sheet-open");
        document.querySelectorAll(".detail-sheet,.sheet-backdrop").forEach(function (item) { item.setAttribute("aria-hidden", "true"); });
      }
      if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-sheet-open]")) {
        e.preventDefault(); e.target.click();
      }
    });
    /* ---- Sort sheet only: large rows, ↑↓ or ☰ drag ---- */
    (function setupSortSheet() {
      var active = null, moved = false, startY = 0, offsetY = 0;
      var list = null, placeholder = null, lastKey = null;

      function movableRows(parent) {
        return Array.from(parent.children).filter(function (n) {
          return n.classList && n.classList.contains("sort-row") && !n.classList.contains("is-fixed") && n !== placeholder;
        });
      }

      function commitList(parent) {
        if (!parent) return;
        var group = parent.getAttribute("data-sort-list");
        if (!group) return;
        var ids = Array.from(parent.querySelectorAll(".sort-row"))
          .map(function (n) { return n.getAttribute("data-sort-id"); })
          .filter(Boolean);
        if (group === "sections") sendAction("order-soft:" + ids.join(","));
        else sendAction("tiles-soft:" + group + ":" + ids.join(","));
        suppressSortClick = true;
        setTimeout(function () { suppressSortClick = false; }, 280);
      }

      function placeAt(clientY) {
        if (!active || !placeholder || !list) return;
        var rows = movableRows(list);
        var insertBefore = null;
        for (var i = 0; i < rows.length; i++) {
          if (rows[i] === active) continue;
          var r = rows[i].getBoundingClientRect();
          if (clientY < r.top + r.height / 2) { insertBefore = rows[i]; break; }
        }
        // Keep fixed rows (e.g. compute) pinned at top
        var fixed = list.querySelector(".sort-row.is-fixed");
        if (!insertBefore) {
          list.appendChild(placeholder);
        } else if (fixed && insertBefore === fixed) {
          list.insertBefore(placeholder, fixed.nextSibling);
        } else {
          list.insertBefore(placeholder, insertBefore);
        }
        var key = insertBefore ? insertBefore.getAttribute("data-sort-id") : "end";
        if (key === lastKey) return;
        lastKey = key;
      }

      function beginDrag(row, e) {
        var rect = row.getBoundingClientRect();
        list = row.parentNode;
        active = row;
        moved = true;
        lastKey = null;
        offsetY = e.clientY - rect.top;
        placeholder = document.createElement("div");
        placeholder.className = "sort-placeholder";
        placeholder.style.height = rect.height + "px";
        list.insertBefore(placeholder, row);
        row.classList.add("is-dragging");
        row.style.position = "fixed";
        row.style.left = rect.left + "px";
        row.style.top = rect.top + "px";
        row.style.width = rect.width + "px";
        row.style.zIndex = "120";
        row.style.pointerEvents = "none";
        document.body.appendChild(row);
      }

      function onMove(e) {
        if (!active) return;
        if (!moved) {
          if (Math.abs(e.clientY - startY) < 5) return;
          beginDrag(active, e);
        }
        e.preventDefault();
        active.style.top = (e.clientY - offsetY) + "px";
        placeAt(e.clientY);
      }

      function onUp(e) {
        if (!active) return;
        document.removeEventListener("pointermove", onMove, true);
        document.removeEventListener("pointerup", onUp, true);
        document.removeEventListener("pointercancel", onUp, true);
        try { e.target && e.target.releasePointerCapture && e.target.releasePointerCapture(e.pointerId); } catch (err) {}
        if (moved && placeholder && list) {
          list.insertBefore(active, placeholder);
          placeholder.remove();
          active.classList.remove("is-dragging");
          active.style.position = active.style.left = active.style.top = active.style.width = active.style.zIndex = active.style.pointerEvents = "";
          commitList(list);
        } else if (active) {
          active.classList.remove("is-dragging");
        }
        active = null; moved = false; list = null; placeholder = null; lastKey = null;
      }

      document.querySelectorAll("[data-sort-grip]").forEach(function (grip) {
        grip.addEventListener("pointerdown", function (e) {
          if (e.button !== undefined && e.button !== 0) return;
          var row = grip.closest(".sort-row");
          if (!row || row.classList.contains("is-fixed")) return;
          e.preventDefault(); e.stopPropagation();
          active = row; moved = false; startY = e.clientY;
          try { grip.setPointerCapture(e.pointerId); } catch (err) {}
          document.addEventListener("pointermove", onMove, true);
          document.addEventListener("pointerup", onUp, true);
          document.addEventListener("pointercancel", onUp, true);
        });
        grip.addEventListener("dragstart", function (e) { e.preventDefault(); });
      });
    })();
  </script>
</body>
</html>]],
    th.color_scheme, bgCss, cardCss, th.border, th.muted, th.text, th.sub, th.track, accent, th.glow1, th.glow2,
    th.fill or "rgba(120,120,128,0.16)",
    th.fill2 or "rgba(120,120,128,0.10)",
    th.hairline or th.border,
    th.inset or "rgba(255,255,255,0.10)",
    th.drop or "rgba(0,0,0,0.28)",
    th.shellBorder or th.border,
    blur, sat,
    chrome.radius or 28,
    chrome.chart_free, chrome.chart_local, chrome.chart_primary, chrome.chart_secondary,
    chrome.chart_warn, chrome.chart_ok,
    auroraCSS,
    ((prefs.density == "compact") and " is-compact" or "") ..
      (isLight and " is-light" or " is-dark"),
    prefs.theme,
    prefs.density == "compact" and "展開" or "精簡",
    esc(updated), esc(chartLabel), esc(themeLabel), math.floor(op * 100 + 0.5),
    -- data zone
    orderedSections,
    -- customize zone
    themeCards,
    esc(aLabel),
    accentDots,
    esc(gLabel),
    glassSeg,
    math.floor(op * 100 + 0.5), blur, sat,
    esc(chartLabel), prefs.radar and "開" or "關",
    detailSheets
  )
end


local function positionPanel()
  if not panel then return end
  local screen = hs.screen.mainScreen()
  local sf = screen:fullFrame()
  -- Top-right under menu bar, clamp height to visible frame
  local maxH = math.min(PANEL_H, math.floor(sf.h * 0.88))
  local x = sf.x + sf.w - PANEL_W - 14
  local y = sf.y + 28
  panel:frame(hs.geometry.rect(x, y, PANEL_W, maxH))
end

local panelFadeTimer = nil

local function hidePanel()
  if not panel then return end
  if panelFadeTimer then
    panelFadeTimer:stop()
    panelFadeTimer = nil
  end
  local steps, i = 6, 0
  if panel.alpha then
    panelFadeTimer = hs.timer.doEvery(0.016, function()
      i = i + 1
      local a = 1 - (i / steps)
      pcall(function() panel:alpha(math.max(0, a)) end)
      if i >= steps then
        if panelFadeTimer then panelFadeTimer:stop(); panelFadeTimer = nil end
        panel:hide()
        pcall(function() panel:alpha(1) end)
      end
    end)
  else
    panel:hide()
  end
end

-- MenuBar open-click is outside the panel; ignore outside-dismiss briefly after show.
local suppressOutsideUntil = 0

redrawPanel = function()
  if not panel then return end
  local visible = false
  pcall(function()
    local w = panel:hswindow()
    visible = w and w:isVisible() or false
  end)
  panel:html(buildHTML(readSnapshot()))
  if visible then
    pcall(function() panel:alpha(1) end)
  end
end

local function handleAction(action)
  if type(action) ~= "string" then return end
  action = action:gsub("^/*", ""):gsub("[?#|].*$", "")

  local moveId, moveDirection = action:match("^move:([a-z_]+):([a-z]+)$")
  if moveDirection ~= "up" and moveDirection ~= "down" then moveId, moveDirection = nil, nil end
  local orderPayload = action:match("^order:([a-z_,]+)$")
  local softTile = false
  local tileGroup, tilePayload = action:match("^tiles%-soft:([a-z_]+):([a-z0-9_,]+)$")
  if tileGroup then
    softTile = true
  else
    tileGroup, tilePayload = action:match("^tiles:([a-z_]+):([a-z0-9_,]+)$")
  end
  local softOrder = false
  if not orderPayload then
    orderPayload = action:match("^order%-soft:([a-z_,]+)$")
    if orderPayload then softOrder = true end
  end

  if tileGroup and tilePayload then
    local allowed = TILE_ORDER_DEFAULTS[tileGroup]
    local prefsKey = tilePrefsKey(tileGroup)
    if allowed and prefsKey then
      local proposed = {}
      for id in tilePayload:gmatch("[a-z0-9_]+") do table.insert(proposed, id) end
      local normalized = normalizedTileOrder(tileGroup, proposed)
      if #proposed == #allowed then
        local valid = true
        for index, id in ipairs(normalized) do
          if id ~= proposed[index] then valid = false; break end
        end
        if valid then
          prefs[prefsKey] = normalized
          savePrefs()
          if not softTile then redrawPanel() end
        end
      end
    end
    return
  elseif orderPayload then
    local proposed = {}
    for id in orderPayload:gmatch("[a-z_]+") do table.insert(proposed, id) end
    local normalized = normalizedSectionOrder(proposed)
    -- Reject partial, duplicate or unknown payloads instead of silently
    -- granting a variable bridge command broader meaning.
    if #proposed == #SECTION_ORDER then
      local valid = true
      for index, id in ipairs(normalized) do
        if id ~= proposed[index] then valid = false; break end
      end
      if valid then
        prefs.section_order = normalized
        savePrefs()
        if not softOrder then redrawPanel() end
      end
    end
    return
  elseif moveId then
    local order = normalizedSectionOrder(prefs.section_order)
    if moveId == "compute" then return end
    for index, id in ipairs(order) do
      if id == moveId then
        local other = moveDirection == "up" and index - 1 or index + 1
        if other >= 2 and other <= #order then order[index], order[other] = order[other], order[index] end
        break
      end
    end
    prefs.section_order = order
    savePrefs()
    redrawPanel()
    return
  end

  if action == "refresh" then
    refreshSnapshot(true)
  elseif action == "cycle-chart" then
    prefs.chart = cycleList(CHART_ORDER, prefs.chart)
    savePrefs()
    redrawPanel()
  elseif action == "cycle-theme" then
    local prevScheme = resolvedTheme().color_scheme
    prefs.theme = cycleList(THEME_ORDER, prefs.theme)
    applyThemeMaterial(prefs.theme)
    savePrefs()
    -- Full redraw only when light/dark flips — avoids control-strip jump.
    softChromeOrRedraw(prevScheme ~= resolvedTheme().color_scheme)
  elseif action:match("^theme:[a-z]+$") then
    local tid = action:match("^theme:([a-z]+)$")
    if THEMES[tid] then
      local prevScheme = resolvedTheme().color_scheme
      prefs.theme = tid
      applyThemeMaterial(tid)
      savePrefs()
      softChromeOrRedraw(prevScheme ~= resolvedTheme().color_scheme)
    end
  elseif action:match("^accent:[a-z]+$") then
    local aid = action:match("^accent:([a-z]+)$")
    if aid == "theme" or ACCENTS[aid] then
      prefs.accent = aid
      savePrefs()
      -- Accent never needs full reflow — soft recolor only.
      softChromeOrRedraw(false)
    end
  elseif action:match("^glass:[a-z]+$") then
    local gid = action:match("^glass:([a-z]+)$")
    if GLASS_PRESETS[gid] then
      applyGlassPreset(gid)
      savePrefs()
      softChromeOrRedraw()
    end
  elseif action == "cycle-glass" then
    local cur = prefs.glass_preset
    if cur == "custom" then cur = "crystal" end
    applyGlassPreset(cycleList(GLASS_PRESET_ORDER, cur))
    savePrefs()
    softChromeOrRedraw()
  elseif action == "toggle-radar" then
    prefs.radar = not prefs.radar
    savePrefs()
    redrawPanel()
  elseif action == "toggle-density" then
    prefs.density = prefs.density == "compact" and "comfortable" or "compact"
    savePrefs()
    redrawPanel()
  elseif action == "layout-done" then
    -- Apply soft-saved order to the main dashboard and close the sheet.
    redrawPanel()
  elseif action == "reset-layout" then
    prefs.section_order = normalizedSectionOrder(SECTION_ORDER)
    prefs.token_kpi_order = normalizedTileOrder("token_kpis", TILE_ORDER_DEFAULTS.token_kpis)
    prefs.token_source_order = normalizedTileOrder("token_sources", TILE_ORDER_DEFAULTS.token_sources)
    prefs.provider_order = normalizedTileOrder("providers", TILE_ORDER_DEFAULTS.providers)
    prefs.edit_layout = false
    savePrefs()
    redrawPanel()
  elseif action == "opacity-up" then
    prefs.opacity = math.floor(clamp((prefs.opacity or 0.72) + 0.10, 0.18, 0.98) * 100 + 0.5) / 100
    markGlassCustom()
    savePrefs()
    softChromeOrRedraw()
  elseif action == "opacity-down" then
    prefs.opacity = math.floor(clamp((prefs.opacity or 0.72) - 0.10, 0.18, 0.98) * 100 + 0.5) / 100
    markGlassCustom()
    savePrefs()
    softChromeOrRedraw()
  elseif action == "blur-up" then
    prefs.blur = clamp((prefs.blur or 48) + 6, 8, 80)
    markGlassCustom()
    savePrefs()
    softChromeOrRedraw()
  elseif action == "blur-down" then
    prefs.blur = clamp((prefs.blur or 48) - 6, 8, 80)
    markGlassCustom()
    savePrefs()
    softChromeOrRedraw()
  elseif action == "sat-up" then
    prefs.saturate = clamp((prefs.saturate or 190) + 15, 80, 240)
    markGlassCustom()
    savePrefs()
    softChromeOrRedraw()
  elseif action == "sat-down" then
    prefs.saturate = clamp((prefs.saturate or 190) - 15, 80, 240)
    markGlassCustom()
    savePrefs()
    softChromeOrRedraw()
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
  if panelFadeTimer then
    panelFadeTimer:stop()
    panelFadeTimer = nil
  end
  panel:html(html)
  positionPanel()
  -- Soft open: avoid hard pop-in under the MenuBar.
  pcall(function() panel:alpha(0) end)
  panel:show()
  panel:bringToFront(true)
  if panel.alpha then
    local steps, i = 7, 0
    panelFadeTimer = hs.timer.doEvery(0.016, function()
      i = i + 1
      local a = i / steps
      pcall(function() panel:alpha(math.min(1, a)) end)
      if i >= steps then
        if panelFadeTimer then panelFadeTimer:stop(); panelFadeTimer = nil end
        pcall(function() panel:alpha(1) end)
      end
    end)
  else
    pcall(function() panel:alpha(1) end)
  end
  -- Grace period: MenuBar click is outside the panel frame; without this,
  -- the outside-dismiss eventtap closes the dashboard on the same click.
  suppressOutsideUntil = hs.timer.secondsSinceEpoch() + 0.65
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

function M.show()
  showPanel()
end

function M.hide()
  hidePanel()
end

-- Public: open control panel (for debugging / scripts)
function M.openPanel()
  showPanel()
end


local function applyMenubarIcon()
  if not item then return end
  -- Keep the item narrow enough to survive crowded/notched menu bars. The
  -- title already carries C/G/H identity, so a separate 18px icon is redundant.
  pcall(function() item:setIcon(nil) end)
end

local function ensureMenubarItem()
  -- Tahoe / crowded MenuBar: dead hs.menubar refs leave no visible item while
  -- the module still thinks it is running. Always recreate when missing.
  if item then
    local ok = pcall(function()
      item:setTitle(item:title() or " NS ")
    end)
    if ok then
      applyMenubarIcon()
      return true
    end
    pcall(function() item:delete() end)
    item = nil
  end
  -- Stable autosave identity prevents Tahoe from restoring a recreated item
  -- beyond the right screen edge after reload/remove-return cycles.
  item = hs.menubar.new(true, "NexStatusUsage")
  if not item then
    hs.printf("[nexstatus] failed to create menubar item")
    return false
  end
  _G.NexStatusMenuBar = item
  pcall(function() item:setMenu(nil) end)
  item:setClickCallback(function()
    hs.printf("[nexstatus] menubar clicked → toggle dashboard")
    togglePanel()
  end)
  applyMenubarIcon()
  -- Short placeholder — long titles get crushed off-screen on crowded bars
  item:setTitle(" NS ")
  item:setTooltip("NexStatus — loading…")
  return true
end

function M.refreshTitleOnly()
  if not ensureMenubarItem() then return end
  local s = readSnapshot() or {}
  local host = s.host or {}
  local cl = s.claude or {}
  local cx = s.codex or {}
  local go = s.opencode_go or {}
  local gk = s.grok or {}

  -- Main bar: C=Claude · G=Code/Codex · K=Grok · A=Antigravity
  local function chip(letter, ok, val)
    if not ok or val == nil then
      return letter .. "—%"
    end
    return string.format("%s%d%%", letter, tonumber(val) or 0)
  end

  local ag = s.antigravity or {}
  local parts = {
    chip("C", cl.ok, cl.five_hour_pct),
    chip("G", cx.ok, cx.five_hour_pct),
    chip("K", gk.ok, gk.used_pct),
  }
  if ag.ok then
    table.insert(parts, chip("A", true, ag.used_pct or ag.session_used_pct))
  end

  -- Optional memory chip when swap is active or RAM is tight
  local mem = tonumber(host.mem_pct)
  local swap = tonumber(host.swap_mb) or 0
  local showMem = (swap >= 64) or (mem ~= nil and mem >= 80)
  if showMem and mem ~= nil then
    table.insert(parts, string.format("M%d%%", mem))
  end

  -- Compact title: long "C88% G100% K19% A3% M29%" is often clipped/invisible
  -- on crowded Tahoe MenuBars. Keep NS + short numbers; full detail in tooltip.
  local function short(ok, val)
    if not ok or val == nil then return "—" end
    return tostring(tonumber(val) or 0)
  end
  local body = string.format(
    "C%s G%s K%s",
    short(cl.ok, cl.five_hour_pct),
    short(cx.ok, cx.five_hour_pct),
    short(gk.ok, gk.used_pct)
  )
  if ag.ok then
    body = body .. " A" .. short(true, ag.used_pct or ag.session_used_pct)
  end
  if showMem and mem ~= nil then
    body = body .. " M" .. tostring(mem)
  end
  local pr = pressureFromSnapshot(s)
  -- MenuBar: C=Claude 5h · G=Codex 5h · H=host pressure index (CPU+MEM+vm pressure).
  -- H is hardware load — not the AI quota weather score shown inside the panel radar.
  local function menuPct(ok, value)
    if not ok or value == nil then return "—" end
    return tostring(math.floor((tonumber(value) or 0) + .5)) .. "%"
  end
  local hostLoad = tonumber(host.pressure_pct)
  if hostLoad == nil then
    -- Backward compatible with older snapshots that only had mem/cpu.
    local cpu = tonumber(host.cpu_pct) or 0
    local memV = tonumber(host.mem_pct) or 0
    hostLoad = math.floor(0.55 * memV + 0.45 * cpu + 0.5)
  end
  hostLoad = math.max(0, math.min(100, math.floor(hostLoad + 0.5)))
  local hostLabel = (hostLoad >= 80 and "H!" or "H") .. tostring(hostLoad) .. "%"
  local title = string.format(
    "C%sG%s%s",
    menuPct(cl.ok, cl.five_hour_pct),
    menuPct(cx.ok, cx.five_hour_pct),
    hostLabel
  )
  local tip = string.format(
    "NexStatus\nH = 電腦壓力 %d%% · %s · CPU %s · MEM %s · Swap %.0f MB\nAI 額度雷達 %d · %s\nC = Claude 5h %s\nG = Codex 5h %s\nK = Grok %s\nA = Antigravity %s (%s)\nOpenCode Go %s\n點一下開啟儀表板",
    hostLoad,
    tostring(host.pressure or "—"):gsub(" 🟢", ""):gsub(" 🟡", ""):gsub(" 🔴", ""),
    pctText(host.cpu_pct),
    pctText(mem),
    swap,
    pr.score,
    pr.weather,
    pctText(cl.five_hour_pct),
    pctText(cx.five_hour_pct),
    pctText(gk.used_pct),
    pctText(ag.used_pct or ag.session_used_pct),
    tostring(ag.plan or "—"),
    pctText(go.used_pct)
  )

  applyMenubarIcon()
  pcall(function()
    item:setTitle(title)
    item:setTooltip(tip)
  end)
end

function M.refresh()
  if not ensureMenubarItem() then return end
  refreshSnapshot(false)
  -- Paint the current snapshot immediately; the async collector repaints only
  -- after a successful atomic refresh.
  M.refreshTitleOnly()
  -- Live-update open panel
  if panel and panel:hswindow() and panel:hswindow():isVisible() then
    panel:html(buildHTML(readSnapshot()))
  end
end

function M.start()
  -- Hard reset: stop timers first so a reloaded instance cannot race-create a
  -- second MenuBar chip (orphan timers from a previous module chunk).
  if timer then pcall(function() timer:stop() end); timer = nil end
  if M._watch then pcall(function() M._watch:stop() end); M._watch = nil end
  if M._tap then pcall(function() M._tap:stop() end); M._tap = nil end
  if panelFadeTimer then pcall(function() panelFadeTimer:stop() end); panelFadeTimer = nil end
  if collectorWatchdog then pcall(function() collectorWatchdog:stop() end); collectorWatchdog = nil end
  if collectorTask then
    pcall(function() if collectorTask:isRunning() then collectorTask:terminate() end end)
    collectorTask = nil
  end
  refreshQueued = false

  if item then
    pcall(function() item:delete() end)
    item = nil
  end
  if _G.NexStatusMenuBar then
    pcall(function() _G.NexStatusMenuBar:delete() end)
    _G.NexStatusMenuBar = nil
  end
  if panel then
    pcall(function() panel:delete() end)
    panel = nil
  end

  if not ensureMenubarItem() then
    return
  end

  -- Warm snapshot so first open is instant
  pcall(function() refreshSnapshot(false) end)
  M.refreshTitleOnly()
  timer = hs.timer.doEvery(15, function()
    M.refresh()
  end)

  -- Watchdog: if MenuBar item disappears, recreate (every 30s)
  M._watch = hs.timer.doEvery(30, function()
    if not ensureMenubarItem() then return end
    -- Title is "C..% G..% H..%" — empty/whitespace only means paint failed.
    local t = nil
    pcall(function() t = item:title() end)
    if type(t) ~= "string" or t:match("%S") == nil then
      M.refreshTitleOnly()
    end
  end)

  -- Click outside panel to dismiss — but never on the open-click itself
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

  hs.printf("[nexstatus] NexStatus ready — look for MenuBar title starting with NS (root=%s)", ROOT)
  hs.alert.show("NexStatus 已上線：找 MenuBar「NS C…%」", 2.2)
end

function M.stop()
  if timer then pcall(function() timer:stop() end); timer = nil end
  refreshQueued = false
  if panelFadeTimer then pcall(function() panelFadeTimer:stop() end); panelFadeTimer = nil end
  if collectorWatchdog then pcall(function() collectorWatchdog:stop() end); collectorWatchdog = nil end
  if collectorTask then
    pcall(function()
      if collectorTask:isRunning() then collectorTask:terminate() end
    end)
    collectorTask = nil
  end
  if M._watch then pcall(function() M._watch:stop() end); M._watch = nil end
  if M._tap then pcall(function() M._tap:stop() end); M._tap = nil end
  if panel then
    pcall(function() panel:delete() end)
    panel = nil
  end
  if item then
    pcall(function() item:delete() end)
    item = nil
  end
  if _G.NexStatusMenuBar then
    pcall(function() _G.NexStatusMenuBar:delete() end)
    _G.NexStatusMenuBar = nil
  end
  hs.printf("[nexstatus] NexStatus stopped")
end

function M.restart()
  M.stop()
  M.start()
end

return M
