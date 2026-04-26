local source_stream = KEYS[1]
local xq_stream = KEYS[2]

local group_name = ARGV[1]
local message_id = ARGV[2]
local original_id = ARGV[3]
local queue_name = ARGV[4]
local name = ARGV[5]
local payload = ARGV[6]
local attempt = ARGV[7]
local error = ARGV[8]
local traceback = ARGV[9]
local failed_at = ARGV[10]

local xq_stream_id = redis.call(
    "XADD",
    xq_stream,
    "*",
    "original_id",
    original_id,
    "queue",
    queue_name,
    "name",
    name,
    "payload",
    payload,
    "attempt",
    attempt,
    "error",
    error,
    "traceback",
    traceback,
    "failed_at",
    failed_at
)

redis.call("XACK", source_stream, group_name, message_id)

return xq_stream_id
