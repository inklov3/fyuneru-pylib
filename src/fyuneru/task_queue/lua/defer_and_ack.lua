local source_stream = KEYS[1]
local queue_stream = KEYS[2]

local group_name = ARGV[1]
local message_id = ARGV[2]
local defer_id = ARGV[3]
local name = ARGV[4]
local payload = ARGV[5]
local attempt = ARGV[6]
local eta = ARGV[7]
local created_at = ARGV[8]

local defer_stream_id = redis.call(
    "XADD",
    queue_stream,
    "*",
    "id",
    defer_id,
    "name",
    name,
    "payload",
    payload,
    "attempt",
    attempt,
    "eta",
    eta,
    "created_at",
    created_at
)

redis.call("XACK", source_stream, group_name, message_id)

return defer_stream_id
