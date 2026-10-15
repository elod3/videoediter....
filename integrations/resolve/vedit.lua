--[[
vedit ⇄ DaVinci Resolve

În Resolve: Workspace > Scripts > vedit. Merge și în versiunea gratuită (Lua e inclus în Resolve,
nu trebuie Python instalat). Vorbește cu vedit-server prin curl, care e deja pe macOS și Linux.

  Ia din vedit        — aduce montajul proiectului ales ca timeline nou („vedit · <proiect>”),
                        cu fișierele originale legate direct de pe disc.
  Trimite în vedit    — exportă timeline-ul curent ca FCPXML și îl aplică în vedit. Efectele, încadrarea,
                        subtitrările și graficele din vedit rămân; tăieturile, ordinea, viteza și B-roll-ul
                        vin din Resolve. Pasul se poate anula din site („Anulează”).

Setările (adresa serverului, tokenul) se țin minte în ~/.vedit-resolve.
Instalare: `make resolve-install` din repo (copiază scriptul în folderul de scripturi al Resolve).
]]

local HOME = os.getenv("HOME") or os.getenv("USERPROFILE") or "."
local CONF = HOME .. "/.vedit-resolve"
local TMP = (os.getenv("TMPDIR") or "/tmp/"):gsub("/?$", "/")

local function read_conf()
  local c = { server = "http://127.0.0.1:8000", token = "" }
  local f = io.open(CONF, "r")
  if f then
    for line in f:lines() do
      local k, v = line:match("^(%w+)=(.*)$")
      if k then c[k] = v end
    end
    f:close()
  end
  return c
end

local function write_conf(c)
  local f = io.open(CONF, "w")
  if f then
    f:write("server=" .. c.server .. "\n", "token=" .. c.token .. "\n", "project=" .. (c.project or "") .. "\n")
    f:close()
  end
end

-- argumentele merg între ghilimele simple: nimic din ce scrie utilizatorul nu ajunge la shell ca și cod
local function q(s) return "'" .. tostring(s):gsub("'", "'\\''") .. "'" end

local function curl(conf, args)
  local auth = conf.token ~= "" and (" -H " .. q("Authorization: Bearer " .. conf.token)) or ""
  local cmd = "curl -sS --max-time 120 -w '\\n%{http_code}'" .. auth .. " " .. args .. " 2>&1"
  local p = io.popen(cmd)
  local out = p:read("*a")
  p:close()
  local body, code = out:match("^(.*)\n(%d%d%d)%s*$")
  if not code then return nil, "nu răspunde serverul vedit la " .. conf.server .. " (" .. out .. ")" end
  code = tonumber(code)
  if code >= 400 then
    return nil, (body:match('"detail"%s*:%s*"(.-)"') or body) .. " [" .. code .. "]"
  end
  return body
end

local function projects(conf)
  local body, err = curl(conf, q(conf.server .. "/api/projects"))
  if not body then return nil, err end
  local list = {}
  for n in body:gmatch('"name"%s*:%s*"([%w_%-]+)"') do list[#list + 1] = n end
  return list
end

local resolve = resolve or Resolve()
local function current()
  local pm = resolve:GetProjectManager()
  local proj = pm and pm:GetCurrentProject()
  if not proj then return nil, "Deschide un proiect în Resolve întâi." end
  return proj
end

local function pull(conf, name)
  local proj, err = current()
  if not proj then return false, err end
  local path = TMP .. "vedit-" .. name .. ".fcpxml"
  local _, e = curl(conf, "-o " .. q(path) .. " " .. q(conf.server .. "/api/projects/" .. name .. "/resolve.fcpxml"))
  if e then return false, e end
  local mp = proj:GetMediaPool()
  local tlname = "vedit · " .. name .. " · " .. os.date("%H%M")
  local tl = mp:ImportTimelineFromFile(path, { timelineName = tlname, importSourceClips = true })
  if not tl then return false, "Resolve n-a putut importa FCPXML-ul (" .. path .. ")" end
  proj:SetCurrentTimeline(tl)
  return true, "Timeline-ul „" .. tlname .. "” e deschis. Când termini: Trimite în vedit."
end

local function push(conf, name)
  local proj, err = current()
  if not proj then return false, err end
  local tl = proj:GetCurrentTimeline()
  if not tl then return false, "Niciun timeline deschis." end
  local path = TMP .. "vedit-out-" .. name .. ".fcpxml"
  local fmt = resolve.EXPORT_FCPXML_1_10 or resolve.EXPORT_FCPXML_1_9 or resolve.EXPORT_FCPXML_1_8
  if not tl:Export(path, fmt, resolve.EXPORT_NONE) then return false, "Exportul FCPXML din Resolve a eșuat." end
  local body, e = curl(conf, "-X POST -H 'Content-Type: application/xml' --data-binary @" .. q(path) .. " "
    .. q(conf.server .. "/api/projects/" .. name .. "/resolve/import"))
  if not body then return false, e end
  return true, "Trimis în vedit: " .. (body:match('"note"%s*:%s*"(.-)"') or "gata")
end

-- proiectul vedit din numele timeline-ului curent („vedit · nume · 1432”)
local function guess(conf)
  local proj = current()
  local tl = proj and proj:GetCurrentTimeline()
  local n = tl and tl:GetName():match("^vedit · ([%w_%-]+)")
  return n or conf.project or ""
end

-------------------------------------------------------------------- fereastra
local conf = read_conf()
local ui = fu.UIManager
local disp = bmd.UIDispatcher(ui)
local win = disp:AddWindow({
  ID = "vedit", WindowTitle = "vedit ⇄ Resolve", Geometry = { 200, 200, 460, 250 },
  ui:VGroup{
    ui:HGroup{ Weight = 0, ui:Label{ Text = "Server", MinimumSize = { 70, 0 }, Weight = 0 }, ui:LineEdit{ ID = "server", Text = conf.server } },
    ui:HGroup{ Weight = 0, ui:Label{ Text = "Token", MinimumSize = { 70, 0 }, Weight = 0 }, ui:LineEdit{ ID = "token", Text = conf.token, PlaceholderText = "doar dacă serverul cere VEDIT_API_TOKEN", EchoMode = "Password" } },
    ui:HGroup{ Weight = 0, ui:Label{ Text = "Proiect", MinimumSize = { 70, 0 }, Weight = 0 }, ui:ComboBox{ ID = "project", Editable = true }, ui:Button{ ID = "reload", Text = "↻", Weight = 0, MinimumSize = { 32, 0 } } },
    ui:HGroup{ Weight = 0, ui:Button{ ID = "pull", Text = "Ia din vedit" }, ui:Button{ ID = "push", Text = "Trimite în vedit" } },
    ui:Label{ ID = "status", Text = "", WordWrap = true, Alignment = { AlignTop = true } },
  },
})
local it = win:GetItems()

local function settings()
  conf.server = it.server.Text:gsub("/+$", "")
  conf.token = it.token.Text
  conf.project = it.project.CurrentText
  write_conf(conf)
  return conf
end

local function fill()
  it.project:Clear()
  local list, err = projects(settings())
  if not list then it.status.Text = err return end
  local want = guess(conf)
  for i, n in ipairs(list) do
    it.project:AddItem(n)
    if n == want then it.project.CurrentIndex = i - 1 end
  end
  it.status.Text = #list .. " proiecte în vedit."
end

local function run(fn)
  local c = settings()
  if c.project == "" then it.status.Text = "Alege proiectul." return end
  it.status.Text = "lucrez…"
  local ok, msg = fn(c, c.project)
  it.status.Text = (ok and "" or "Eroare: ") .. msg
  print("[vedit] " .. msg)
end

function win.On.reload.Clicked() fill() end
function win.On.pull.Clicked() run(pull) end
function win.On.push.Clicked() run(push) end
function win.On.vedit.Close() disp:ExitLoop() end

fill()
win:Show()
disp:RunLoop()
win:Hide()
