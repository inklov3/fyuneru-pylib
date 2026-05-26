local source_stream = KEYS[1]
local xq_stream = KEYS[2]

local group_name = ARGV[1]
local message_id = ARGV[2]
local original_id = ARGV[3]
local queue_name = ARGV[4]
local payload = ARGV[5]
local attempt = ARGV[6]
local error = ARGV[7]
local traceback = ARGV[8]
local failed_at = ARGV[9]
local xq_maxlen = ARGV[10]

local xq_stream_id
if xq_maxlen ~= nil and xq_maxlen ~= "" then
    xq_stream_id = redis.call(
        "XADD",
        xq_stream,
        "MAXLEN",
        "~",
        xq_maxlen,
        "*",
        "original_id",
        original_id,
        "queue",
        queue_name,
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
else
    xq_stream_id = redis.call(
        "XADD",
        xq_stream,
        "*",
        "original_id",
        original_id,
        "queue",
        queue_name,
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
end

redis.call("XACK", source_stream, group_name, message_id)

return xq_stream_id
