extends SceneTree
const Admission = preload("res://scripts/admission_boundary.gd")
const Context = preload("res://scripts/connection_context.gd")
const Transport = preload("res://scripts/enet_transport.gd")
const Detector = preload("res://scripts/aim_detector.gd")

# Only suppress outbound snapshots in deterministic lifecycle fixtures.
# The release gate also runs real Network RPCs in separate ENet processes.
class LocalNetwork:
	extends "res://scripts/network.gd"
	func publish() -> void:
		changed.emit()

class SenderTransport:
	extends "res://scripts/enet_transport.gd"
	var sender = 2
	var listen_calls = 0
	func remote_sender_id() -> int:
		return sender
	func listen(_port: int, _max_players: int) -> Error:
		listen_calls += 1
		return FAILED

var checks = 0
var failures = 0

func check(value: bool, message: String) -> void:
	checks += 1
	if not value:
		failures += 1
		printerr("FAIL ",message)

func _initialize() -> void:
	call_deferred("run")

func policy() -> void:
	var boundary = Admission.new()
	check(Admission.profile_error(false) == ERR_UNAVAILABLE,"protected profile unavailable")
	check(Admission.profile_error(true) == OK,"explicit development profile available")
	check(boundary.hello(2,1,1,"Alice",true,"LOBBY",{}) == Admission.Hello.IGNORE,"unknown peer hello ignored")
	check(not boundary.permits(2,"session","session"),"unknown peer has no permission")
	var original = boundary.connected(2,100)
	check(not boundary.admitted(2),"pending connection has no permission")
	for nickname in ["","two words","x".repeat(25)]:
		check(boundary.hello(2,1,1,nickname,true,"LOBBY",{}) == Admission.Hello.DISCONNECT,"invalid nickname disconnects")
	check(boundary.hello(2,2,1,"Alice",true,"IN_MATCH",{}) == Admission.Hello.DISCONNECT,"version checked before phase")
	var roster = {3:{"name":"Alice"}}
	check(boundary.hello(2,1,1,"Alice",true,"IN_MATCH",roster) == Admission.Hello.IN_MATCH,"in-match refusal before duplicate")
	check(boundary.hello(2,1,1,"Alice",true,"LOBBY",roster) == Admission.Hello.DUPLICATE_NAME,"duplicate name refused")
	check(boundary.hello(2,1,1,"Alice",false,"LOBBY",{}) == Admission.Hello.IGNORE,"no development cannot admit")
	check(not boundary.admitted(2),"rejected hello has no permission")
	check(boundary.expired_handshakes(5100).is_empty(),"exactly five seconds remains pending")
	check(boundary.expired_handshakes(5101) == [2],"strictly over five seconds expires")
	check(boundary.hello(2,1,1,"Alice",true,"RESULTS",{}) == Admission.Hello.ACCEPT,"development allowed in results")
	check(boundary.expired_handshakes(100000).is_empty(),"admitted connection has no handshake timeout")
	check(boundary.permits(2,"session","session"),"admitted peer current session allowed")
	check(not boundary.permits(2,"other","session"),"wrong session refused")
	check(boundary.hello(2,2,1,"invalid name",true,"LOBBY",{}) == Admission.Hello.IGNORE,"second hello ignored before payload validation")
	original.last_sequence = 50
	original.last_input_tick = 10
	boundary.disconnected(2)
	check(original.state == Context.State.CLOSED and original.last_sequence == 0,"disconnect invalidates retained context")
	check(not boundary.admitted(2) and boundary.connection(2) == null,"disconnect removes permission")
	check(boundary.hello(2,1,1,"Alice",true,"LOBBY",{}) == Admission.Hello.IGNORE,"late hello cannot revive closed context")
	var replacement = boundary.connected(2,200)
	check(replacement != original and replacement.generation > original.generation,"peer id reuse creates another generation")
	check(not boundary.admitted(2) and replacement.last_sequence == 0 and replacement.last_input_tick == -1,"reused id inherits no permission or sequence")
	var other = boundary.connected(3,200)
	boundary.clear()
	check(replacement.state == Context.State.CLOSED and other.state == Context.State.CLOSED,"stop invalidates all retained contexts")
	check(boundary.expired_handshakes(100000).is_empty(),"stop removes all pending handshakes")
	check(boundary.connected(2,300).generation > replacement.generation,"stop does not reuse local generation")
	boundary.clear()

func lifecycle() -> void:
	var world = Node3D.new()
	root.add_child(world)
	var net = LocalNetwork.new()
	root.add_child(net)
	net.set_physics_process(false)
	net.world = world
	var sender = SenderTransport.new(net.multiplayer)
	net.transport = sender
	net.server_mode = true
	net.development = true
	net.session = "session"
	net.phase = "LOBBY"
	for id in [2,3]:
		net.admission.connected(id,0)
		net.admission.hello(id,1,1,"Player_"+str(id),true,"LOBBY",net.members)
		net.members[id] = {"name":"Player_"+str(id),"ready":false}
		net.detectors[id] = Detector.new()
	var context = net.admission.connection(2)
	var detector = net.detectors[2]
	detector.alert_sent = true
	check(net.host(7777,false) == ERR_UNAVAILABLE and sender.listen_calls == 0,"protected refusal opens no socket")
	check(net.session == "session" and net.admission.connection(2) == context,"protected refusal leaves existing session intact")
	net.ready_request("wrong")
	check(not net.members[2].ready,"ready rejects wrong session")
	net.ready_request("session")
	check(net.members[2].ready and net.phase == "LOBBY","one ready cannot start match")
	sender.sender = 3
	net.ready_request("session")
	check(net.phase == "IN_MATCH" and net.pawns.size() == 2,"two admitted peers start match")
	for seq in [0,-1,2147483648]:
		net.accept_intent(2,"session",seq,Vector2.ZERO,0,0,false,false,false)
		check(net.inputs.is_empty(),"sequence bounds reject without consumption")
	net.accept_intent(2,"session",1,Vector2.ZERO,0,0,true,true,true)
	check(context.last_sequence == 1 and net.inputs.has(2),"admitted intent accepted")
	net.finish_match()
	check(net.inputs.is_empty() and not net.members[2].ready,"finish clears intentions and ready")
	check(context == net.admission.connection(2) and context.last_sequence == 1,"finish preserves connection and sequence")
	sender.sender = 2
	net.ready_request("session")
	sender.sender = 3
	net.ready_request("session")
	check(net.phase == "IN_MATCH" and net.admission.connection(2) == context,"rematch preserves connection")
	check(net.detectors[2] == detector and detector.alert_sent,"rematch leaves detector lifecycle unchanged")
	net.tick += 1
	net.accept_intent(2,"session",1,Vector2.ZERO,0,0,false,false,false)
	check(net.inputs.is_empty(),"replayed pre-rematch sequence rejected")
	net.accept_intent(2,"session",2,Vector2.ZERO,0,0,false,false,false)
	check(context.last_sequence == 2,"next sequence accepted in rematch")
	net._peer_disconnected(2)
	check(not net.inputs.has(2) and not net.pawns.has(2) and not net.members.has(2) and not net.detectors.has(2),"disconnect removes gameplay state")
	check(context.state == Context.State.CLOSED and not net.admission.admitted(2),"disconnect removes permission")
	net._peer_connected(2)
	var new_context = net.admission.connection(2)
	net.members[2] = {"name":"Pending","ready":false}
	net.spawn(2)
	net.accept_intent(2,"session",1,Vector2.ZERO,0,0,false,false,false)
	check(not net.inputs.has(2),"pending connection cannot use stale gameplay state")
	net.phase = "RESULTS"
	sender.sender = 2
	net.ready_request("session")
	check(not net.members[2].ready,"pending connection cannot ready")
	net.stop("")
	check(new_context.state == Context.State.CLOSED and net.admission.connection(3) == null,"stop retires pending and admitted contexts")
	check(net.members.is_empty() and net.inputs.is_empty() and net.phase == "DISCONNECTED" and net.session.is_empty(),"stop clears session and gameplay state")
	check(net.host(7777,true) == FAILED and sender.listen_calls == 1,"transport open failure propagates")
	check(not net.server_mode and not net.development and net.session.is_empty() and net.phase == "DISCONNECTED","failed host grants no permission or session")
	net.queue_free()
	world.queue_free()

func real_transport() -> void:
	var server_api = MultiplayerAPI.create_default_interface()
	var client_api = MultiplayerAPI.create_default_interface()
	var server = Transport.new(server_api)
	var client = Transport.new(client_api)
	check(server.listen(0,2) == OK,"real ENet server opens ephemeral port")
	if not server_api.multiplayer_peer is ENetMultiplayerPeer: return
	var peer: ENetMultiplayerPeer = server_api.multiplayer_peer
	var port = peer.host.get_local_port()
	check(server.unique_id() == 1,"server is transport authority")
	check(client.connect_to("127.0.0.1",port) == OK,"real ENet client opens")
	var deadline = Time.get_ticks_msec()+3000
	while server_api.get_peers().is_empty() and Time.get_ticks_msec() < deadline:
		server_api.poll()
		client_api.poll()
		await process_frame
	check(server_api.get_peers().size() == 1,"real transport connects one peer")
	if not server_api.get_peers().is_empty():
		check(server_api.get_peers()[0] == client.unique_id(),"real transport attributes client identity")
		server.disconnect_peer(client.unique_id())
		deadline = Time.get_ticks_msec()+3000
		while not server_api.get_peers().is_empty() and Time.get_ticks_msec() < deadline:
			server_api.poll()
			client_api.poll()
			await process_frame
		check(server_api.get_peers().is_empty(),"real transport disconnects peer")
	client.close()
	server.close()
	server.close()
	check(server_api.multiplayer_peer is OfflineMultiplayerPeer and client_api.multiplayer_peer is OfflineMultiplayerPeer,"close is idempotent and replaces transport")
	check(server.listen(port,2) == OK,"closed socket can be reopened")
	server.close()

func occupied_port() -> void:
	# Invoked in a separate process by test_game_tools.py: Godot emits a native
	# error for this expected failure. That test checks its exact diagnostic.
	var owner_api = MultiplayerAPI.create_default_interface()
	var other_api = MultiplayerAPI.create_default_interface()
	var owner = Transport.new(owner_api)
	var other = Transport.new(other_api)
	check(owner.listen(0,2) == OK,"port owner starts")
	if owner_api.multiplayer_peer is ENetMultiplayerPeer:
		var port = owner_api.multiplayer_peer.host.get_local_port()
		check(other.listen(port,2) == ERR_CANT_CREATE,"occupied port returns original ENet error")
		check(not other_api.multiplayer_peer is ENetMultiplayerPeer,"failed listen installs no ENet peer")
		check(owner_api.multiplayer_peer.host.get_local_port() == port,"failure preserves port owner")
		check(other.listen(0,2) == OK,"adapter recovers after failed listen")
	other.close()
	owner.close()

func run() -> void:
	if "--occupied-port" in OS.get_cmdline_user_args():
		occupied_port()
		print(JSON.stringify({"suite":"occupied-port","checks":checks,"failures":failures}))
		quit(1 if failures else 0)
		return
	policy()
	lifecycle()
	await process_frame
	await real_transport()
	print(JSON.stringify({"suite":"admission-boundary","checks":checks,"failures":failures,"scope":"development fixtures and real ENet loopback; no protected admission"}))
	quit(1 if failures else 0)
