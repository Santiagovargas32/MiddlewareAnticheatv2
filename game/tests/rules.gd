extends SceneTree
const Arena = preload("res://scripts/arena.gd")
const Pawn = preload("res://scripts/pawn.gd")
const Network = preload("res://scripts/network.gd")
const Detector = preload("res://scripts/aim_detector.gd")
var failures = 0
var checks = 0

func check(value: bool, message: String) -> void:
	checks += 1
	if not value:
		failures += 1
		printerr("FAIL ",message)

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	var arena = Arena.new()
	root.add_child(arena)
	var pawn = Pawn.new()
	arena.add_child(pawn)
	pawn.position = Vector3(0,1,-10)
	for i in range(90):
		await physics_frame
		pawn.simulate(1.0/60,{"move":Vector2.ZERO})
	check(pawn.is_on_floor(),"gravity and floor collision")
	var start = pawn.position
	for i in range(60):
		await physics_frame
		pawn.simulate(1.0/60,{"move":Vector2(1,0)})
	check(absf(pawn.position.x-start.x-6) < 0.2,"server movement speed 6m/s")
	pawn.simulate(1.0/60,{"jump":true})
	check(pawn.velocity.y > 0,"jump requires floor")
	pawn.ammo = 0
	check(not pawn.can_fire(),"no ammo prevents firing")
	pawn.simulate(1.0/60,{"reload":true})
	check(pawn.reload_time > 1,"reload is timed")
	check(not pawn.can_fire(),"reload blocks fire")
	for i in range(100):
		await physics_frame
		pawn.simulate(1.0/60,{})
	check(pawn.ammo == 12 and pawn.can_fire(),"reload completes")
	pawn.cooldown = 0.18
	check(not pawn.can_fire(),"fire cooldown")
	pawn.health = 0
	check(not pawn.can_fire(),"dead player cannot fire")
	start = pawn.position
	pawn.simulate(1.0/60,{"move":Vector2(1,0)})
	check(pawn.position == start,"dead player cannot move")
	var normal = Detector.new()
	for i in range(600): normal.observe(sin(i*0.01)*0.1,0,0.1,2,0.05)
	check(normal.score < 20,"synthetic smooth trace remains normal")
	var snap = Detector.new()
	for i in range(8): snap.observe(0.6 if i%2 else -0.6,0,0.0001,2,0.05)
	check(snap.score >= 75,"repeated precise snaps accumulate suspicion")
	var single = Detector.new()
	single.observe(0,0,0.2,2,0.05)
	single.observe(0.6,0,0,2,0.05)
	check(single.score < 45,"single anomaly is not detection")
	var occluded = Detector.new()
	for i in range(8): occluded.observe(0.6 if i%2 else -0.6,0,0,0,0.05)
	check(occluded.score == 0,"no visible target means no snap evidence")
	var net = Network.new()
	root.add_child(net)
	var settings = ConfigFile.new()
	settings.load("res://server.cfg")
	settings.set_value("match","max_players",9)
	settings.save("user://invalid-server.cfg")
	check(not net.configure("user://invalid-server.cfg"),"invalid player limit rejected")
	settings.set_value("match","max_players",8)
	settings.set_value("anticheat","action","KICK")
	settings.save("user://invalid-server.cfg")
	check(not net.configure("user://invalid-server.cfg"),"unimplemented policy action rejected")
	settings.set_value("anticheat","action","WARN")
	settings.set_value("anticheat","threshold",101)
	settings.save("user://invalid-server.cfg")
	check(not net.configure("user://invalid-server.cfg"),"invalid threshold rejected")
	settings.set_value("anticheat","threshold",75.0)
	settings.set_value("match","duration_seconds",10)
	settings.save("user://invalid-server.cfg")
	check(net.configure("user://invalid-server.cfg"),"valid external configuration accepted")
	check(net.config.get_value("match","duration_seconds") == 10,"external match duration applied")
	check(net.host(0,true) == ERR_INVALID_PARAMETER,"invalid port rejected before socket")
	net.configure("res://server.cfg")
	DirAccess.remove_absolute(ProjectSettings.globalize_path("user://invalid-server.cfg"))
	net.world = arena
	net.server_mode = true
	net.phase = "IN_MATCH"
	net.session = "test-session"
	net.members[2] = {"name":"Test"}
	net.pawns[2] = pawn
	net.set_physics_process(false)
	net.accept_intent(2,"wrong",1,Vector2.ZERO,0,0,false,false,false)
	check(not net.inputs.has(2),"wrong session rejected")
	net.accept_intent(3,"test-session",1,Vector2.ZERO,0,0,false,false,false)
	check(not net.inputs.has(3),"unknown transport peer rejected")
	net.accept_intent(2,"test-session",1,Vector2(2,0),0,0,false,false,false)
	check(not net.inputs.has(2),"speed input rejected")
	net.accept_intent(2,"test-session",1,Vector2.ZERO,NAN,0,false,false,false)
	check(not net.inputs.has(2),"NaN rejected")
	net.accept_intent(2,"test-session",1,Vector2.ZERO,0,2,false,false,false)
	check(not net.inputs.has(2),"pitch bounds rejected")
	net.accept_intent(2,"test-session",1,Vector2.ZERO,0,0,false,false,false)
	check(net.last_sequence[2] == 1,"valid intent accepted after rejections")
	net.accept_intent(2,"test-session",2,Vector2(1,0),0,0,false,false,false)
	check(net.last_sequence[2] == 1,"same tick burst does not consume sequence")
	net.tick += 1
	net.accept_intent(2,"test-session",1,Vector2(1,0),0,0,false,false,false)
	check(net.inputs[2].move == Vector2.ZERO,"replay rejected")
	net.accept_intent(2,"test-session",2,Vector2(1,0),0,0,false,false,false)
	check(net.last_sequence[2] == 2,"next tick accepts unconsumed sequence")
	net.pawns.clear()
	net.queue_free()
	print(JSON.stringify({"suite":"arena-rules","checks":checks,"failures":failures,"scope":"physics and synthetic detector fixtures, not human FP measurements"}))
	arena.queue_free()
	quit(1 if failures else 0)
