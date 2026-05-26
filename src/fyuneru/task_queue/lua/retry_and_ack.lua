local source_stream = KEYS[1]
local queue_stream = KEYS[2]

local group_name = ARGV[1]
local message_id = ARGV[2]
local retry_id = ARGV[3]
local payload = ARGV[4]
local attempt = ARGV[5]
local eta = ARGV[6]
local created_at = ARGV[7]

local retry_stream_id = redis.call(
    "XADD",
    queue_stream,
    "*",
    "id",
    retry_id,
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

return retry_stream_id
