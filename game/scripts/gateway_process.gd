extends RefCounted
## Private inherited IPC only. Poll from the main loop; never wait for TLS here.
const PROTOCOL = "arena-gateway-ipc/1"
const MAX_ID = 2147483647
var child: Dictionary = {}
var run_id = ""
var generation = 0
var tx = 0
var rx = 0
var buffer = PackedByteArray()
var stderr_tail = PackedByteArray()
var failed = false
var closing = false
var close_at = 0
var killed = false
var child_exited = false
var last_received = 0
var last_sent = 0
var ready = false
var started_at = 0
var partial_at = 0
var failure_reason = ""
var started = false

static func exact(value: Variant, names: Array) -> bool:
	if not value is Dictionary or value.size() != names.size(): return false
	for name in names:
		if not value.has(name): return false
	return true

static func number(value: Variant, low: int = 1, high: int = MAX_ID) -> bool:
	return (value is int or value is float) and is_finite(value) and value == floor(value) and value >= low and value <= high

static func hex_id(value: Variant, length: int = 32) -> bool:
	if not value is String or value.length() != length: return false
	for c in value:
		if not c in "0123456789abcdef": return false
	return true

static func strict_json(data: PackedByteArray) -> Variant:
	if data.is_empty() or data.size() > 4096: return null
	# Our encoder uses JSON ASCII escapes. Invalid UTF-8 never reaches Godot's
	# string decoder (which would otherwise emit engine diagnostics).
	for byte in data:
		if byte > 127: return null
	var text = data.get_string_from_utf8()
	if text.to_utf8_buffer() != data: return null
	# Godot's JSON parser accepts duplicate keys. Reject them before consuming
	# its result, tracking each object's keys and respecting escaped strings.
	var stack: Array = []
	var index = 0
	while index < text.length():
		var c = text[index]
		if c == "{" or c == "[":
			stack.append({})
			if stack.size() > 4: return null
		elif c == "}" or c == "]":
			if stack.is_empty(): return null
			stack.pop_back()
		elif c == '"':
			var start = index
			index += 1
			while index < text.length() and text[index] != '"':
				if text[index] == "\\": index += 1
				index += 1
			if index >= text.length(): return null
			var after = index+1
			while after < text.length() and text[after] in " \t\r\n": after += 1
			if after < text.length() and text[after] == ":":
				if stack.is_empty(): return null
				var key_parser = JSON.new()
				if key_parser.parse(text.substr(start,index-start+1)) != OK: return null
				var key = key_parser.data
				if stack[-1].has(key): return null
				stack[-1][key] = true
		elif c in "-0123456789":
			while index+1 < text.length() and text[index+1] in "0123456789.eE+-":
				index += 1
				if text[index] in ".eE+": return null
		index += 1
	var parser = JSON.new()
	if parser.parse(text) != OK: return null
	return parser.data

func start(python: String, script: String, config: Dictionary, server_run: String, serial: int) -> bool:
	if started or not hex_id(server_run) or not number(serial) or not python.is_absolute_path() or not script.is_absolute_path(): return false
	started = true  # A closed supervisor is terminal; use a new generation/object.
	run_id = server_run
	generation = serial
	child = OS.execute_with_pipe(python,PackedStringArray([script]),false)
	if child.is_empty():
		failed = true
		return false
	last_received = Time.get_ticks_msec()
	started_at = last_received
	return send("CONFIG",config)

func send(operation: String, body: Dictionary) -> bool:
	if failed or closing or child.is_empty(): return false
	if tx >= MAX_ID:
		fail("sequence_overflow")
		return false
	tx += 1
	var data = JSON.stringify({"protocol_version":PROTOCOL,"server_run_id":run_id,"gateway_generation":generation,"request_id":tx,"operation":operation,"body":body}).to_utf8_buffer()
	if data.is_empty() or data.size() > 4096:
		fail("frame_size")
		return false
	var packet = PackedByteArray([0,0,0,0])
	packet[0] = (data.size() >> 24)&255
	packet[1] = (data.size() >> 16)&255
	packet[2] = (data.size() >> 8)&255
	packet[3] = data.size()&255
	packet.append_array(data)
	if not child.stdio.store_buffer(packet):
		# Progress is unknown: never retry this frame after a partial write.
		fail("ipc_write")
		return false
	last_sent = Time.get_ticks_msec()
	return true

func valid_message(value: Variant) -> bool:
	if not exact(value,["protocol_version","server_run_id","gateway_generation","request_id","operation","body"]): return false
	if value.protocol_version != PROTOCOL or value.server_run_id != run_id or not number(value.gateway_generation) or value.gateway_generation != generation or not number(value.request_id) or value.request_id != rx+1: return false
	var body = value.body
	match value.operation:
		"HEARTBEAT":
			if not exact(body,[]): return false
		"READY":
			if ready or not exact(body,["port"]) or not number(body.port,0,65535): return false
			ready = true
		"ROUTE_OPEN":
			if not ready or not exact(body,["channel_id","attestor","address","port","remote_run_id","game_session_id"]): return false
			if not hex_id(body.channel_id) or not hex_id(body.attestor,64) or body.address != "127.0.0.1" or not number(body.port,1,65535) or not hex_id(body.remote_run_id) or not hex_id(body.game_session_id): return false
		"ROUTE_CLOSE":
			if not exact(body,["channel_id"]) or not hex_id(body.channel_id): return false
		_: return false
	rx = int(value.request_id)
	return true

func poll() -> Array:
	var messages: Array = []
	if child.is_empty(): return messages
	var now = Time.get_ticks_msec()
	var diagnostic: PackedByteArray = child.stderr.get_buffer(4096)
	stderr_tail.append_array(diagnostic)
	if stderr_tail.size() > 65536: stderr_tail = stderr_tail.slice(stderr_tail.size()-65536)
	if closing:
		if child_exited or not OS.is_process_running(child.pid):
			child.stdio.close()
			child.stderr.close()
			child.clear()
		elif now-close_at > 2000 and not killed:
			# Godot's Unix kill also waits/reaps its child. Do not query that PID
			# again after success (it is no longer registered as our live child).
			child_exited = OS.kill(child.pid) == OK
			killed = true
		elif now-close_at > 3000:
			failed = true
		return messages
	if not OS.is_process_running(child.pid):
		child_exited = true
		fail("child_exit")
		return messages
	if now-last_received > 1000:
		fail("heartbeat_timeout")
		return messages
	if not ready and now-started_at > 5000:
		fail("startup_timeout")
		return messages
	if partial_at > 0 and now-partial_at > 200:
		fail("partial_timeout")
		return messages
	if now-last_sent >= 250: send("HEARTBEAT",{})
	if failed or closing: return messages
	var poll_started = Time.get_ticks_usec()
	var bytes_read = 0
	var bytes_processed = 0
	while messages.size() < 32 and bytes_read < 65536 and Time.get_ticks_usec()-poll_started < 1000:
		if buffer.size() >= 4:
			var length = (int(buffer[0])<<24)|(int(buffer[1])<<16)|(int(buffer[2])<<8)|int(buffer[3])
			if length < 1 or length > 4096:
				fail("frame_size")
				return []
			if buffer.size() >= length+4:
				if bytes_processed+length+4 > 65536: break
				bytes_processed += length+4
				var message = strict_json(buffer.slice(4,length+4))
				buffer = buffer.slice(length+4)
				partial_at = 0 if buffer.is_empty() else now
				if not valid_message(message):
					fail("ipc_message")
					return []
				last_received = now
				messages.append(message)
				continue
		var data: PackedByteArray = child.stdio.get_buffer(4096)
		if data.is_empty(): break
		if buffer.is_empty(): partial_at = now
		bytes_read += data.size()
		buffer.append_array(data)
	return messages

func fail(reason: String = "ipc_failure") -> void:
	failed = true
	failure_reason = reason
	shutdown()

func shutdown() -> void:
	if closing or child.is_empty(): return
	if not failed: send("SHUTDOWN",{})
	closing = true
	close_at = Time.get_ticks_msec()
	buffer.clear()
	# EOF is authoritative for the child; continue polling stderr/exit for <=3 s.
	child.stdio.close()
