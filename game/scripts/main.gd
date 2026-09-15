extends Node
const Arena = preload("res://scripts/arena.gd")
const Network = preload("res://scripts/network.gd")
const Interface = preload("res://scripts/interface.gd")
const LabAim = preload("res://scripts/lab_aim.gd")
var net: Node
var ui: CanvasLayer
var arena: Node3D
var overview: Camera3D
var lab = LabAim.new()
var yaw = 0.0
var pitch = 0.0
var sensitivity = 0.002
var hosted_pid = -1
var headless = false
var automated = false
var automated_left = 15.0
var auto_ready = false
var auto_join = ""
var smoke_path = ""
var alert_capture = ""
var smoke_elapsed = 0.0
var ground_truth: FileAccess
var truth_binding = ""
var beep: AudioStreamPlayer
var exiting = false

func _ready() -> void:
	get_tree().auto_accept_quit = false
	var raw_args = OS.get_cmdline_user_args()
	for flag in ["--port","--name","--join","--seconds","--screenshot","--alert-screenshot","--config"]:
		var index = raw_args.find(flag)
		if index >= 0 and (index+1 >= raw_args.size() or raw_args[index+1].begins_with("--")):
			printerr("Missing value: ",flag)
			get_tree().quit(2)
			return
	arena = Arena.new()
	add_child(arena)
	overview = Camera3D.new()
	arena.add_child(overview)
	overview.position = Vector3(22,20,22)
	overview.look_at(Vector3.ZERO)
	overview.current = true
	net = Network.new()
	net.name = "Network"
	net.world = arena
	add_child(net)
	var args = OS.get_cmdline_user_args()
	headless = "--server" in args
	automated = "--automated" in args
	if "--seconds" in args: automated_left = float(args[args.find("--seconds")+1])
	if "--alert-screenshot" in args: alert_capture = args[args.find("--alert-screenshot")+1]
	if "--screenshot" in args: smoke_path = args[args.find("--screenshot")+1]
	var port = 7777
	if "--port" in args: port = int(args[args.find("--port")+1])
	if headless:
		var error = net.host(port,"--development" in args)
		if error != OK:
			printerr("SERVER_REFUSED: ",error_string(error)," ",net.config_error,"; requiere --development, puerto libre y configuración válida")
			get_tree().quit(2)
		else: print(JSON.stringify({"event":"server_ready","port":port,"profile":"development_unattested"}))
		return
	ui = Interface.new()
	ui.capture_input = not automated
	add_child(ui)
	sensitivity = ui.sensitivity
	ui.connect_requested.connect(connect_game)
	ui.host_requested.connect(host_game)
	ui.ready_requested.connect(net.ready_player)
	ui.quit_requested.connect(func(): quit_game(0))
	ui.leave_requested.connect(func(): net.stop(""); stop_host(); overview.current=true; ui.main_menu())
	ui.reacquisition_changed.connect(func(value): lab.reacquisition=value; set_lab(lab.enabled))
	ui.lab_changed.connect(func(value): set_lab(value))
	ui.settings_changed.connect(func(value): sensitivity=value)
	net.changed.connect(state_changed)
	net.notice.connect(func(message):
		ui.show_notice(message)
		if message.begins_with("ANTICHEAT") and not alert_capture.is_empty():
			smoke_path = alert_capture
			smoke_elapsed = 3
			alert_capture = ""
		if automated: print(JSON.stringify({"event":"client_notice","message":message})))
	net.shot.connect(shot_feedback)
	make_audio()
	if "--join" in args:
		auto_join = args[args.find("--join")+1]
		var nickname = "Player"
		if "--name" in args: nickname=args[args.find("--name")+1]
		connect_game(auto_join,port,nickname)
	if "--snap-cycle" in args:
		lab.reacquisition = true
		ui.reacquisition = true
	if "--lab" in args: set_lab(true)

func connect_game(address: String, port: int, nickname: String) -> void:
	var error = net.join_server(address,port,nickname)
	if error != OK: ui.show_notice("Error de conexión: "+error_string(error))

func host_game(port: int) -> void:
	stop_host()
	var args = ["--headless","--path",ProjectSettings.globalize_path("res://"),"--","--server","--development","--port",str(port)]
	var original = OS.get_cmdline_user_args()
	if "--config" in original: args.append_array(["--config",original[original.find("--config")+1]])
	hosted_pid = OS.create_process(OS.get_executable_path(),args)
	if hosted_pid <= 0:
		ui.show_notice("No se pudo iniciar el servidor dedicado")
		return
	await get_tree().create_timer(0.8).timeout
	if not OS.is_process_running(hosted_pid):
		hosted_pid = -1
		ui.show_notice("El servidor no arrancó: comprueba puerto y configuración")
		return
	connect_game("127.0.0.1",port,ui.nickname)

func state_changed() -> void:
	if not ui: return
	match net.phase:
		"DISCONNECTED":
			overview.current = true
			ui.main_menu()
		"CONNECTING","CONNECTED": ui.connection_screen(net.phase)
		"LOBBY","RESULTS": ui.lobby(net.phase)
		"IN_MATCH": ui.match_screen()

func _input(event: InputEvent) -> void:
	if headless: return
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_F11: ui.toggle_fullscreen()
		if event.keycode == KEY_F8 and net.development: set_lab(not lab.enabled)
		if event.keycode == KEY_ESCAPE and net.phase == "IN_MATCH":
			if ui.current_screen == "PAUSE": ui.match_screen()
			else: ui.pause_menu()
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		yaw = wrapf(yaw-event.relative.x*sensitivity,-PI,PI)
		pitch = clampf(pitch-event.relative.y*sensitivity,-1.5,1.5)

func _physics_process(delta: float) -> void:
	if headless: return
	if automated and net.phase == "LOBBY" and not auto_ready:
		auto_ready = true
		net.ready_player()
	if net.phase != "IN_MATCH" or not net.pawns.has(net.own_id): return
	var pawn = net.pawns[net.own_id]
	var movement = Vector2.ZERO
	var jump = false
	var fire = false
	var reload = false
	if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		movement = Vector2(float(Input.is_physical_key_pressed(KEY_D))-float(Input.is_physical_key_pressed(KEY_A)),float(Input.is_physical_key_pressed(KEY_S))-float(Input.is_physical_key_pressed(KEY_W))).limit_length()
		jump = Input.is_physical_key_pressed(KEY_SPACE)
		fire = Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT)
		reload = Input.is_physical_key_pressed(KEY_R)
	if automated:
		var world_move = Vector3(clampf(-13.0-pawn.position.x,-1,1),0,0)
		var local_move = Basis(Vector3.UP,-yaw)*world_move
		movement = Vector2(local_move.x,local_move.z).limit_length()
		fire = true
		reload = pawn.ammo == 0
	if lab.enabled and net.development:
		var direction = lab.direction(pawn,net.pawns,net.own_id)
		yaw = direction.x
		pitch = direction.y
	pawn.aim(yaw,pitch)
	net.send_input(movement,yaw,pitch,jump,fire,reload)

func _process(delta: float) -> void:
	if automated:
		automated_left -= delta
		if automated_left <= 0:
			print(JSON.stringify({"event":"automated_exit","phase":net.phase,"players":net.members.size(),"snapshots":net.snapshots.size(),"profile":"development_unattested","own_state":net.pawns[net.own_id].pack() if net.pawns.has(net.own_id) else {}}))
			quit_game(0 if net.phase == "IN_MATCH" else 3)
			return
	if headless: return
	for id in net.snapshots:
		if net.pawns.has(id): net.pawns[id].unpack(net.snapshots[id],id == net.own_id,delta)
	if net.pawns.has(net.own_id) and net.phase == "IN_MATCH": net.pawns[net.own_id].camera.current = true
	ui.update_game(net,lab.enabled)
	if net.phase == "IN_MATCH" and truth_binding != net.session+str(net.own_id):
		truth_binding = net.session+str(net.own_id)
		set_lab(lab.enabled)
	if not smoke_path.is_empty():
		smoke_elapsed += delta
		if smoke_elapsed > 3:
			await RenderingServer.frame_post_draw
			var error = get_viewport().get_texture().get_image().save_png(smoke_path)
			print("SCREENSHOT_RESULT ",error)
			smoke_path = ""

func set_lab(value: bool) -> void:
	lab.enabled = value
	if ui: ui.simulation = value
	if not ground_truth:
		ground_truth = FileAccess.open("user://ground-truth-"+str(OS.get_process_id())+".jsonl",FileAccess.WRITE)
	if ground_truth:
		# Stored on CLIENT only; never transmitted to the detector.
		ground_truth.store_line(JSON.stringify({"schema":"arena-ground-truth/1","client_ms":Time.get_ticks_msec(),"observed_server_tick":net.server_tick,"session":net.session,"player":net.own_id,"enabled":value,"reacquisition":lab.reacquisition}))
		ground_truth.flush()

func make_audio() -> void:
	beep = AudioStreamPlayer.new()
	var stream = AudioStreamWAV.new()
	stream.format = AudioStreamWAV.FORMAT_16_BITS
	stream.mix_rate = 22050
	var data = PackedByteArray()
	data.resize(2205*2)
	for i in range(2205):
		var value = int(sin(i*0.17)*10000*exp(-float(i)/350))
		data.encode_s16(i*2,value)
	stream.data = data
	beep.stream = stream
	beep.volume_db = -14
	add_child(beep)

func shot_feedback(shooter: int, victim: int) -> void:
	if shooter == net.own_id:
		beep.play()
		if victim != 0: ui.show_notice("HIT +25")
	if victim == net.own_id: ui.show_notice("DAMAGE −25")

func stop_host() -> void:
	if hosted_pid > 0 and OS.is_process_running(hosted_pid): OS.kill(hosted_pid)
	hosted_pid = -1

func _exit_tree() -> void:
	stop_host()
	if ground_truth: ground_truth.close()

func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST: quit_game(0)

func quit_game(code: int) -> void:
	if exiting: return
	exiting = true
	set_process(false)
	set_physics_process(false)
	if net:
		net.set_physics_process(false)
		net.stop("")
	if is_instance_valid(beep):
		beep.stop()
		beep.stream = null
	# Let the audio mixer release active playback references before teardown.
	await get_tree().create_timer(0.15).timeout
	get_tree().quit(code)
