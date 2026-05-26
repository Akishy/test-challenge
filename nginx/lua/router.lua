local _M = {}

local function trim(s)
    return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

local function split_csv(s)
    local result = {}

    if not s or s == "" then
        return result
    end

    for item in string.gmatch(s, "([^,]+)") do
        local value = trim(item)
        if value ~= "" then
            table.insert(result, value)
        end
    end

    return result
end

local function contains(list, value)
    for _, item in ipairs(list) do
        if item == value then
            return true
        end
    end
    return false
end

local function append_once(list, value)
    if value and value ~= "" and not contains(list, value) then
        table.insert(list, value)
    end
end

local function getenv_number(name, default)
    local raw = os.getenv(name)
    local parsed = tonumber(raw)
    if parsed == nil then
        return default
    end
    return parsed
end

local current_nginx = os.getenv("NGINX_NAME") or "nginx-unknown"
local total_nginx = getenv_number("NGINX_TOTAL", 3)
local forward_probability = getenv_number("FORWARD_PROBABILITY", 0.5)
local app_upstream = os.getenv("APP_UPSTREAM") or "app:8000"

function _M.route(is_entrypoint)
    local current_ip = ngx.var.server_addr or ngx.var.remote_addr or "unknown"

    local next_xff
    local visited

    if is_entrypoint then
        -- Первый nginx после LB.
        -- Доверяем только PROXY protocol от LB.
        -- Клиентский X-Forwarded-For полностью игнорируем.
        local client_ip = ngx.var.proxy_protocol_addr
        if not client_ip or client_ip == "" then
            client_ip = ngx.var.remote_addr or "unknown"
        end

        next_xff = client_ip .. ", " .. current_ip
        visited = { current_nginx }
    else
        -- Внутренний переход nginx -> nginx.
        -- Продолжаем цепочку, которую сформировал предыдущий nginx.
        local incoming_xff = ngx.var.http_x_forwarded_for

        if incoming_xff and incoming_xff ~= "" then
            next_xff = incoming_xff .. ", " .. current_ip
        else
            -- Fallback для некорректного внутреннего запроса.
            next_xff = (ngx.var.remote_addr or "unknown") .. ", " .. current_ip
        end

        visited = split_csv(ngx.var.http_x_visited_nginx)
        append_once(visited, current_nginx)
    end

    local candidates = {}

    for i = 1, total_nginx do
        local candidate = "nginx-" .. i

        -- Не идём в себя и не ходим повторно в уже посещённый nginx.
        -- Это защищает от циклов вида nginx-1 -> nginx-2 -> nginx-1.
        if candidate ~= current_nginx and not contains(visited, candidate) then
            table.insert(candidates, candidate)
        end
    end

    local target

    if #candidates > 0 and math.random() < forward_probability then
        local next_nginx = candidates[math.random(#candidates)]
        target = next_nginx .. ":8080"
    else
        target = app_upstream
    end

    ngx.var.next_xff = next_xff
    ngx.var.next_visited = table.concat(visited, ",")
    ngx.var.target_upstream = target
end

return _M