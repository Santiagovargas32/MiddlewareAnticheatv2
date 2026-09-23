extends RefCounted
## Transport association only. Never calls hello/admit or grants gameplay.
const Admission = preload("res://scripts/admission_boundary.gd")
const IPC = preload("res://scripts/gateway_process.gd")
var admission = Admission.new()
var routes: Dictionary = {}
var ports: Dictionary = {}
var used_channels: Dictionary = {}
var peers: Dictionary = {}
var run_id: String
var session: String
var closed = false
var serial = 0

func _init(server_run: String, game_session: String) -> void:
	run_id = server_run
	session = game_session

func open_route(body: Dictionary) -> bool:
	if closed or routes.size() >= 8 or ports.size() >= 256: return false
	if not IPC.exact(body,["channel_id","attestor","address","port","remote_run_id","game_session_id"]): return false
	if not IPC.hex_id(body.channel_id) or not IPC.hex_id(body.attestor,64) or body.address != "127.0.0.1" or not IPC.number(body.port,1,65535) or body.remote_run_id != run_id or body.game_session_id != session: return false
	if used_channels.has(body.channel_id) or ports.has(int(body.port)): return false
	var route = body.duplicate()
	route.peer_id = 0
	routes[body.channel_id] = route
	ports[int(body.port)] = body.channel_id
	used_channels[body.channel_id] = true
	return true

func associate(peer: ENetMultiplayerPeer, id: int) -> Dictionary:
	var endpoint = peer.get_peer(id)
	if endpoint == null: return {}
	return consume(id,endpoint.get_remote_address(),endpoint.get_remote_port())

func consume(id: int, address: String, port: int) -> Dictionary:
	if serial >= IPC.MAX_ID:
		close()
		return {}
	if closed or not IPC.number(id,2) or peers.has(id) or address != "127.0.0.1": return {}
	var channel = ports.get(port,"")
	if not routes.has(channel) or routes[channel].peer_id != 0: return {}
	serial += 1
	var route: Dictionary = routes[channel]
	route.peer_id = id
	peers[id] = channel
	var context = admission.connected(id,Time.get_ticks_msec())
	return {"channel_id":channel,"attestor":route.attestor,"context":context}

func retire(channel: String) -> int:
	if not routes.has(channel): return 0
	var id = int(routes[channel].peer_id)
	admission.disconnected(id)
	peers.erase(id)
	routes.erase(channel)
	# ports and used_channels deliberately retain tombstones until gateway exit.
	return id

func close() -> void:
	closed = true
	for channel in routes.keys(): retire(channel)
	admission.clear()
