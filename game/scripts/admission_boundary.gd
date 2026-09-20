extends RefCounted
## Development-only server policy. No client claim grants protected permission.
const Context = preload("res://scripts/connection_context.gd")
const PROTECTED_NOTICE = "PROTECTED_UNAVAILABLE: falta integrar el verifier con admisión de juego"
enum Hello { IGNORE, DISCONNECT, IN_MATCH, DUPLICATE_NAME, ACCEPT }
var _connections: Dictionary = {}
var _generation = 0

static func profile_error(development: bool) -> Error:
	return OK if development else ERR_UNAVAILABLE

func connected(id: int, now_ms: int) -> Context:
	disconnected(id)
	_generation += 1
	var context = Context.new(id,_generation,now_ms)
	_connections[id] = context
	return context

func connection(id: int) -> Context:
	return _connections.get(id)

func disconnected(id: int) -> void:
	if _connections.has(id):
		_connections[id].close()
		_connections.erase(id)

func clear() -> void:
	for id in _connections.keys(): disconnected(id)

func expired_handshakes(now_ms: int) -> Array:
	var expired = []
	for id in _connections:
		var context: Context = _connections[id]
		if context.state == Context.State.PENDING and now_ms-context.connected_at_ms > 5000:
			expired.append(id)
	return expired

func hello(id: int, version: int, expected_version: int, nickname: String, development: bool, phase: String, members: Dictionary) -> Hello:
	var context = connection(id)
	if context == null or context.state != Context.State.PENDING: return Hello.IGNORE
	if version != expected_version or nickname.length() < 1 or nickname.length() > 24 or not nickname.is_valid_identifier():
		return Hello.DISCONNECT
	if phase == "IN_MATCH": return Hello.IN_MATCH
	for member in members.values():
		if member.name == nickname: return Hello.DUPLICATE_NAME
	if profile_error(development) != OK: return Hello.IGNORE
	context.state = Context.State.ADMITTED
	return Hello.ACCEPT

func admitted(id: int) -> bool:
	var context = connection(id)
	return context != null and context.state == Context.State.ADMITTED

func permits(id: int, claimed_session: String, server_session: String) -> bool:
	return admitted(id) and claimed_session == server_session
