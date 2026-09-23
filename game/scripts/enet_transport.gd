extends RefCounted
## Owns ENet setup/teardown only. RPC declarations remain on the Network node.
var _api: MultiplayerAPI

func _init(api: MultiplayerAPI) -> void:
	_api = api

func listen(port: int, max_players: int) -> Error:
	var peer = ENetMultiplayerPeer.new()
	var error = peer.create_server(port,max_players)
	if error == OK: _api.multiplayer_peer = peer
	else: peer.close()
	return error

func connect_to(address: String, port: int) -> Error:
	var peer = ENetMultiplayerPeer.new()
	var error = peer.create_client(address,port)
	if error == OK: _api.multiplayer_peer = peer
	else: peer.close()
	return error

static func loopback_client(peer: ENetMultiplayerPeer, port: int) -> Error:
	# create_client(local_port=0) ignores bind_ip. Select an ephemeral port,
	# then explicitly bind ENet to loopback. If the port is taken in between,
	# create_client fails closed; never fall back to an unbound/wildcard socket.
	var reservation = PacketPeerUDP.new()
	var error = reservation.bind(0,"127.0.0.1")
	if error != OK: return error
	var local_port = reservation.get_local_port()
	reservation.close()
	peer.set_bind_ip("127.0.0.1")
	return peer.create_client("127.0.0.1",port,4,0,0,local_port)

func close() -> void:
	if _api.multiplayer_peer: _api.multiplayer_peer.close()
	_api.multiplayer_peer = OfflineMultiplayerPeer.new()

func disconnect_peer(id: int) -> void:
	_api.multiplayer_peer.disconnect_peer(id)

func remote_sender_id() -> int:
	return _api.get_remote_sender_id()

func unique_id() -> int:
	return _api.get_unique_id()
