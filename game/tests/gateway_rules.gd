extends SceneTree
const IPC = preload("res://scripts/gateway_process.gd")
const Routes = preload("res://scripts/peer_routes.gd")
var checks = 0
var failures = 0

func check(value: bool, message: String) -> void:
	checks += 1
	if not value:
		failures += 1
		printerr("FAIL ",message)

func route(channel: String, port: int, attestor: String = "c".repeat(64)) -> Dictionary:
	return {"channel_id":channel,"attestor":attestor,"address":"127.0.0.1","port":port,"remote_run_id":"a".repeat(32),"game_session_id":"b".repeat(32)}

func _initialize() -> void:
	for text in ['{"a":1,"a":2}','{"a":1,"\\u0061":2}','{"a":1.0}','{"a":1e0}','{"a":NaN}','[[[[[0]]]]]','{"a":']:
		check(IPC.strict_json(text.to_utf8_buffer()) == null,"strict JSON rejects ambiguous, malformed or deep data")
	check(IPC.strict_json(PackedByteArray([255])) == null,"invalid UTF8 rejected before decoder")
	check(IPC.strict_json('{"a":{"a":1},"b":"escaped\\\"text"}'.to_utf8_buffer()) is Dictionary,"duplicate names in separate objects and escaped strings are valid")
	var process = IPC.new()
	process.run_id = "a".repeat(32)
	process.generation = 1
	var message = {"protocol_version":IPC.PROTOCOL,"server_run_id":process.run_id,"gateway_generation":1,"request_id":1,"operation":"READY","body":{"port":12345}}
	check(process.valid_message(message),"matching startup context accepted")
	check(not process.valid_message(message),"IPC replay rejected")
	message.request_id = 2
	message.operation = "HEARTBEAT"
	message.body = {}
	for key in ["server_run_id","gateway_generation","protocol_version","request_id"]:
		var wrong = message.duplicate(true)
		wrong[key] = "wrong" if key in ["server_run_id","protocol_version"] else 3
		check(not process.valid_message(wrong),"wrong envelope field rejected without consuming sequence")
	check(process.valid_message(message),"valid response survives rejected contexts")
	message.request_id = 3
	message.body = {"allow":true}
	check(not process.valid_message(message),"heartbeat cannot carry permission")
	message.operation = "REGISTER_RESULT"
	message.body = {}
	check(not process.valid_message(message),"unimplemented admission operation rejected")
	var routes = Routes.new("a".repeat(32),"b".repeat(32))
	check(routes.consume(2,"127.0.0.1",20000).is_empty(),"direct UDP has no route")
	var first = route("1".repeat(32),20000)
	var foreign = first.duplicate()
	foreign.remote_run_id = "d".repeat(32)
	check(not routes.open_route(foreign),"route from another run rejected")
	foreign = first.duplicate()
	foreign.allow = true
	check(not routes.open_route(foreign),"client permission claim rejected")
	check(routes.open_route(first),"authenticated inherited route accepted")
	check(not routes.open_route(first),"route OPEN replay rejected")
	check(routes.consume(2,"192.0.2.1",20000).is_empty(),"same port from another address rejected")
	var bound = routes.consume(2,"127.0.0.1",20000)
	check(not bound.is_empty() and bound.attestor == first.attestor,"actual endpoint selects identity")
	check(not routes.admission.admitted(2),"transport association never grants permission")
	check(routes.consume(3,"127.0.0.1",20000).is_empty(),"second peer on same route rejected")
	check(routes.open_route(route("2".repeat(32),20001,"d".repeat(64))),"second identity route accepted")
	check(routes.consume(2,"127.0.0.1",20001).is_empty(),"existing peer cannot move to another identity")
	check(routes.retire(first.channel_id) == 2,"retire returns peer to disconnect")
	check(bound.context.state == bound.context.State.CLOSED,"retirement invalidates retained context")
	check(not routes.open_route(route("3".repeat(32),20000)),"retired endpoint cannot be recycled")
	check(not routes.open_route(route(first.channel_id,20002)),"retired channel cannot be recycled")
	var replacement = routes.consume(2,"127.0.0.1",20001)
	check(replacement.attestor == "d".repeat(64) and replacement.context.generation > bound.context.generation,"peer reuse gets fresh identity and generation")
	routes.retire(replacement.channel_id)
	routes.serial = IPC.MAX_ID
	check(routes.open_route(route("4".repeat(32),20002)),"route allocated before generation exhaustion")
	check(routes.consume(2,"127.0.0.1",20002).is_empty(),"generation overflow refuses association")
	routes.close()
	check(routes.routes.is_empty() and routes.admission.connection(2) == null,"close removes associations")
	check(not routes.open_route(route("5".repeat(32),20003)),"closed table cannot revive")
	var capacity = Routes.new("a".repeat(32),"b".repeat(32))
	for i in range(8): check(capacity.open_route(route("%032x" % i,21000+i)),"up to eight active routes")
	check(not capacity.open_route(route("%032x" % 8,21008)),"ninth active route rejected")
	for i in range(8): capacity.retire("%032x" % i)
	for i in range(8,256):
		if not capacity.open_route(route("%032x" % i,21000+i)): failures += 1
		capacity.retire("%032x" % i)
	check(capacity.ports.size() == 256,"256 endpoints retained without reuse")
	check(not capacity.open_route(route("%032x" % 256,21256)),"capacity exhausted requires new gateway")
	print(JSON.stringify({"suite":"gateway-routes-ipc","checks":checks,"failures":failures,"scope":"fixtures; no protected gameplay"}))
	quit(1 if failures else 0)
