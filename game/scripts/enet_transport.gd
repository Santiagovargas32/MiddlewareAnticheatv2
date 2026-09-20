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

func close() -> void:
	if _api.multiplayer_peer: _api.multiplayer_peer.close()
	_api.multiplayer_peer = OfflineMultiplayerPeer.new()

func disconnect_peer(id: int) -> void:
	_api.multiplayer_peer.disconnect_peer(id)

func remote_sender_id() -> int:
	return _api.get_remote_sender_id()

func unique_id() -> int:
	return _api.get_unique_id()
