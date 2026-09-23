extends SceneTree
## Internal transport harness. Does not instantiate the game or grant admission.
const Process = preload("res://scripts/gateway_process.gd")
const Routes = preload("res://scripts/peer_routes.gd")
const Transport = preload("res://scripts/enet_transport.gd")
var helper = Process.new()
var peer = ENetMultiplayerPeer.new()
var routes
var options: Dictionary
var server = false
var end_at = 0
var stopping = false
var failed = false
var connected = false
var sequence = 0
var next_send = 0
var sent: Dictionary = {}
var rtt: Array = []
var channels: Dictionary = {}
var modes: Dictionary = {}
var echoes = 0
var frames = 0
var child_pid = 0
var direct_probe: ENetMultiplayerPeer
var burst_us = 0

func event(value: Dictionary) -> void:
	print(JSON.stringify(value))

func _initialize() -> void:
	var args = OS.get_cmdline_user_args()
	if args.size() != 1:
		quit(2)
		return
	options = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	server = options.configuration.role == "server"
	options.configuration.port = int(options.configuration.port)
	end_at = Time.get_ticks_msec()+int(options.seconds*1000)
	peer.set_bind_ip("127.0.0.1")
	if server:
		if peer.create_server(0,8,4) != OK:
			quit(2)
			return
		options.configuration.game_port = peer.host.get_local_port()
		if options.get("probe_direct",false):
			direct_probe = ENetMultiplayerPeer.new()
			direct_probe.create_client("127.0.0.1",peer.host.get_local_port(),4)
		routes = Routes.new(options.run_id,options.configuration.game_session_id)
		peer.peer_connected.connect(func(id: int):
			var association = routes.associate(peer,id)
			if association.is_empty():
				if routes.closed:
					failed = true
					shutdown()
					return
				peer.disconnect_peer(id)
				event({"event":"unbound_peer"})
			else:
				event({"event":"bound_peer","peer":id,"channel":association.channel_id,"attestor":association.attestor,"generation":association.context.generation,"permission":routes.admission.admitted(id)}))
		peer.peer_disconnected.connect(func(id: int):
			if routes.peers.has(id):
				var channel = routes.peers[id]
				routes.retire(channel)
				helper.send("ROUTE_CLOSE",{"channel_id":channel}))
	else:
		peer.peer_connected.connect(func(id: int):
			if id == 1: connected = true)
	if not helper.start(options.python,options.helper,options.configuration,options.run_id,1):
		failed = true
		shutdown()
	child_pid = helper.child.get("pid",0)
	event({"event":"child","pid":child_pid})
	if options.get("ipc_burst",false):
		var began = Time.get_ticks_usec()
		for i in range(128):
			if not helper.send("HEARTBEAT",{"fixture":"x".repeat(3000)}): break
		burst_us = Time.get_ticks_usec()-began

func shutdown() -> void:
	if stopping: return
	stopping = true
	if server: routes.close()
	peer.close()
	if direct_probe: direct_probe.close()
	helper.shutdown()

func _process(_delta: float) -> bool:
	frames += 1
	for message in helper.poll():
		var body: Dictionary = message.body
		match message.operation:
			"READY":
				if server: event({"event":"ready","port":body.port,"udp_port":peer.host.get_local_port()})
			"ROUTE_OPEN":
				var ack = {"channel_id":body.channel_id,"route_request_id":int(message.request_id)}
				if server:
					if not routes.open_route(body):
						failed = true
						shutdown()
						continue
				else:
					if Transport.loopback_client(peer,int(body.port)) != OK:
						failed = true
						shutdown()
						continue
					ack.client_port = peer.host.get_local_port()
					event({"event":"client_endpoint","port":ack.client_port})
				helper.send("ROUTE_ACK",ack)
			"ROUTE_CLOSE":
				if server:
					var id = routes.retire(body.channel_id)
					if id != 0: peer.disconnect_peer(id)
				else:
					failed = true
					shutdown()
	if helper.failed and not stopping:
		failed = true
		shutdown()
	if stopping:
		if helper.child.is_empty():
			event({"event":"exit","failed":failed,"echoes":echoes,"channels":channels.keys(),"modes":modes.keys(),"rtt_ms":rtt,"frames":frames,"child":child_pid,"reason":helper.failure_reason,"stderr_bytes":helper.stderr_tail.size(),"burst_us":burst_us,"routes_remaining":routes.routes.size() if server else 0,"diagnostic":helper.stderr_tail.slice(maxi(0,helper.stderr_tail.size()-128)).get_string_from_utf8()})
			quit(1 if failed else 0)
		return false
	if peer.get_connection_status() != MultiplayerPeer.CONNECTION_DISCONNECTED:
		if direct_probe and direct_probe.get_connection_status() != MultiplayerPeer.CONNECTION_DISCONNECTED: direct_probe.poll()
		peer.poll()
		while peer.get_available_packet_count() > 0:
			var sender = peer.get_packet_peer()
			var channel = peer.get_packet_channel()
			var mode = peer.get_packet_mode()
			var packet = peer.get_packet()
			if server:
				if not routes.peers.has(sender): continue
				peer.set_target_peer(sender)
				peer.transfer_channel = channel
				peer.transfer_mode = mode
				peer.put_packet(packet)
			else:
				var key = packet.get_string_from_ascii()
				if sender != 1 or not sent.has(key):
					failed = true
					shutdown()
					break
				if channel != sent[key].channel or mode != sent[key].mode:
					failed = true
					shutdown()
					break
				rtt.append(Time.get_ticks_msec()-sent[key].at)
				sent.erase(key)
			echoes += 1
			channels[channel] = true
			modes[mode] = true
	var now = Time.get_ticks_msec()
	if not server and connected and now >= next_send and sent.size() < 64:
		sequence += 1
		var text = "probe:%d:%d" % [peer.get_unique_id(),sequence]
		sent[text] = {"at":now,"channel":sequence%4,"mode":sequence%3}
		peer.transfer_channel = sequence%4
		peer.transfer_mode = sequence%3
		peer.set_target_peer(1)
		peer.put_packet(text.to_ascii_buffer())
		next_send = now+50
	if now >= end_at:
		if not server and (echoes < 8 or channels.size() != 4 or modes.size() != 3): failed = true
		shutdown()
	return false
