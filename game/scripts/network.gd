extends Node
## ENet transports intentions only. Peer identity always comes from the transport.
signal changed
signal notice(message: String)
signal shot(shooter: int, victim: int)
const Pawn = preload("res://scripts/pawn.gd")
const Arena = preload("res://scripts/arena.gd")
const Detector = preload("res://scripts/aim_detector.gd")
const Admission = preload("res://scripts/admission_boundary.gd")
const Transport = preload("res://scripts/enet_transport.gd")
const VERSION = 1
var admission = Admission.new()
var transport: Transport
var world: Node3D
var pawns: Dictionary = {}
var members: Dictionary = {}
var inputs: Dictionary = {}
var detectors: Dictionary = {}
var snapshots: Dictionary = {}
var session = ""
var phase = "DISCONNECTED"
var development = false
var server_mode = false
var tick = 0
var server_tick = 0
var match_left = 300.0
var snapshot_elapsed = 0.0
var config = ConfigFile.new()
var config_error = ""
var player_name = "Player"
var sequence = 0
var own_id = 0
var log_file: FileAccess
var log_lines = 0
var log_flush_tick = 0
var tick_us = 0
var detector_us = 0
var ping_ms = 0
var ping_at = 0
var last_packet_at = 0
var telemetry_elapsed = 0.0

func _ready() -> void:
	transport = Transport.new(multiplayer)
	var args = OS.get_cmdline_user_args()
	var path = "res://server.cfg"
	var index = args.find("--config")
	if index >= 0 and index+1 < args.size(): path = args[index+1]
	configure(path)
	multiplayer.peer_connected.connect(_peer_connected)
	multiplayer.peer_disconnected.connect(_peer_disconnected)
	multiplayer.connected_to_server.connect(_connected)
	multiplayer.connection_failed.connect(func(): stop("No se pudo conectar al servidor"))
	multiplayer.server_disconnected.connect(func(): stop("Conexión perdida con el servidor"))

func configure(path: String) -> bool:
	config = ConfigFile.new()
	config_error = ""
	if config.load(path) != OK:
		config_error = "No se pudo leer la configuración del servidor"
		return false
	for rule in [["tick_rate",20,120],["snapshot_rate",10,60],["max_players",2,8],["duration_seconds",10,3600],["frag_limit",1,100]]:
		var value = config.get_value("match",rule[0],null)
		if not value is int or value < rule[1] or value > rule[2]:
			config_error = "Valor inválido: match/"+rule[0]
			return false
	var threshold = config.get_value("anticheat","threshold",null)
	if not (threshold is int or threshold is float) or not is_finite(threshold) or threshold < 1 or threshold > 100:
		config_error = "Umbral anticheat inválido"
		return false
	if config.get_value("anticheat","action","") not in ["LOG_ONLY","WARN"]:
		config_error = "Acción anticheat no implementada; usa LOG_ONLY o WARN"
		return false
	Engine.physics_ticks_per_second = config.get_value("match","tick_rate",60)
	return true

func host(port: int, dev: bool) -> Error:
	if not config_error.is_empty():
		notice.emit(config_error)
		return ERR_INVALID_DATA
	if port < 1024 or port > 65535: return ERR_INVALID_PARAMETER
	if Admission.profile_error(dev) != OK:
		notice.emit(Admission.PROTECTED_NOTICE)
		return ERR_UNAVAILABLE
	stop("")
	var random_session = Crypto.new().generate_random_bytes(16)
	if random_session.size() != 16: return ERR_UNAVAILABLE
	var error = transport.listen(port,clampi(int(config.get_value("match","max_players",8)),2,8))
	if error != OK: return error
	server_mode = true
	development = dev
	phase = "LOBBY"
	session = random_session.hex_encode()
	log_file = FileAccess.open("user://server-session-"+session+".jsonl",FileAccess.WRITE)
	changed.emit()
	return OK

func join_server(address: String, port: int, nickname: String) -> Error:
	stop("")
	player_name = nickname.strip_edges().substr(0,24)
	if player_name.is_empty(): player_name = "Player"
	var error = transport.connect_to(address,port)
	if error != OK: return error
	phase = "CONNECTING"
	last_packet_at = Time.get_ticks_msec()
	changed.emit()
	return OK

func stop(message: String) -> void:
	transport.close()
	for pawn in pawns.values(): pawn.queue_free()
	pawns.clear()
	members.clear()
	inputs.clear()
	detectors.clear()
	admission.clear()
	snapshots.clear()
	server_mode = false
	development = false
	phase = "DISCONNECTED"
	session = ""
	sequence = 0
	own_id = 0
	tick = 0
	server_tick = 0
	snapshot_elapsed = 0
	telemetry_elapsed = 0
	log_lines = 0
	log_flush_tick = 0
	if log_file: log_file.close()
	log_file = null
	if not message.is_empty(): notice.emit(message)
	changed.emit()

func _peer_connected(id: int) -> void:
	if server_mode: admission.connected(id,Time.get_ticks_msec())

func _peer_disconnected(id: int) -> void:
	admission.disconnected(id)
	members.erase(id)
	inputs.erase(id)
	detectors.erase(id)
	if pawns.has(id):
		pawns[id].queue_free()
		pawns.erase(id)
	if server_mode: publish()

func _connected() -> void:
	own_id = transport.unique_id()
	phase = "CONNECTED"
	hello.rpc_id(1,VERSION,player_name)

@rpc("any_peer","call_remote","reliable",0)
func hello(version: int, nickname: String) -> void:
	if not server_mode: return
	var id = transport.remote_sender_id()
	match admission.hello(id,version,VERSION,nickname,development,phase,members):
		Admission.Hello.DISCONNECT:
			transport.disconnect_peer(id)
			return
		Admission.Hello.IN_MATCH:
			rejected.rpc_id(id,"Partida en curso; vuelve a conectar al terminar")
			return
		Admission.Hello.DUPLICATE_NAME:
			rejected.rpc_id(id,"Nombre ya utilizado")
			return
		Admission.Hello.ACCEPT: pass
		_: return
	members[id] = {"name":nickname,"attestation":"NOT_ATTESTED_DEV","ready":false,"ping":0,"score":0.0,"state":"NORMAL"}
	detectors[id] = Detector.new()
	welcome.rpc_id(id,session,development)
	publish()

@rpc("authority","call_remote","reliable",0)
func rejected(reason: String) -> void:
	stop(reason)

@rpc("authority","call_remote","reliable",0)
func welcome(value: String, dev: bool) -> void:
	session = value
	development = dev
	phase = "LOBBY"
	last_packet_at = Time.get_ticks_msec()
	changed.emit()

func ready_player() -> void:
	if phase in ["LOBBY","RESULTS"]: ready_request.rpc_id(1,session)

@rpc("any_peer","call_remote","reliable",0)
func ready_request(value: String) -> void:
	var id = transport.remote_sender_id()
	if not server_mode or not admission.permits(id,value,session) or not members.has(id) or phase not in ["LOBBY","RESULTS"]: return
	members[id].ready = true
	var all_ready = true
	for member in members.values(): all_ready = all_ready and member.ready
	if all_ready and members.size() >= 2:
		phase = "IN_MATCH"
		match_left = float(config.get_value("match","duration_seconds",300))
		for player in members:
			if not pawns.has(player): spawn(player)
			pawns[player].kills = 0
			pawns[player].deaths = 0
			respawn(player)
	publish()

func spawn(id: int) -> void:
	var pawn = Pawn.new()
	pawn.name = "Player_"+str(id)
	world.add_child(pawn)
	pawns[id] = pawn

func respawn(id: int) -> void:
	var pawn = pawns[id]
	# Select the spawn farthest from living opponents.
	var best = Arena.SPAWNS[0]
	var distance = -1.0
	for point in Arena.SPAWNS:
		var nearest = 1000.0
		for other in pawns:
			if other != id and pawns[other].health > 0:
				nearest = minf(nearest,point.distance_to(pawns[other].position))
		if nearest > distance:
			distance = nearest
			best = point
	pawn.position = best
	pawn.velocity = Vector3.ZERO
	pawn.health = 100
	pawn.collision_layer = 1
	pawn.ammo = 12
	pawn.reload_time = 0
	pawn.cooldown = 0
	pawn.respawn_time = 0
	inputs.erase(id)

func send_input(move: Vector2, yaw: float, pitch: float, jump: bool, fire: bool, reload: bool) -> void:
	if phase != "IN_MATCH" or session.is_empty(): return
	sequence += 1
	intent.rpc_id(1,session,sequence,move,yaw,pitch,jump,fire,reload)

@rpc("any_peer","call_remote","unreliable_ordered",1)
func intent(value: String, seq: int, move: Vector2, yaw: float, pitch: float, jump: bool, fire: bool, reload: bool) -> void:
	accept_intent(transport.remote_sender_id(),value,seq,move,yaw,pitch,jump,fire,reload)

func accept_intent(id: int, value: String, seq: int, move: Vector2, yaw: float, pitch: float, jump: bool, fire: bool, reload: bool) -> void:
	if not server_mode or phase != "IN_MATCH": return
	if not admission.permits(id,value,session) or not pawns.has(id) or not members.has(id): return
	var context = admission.connection(id)
	if seq <= context.last_sequence or seq > 2147483647: return
	if not move.is_finite() or move.length_squared() > 1.001 or not is_finite(yaw) or not is_finite(pitch): return
	if absf(yaw) > PI or absf(pitch) > 1.5: return
	# At most one accepted input per server tick. A rejection consumes no sequence.
	if context.last_input_tick == tick: return
	context.last_sequence = seq
	context.last_input_tick = tick
	inputs[id] = {"move":move,"yaw":yaw,"pitch":pitch,"jump":jump,"fire":fire,"reload":reload,"at":tick}

func _physics_process(delta: float) -> void:
	if not server_mode:
		if phase != "DISCONNECTED" and Time.get_ticks_msec()-last_packet_at > 8000:
			stop("Tiempo de espera de conexión agotado")
		return
	var started = Time.get_ticks_usec()
	tick += 1
	for id in admission.expired_handshakes(Time.get_ticks_msec()):
		transport.disconnect_peer(id)
		admission.disconnected(id)
	if phase == "IN_MATCH":
		match_left = maxf(0,match_left-delta)
		for id in pawns:
			var pawn = pawns[id]
			if pawn.health <= 0:
				pawn.respawn_time -= delta
				if pawn.respawn_time <= 0: respawn(id)
				continue
			var input: Dictionary = inputs.get(id,{})
			if tick-input.get("at",-9999) > Engine.physics_ticks_per_second/4: input = {}
			pawn.simulate(delta,input)
			if input.get("fire",false) and pawn.can_fire(): fire_weapon(id)
			if phase != "IN_MATCH": break
			if not input.is_empty():
				input.jump = false
				input.reload = false
			if pawn.position.y < -10: damage(id,id,100)
		if match_left <= 0:
			finish_match()
		telemetry_elapsed += delta
		if telemetry_elapsed >= 1.0/20:
			var detector_started = Time.get_ticks_usec()
			for id in pawns: observe(id,telemetry_elapsed)
			detector_us = Time.get_ticks_usec()-detector_started
			telemetry_elapsed = 0
	snapshot_elapsed += delta
	if snapshot_elapsed >= 1.0/clampf(float(config.get_value("match","snapshot_rate",20)),10,60):
		snapshot_elapsed = 0
		publish()
	tick_us = Time.get_ticks_usec()-started

func fire_weapon(id: int) -> void:
	var pawn = pawns[id]
	pawn.ammo -= 1
	pawn.cooldown = 0.18
	var origin: Vector3 = pawn.position+Vector3.UP*1.55
	var direction: Vector3 = -pawn.camera.global_basis.z
	var query = PhysicsRayQueryParameters3D.create(origin,origin+direction*80)
	query.exclude = [pawn.get_rid()]
	var hit = world.get_world_3d().direct_space_state.intersect_ray(query)
	var victim = 0
	if not hit.is_empty():
		for other in pawns:
			if hit.collider == pawns[other] and pawns[other].health > 0:
				victim = other
				damage(id,other,25)
	shot_event.rpc(id,victim)

func damage(attacker: int, victim: int, amount: int) -> void:
	var pawn = pawns[victim]
	if pawn.health <= 0: return
	pawn.health = maxi(0,pawn.health-amount)
	if pawn.health == 0:
		pawn.collision_layer = 0
		pawn.deaths += 1
		pawn.respawn_time = 3
		if attacker != victim: pawns[attacker].kills += 1
		announcement.rpc(members[attacker].name+" → "+members[victim].name)
		if pawns[attacker].kills >= int(config.get_value("match","frag_limit",15)): finish_match()

func finish_match() -> void:
	phase = "RESULTS"
	for member in members.values(): member.ready = false
	inputs.clear()
	publish()

func observe(id: int, delta: float) -> void:
	var pawn = pawns[id]
	if pawn.health <= 0: return
	var error = PI
	var target = 0
	var origin: Vector3 = pawn.position+Vector3.UP*1.55
	for other in pawns:
		if other == id or pawns[other].health <= 0: continue
		var destination: Vector3 = pawns[other].position+Vector3.UP*1.55
		var angle = (-pawn.camera.global_basis.z).angle_to((destination-origin).normalized())
		if angle >= error: continue
		var query = PhysicsRayQueryParameters3D.create(origin,destination)
		query.exclude = [pawn.get_rid()]
		var hit = world.get_world_3d().direct_space_state.intersect_ray(query)
		if not hit.is_empty() and hit.collider == pawns[other]:
			error = angle
			target = other
	var evidence: Dictionary = detectors[id].observe(pawn.yaw,pawn.pitch,error,target,delta)
	members[id].score = evidence.score
	members[id].state = evidence.state
	if log_file and log_lines < 200000:
		log_lines += 1
		log_file.store_line(JSON.stringify({"schema":"arena-observation/1","server_ms":Time.get_ticks_msec(),"tick":tick,"session":session,"player":id,"yaw":pawn.yaw,"pitch":pawn.pitch,"error":error,"visible_target":target,"delta":delta,"evidence":evidence,"tick_us":tick_us,"detector_us":detector_us}))
	if evidence.score >= float(config.get_value("anticheat","threshold",75)) and not detectors[id].alert_sent:
		detectors[id].alert_sent = true
		var action = str(config.get_value("anticheat","action","WARN"))
		# Only non-punitive actions until false positives are measured.
		if action == "WARN": announcement.rpc("ANTICHEAT · Suspicious aim behaviour: "+members[id].name)
		if log_file:
			log_file.store_line(JSON.stringify({"event":"ANTICHEAT_ALERT","server_ms":Time.get_ticks_msec(),"tick":tick,"session":session,"player":id,"detector":"aim-v1","score":evidence.score,"evidence":evidence,"action":action}))
			log_file.flush()

func publish() -> void:
	if log_file and tick-log_flush_tick >= Engine.physics_ticks_per_second:
		log_file.flush()
		log_flush_tick = tick
	var values = {}
	for id in pawns: values[id] = pawns[id].pack()
	snapshot.rpc(session,phase,members,values,match_left,tick_us,detector_us,tick)
	changed.emit()

@rpc("authority","call_remote","unreliable_ordered",2)
func snapshot(value: String, state: String, roster: Dictionary, values: Dictionary, remaining: float, tick_cost: int, detector_cost: int, authoritative_tick: int) -> void:
	if value != session or session.is_empty(): return
	last_packet_at = Time.get_ticks_msec()
	var old_phase = phase
	phase = state
	members = roster
	snapshots = values
	match_left = remaining
	server_tick = authoritative_tick
	tick_us = tick_cost
	detector_us = detector_cost
	for id in values:
		if not pawns.has(id): spawn(id)
	for id in pawns.keys():
		if not values.has(id):
			pawns[id].queue_free()
			pawns.erase(id)
	if old_phase != phase: changed.emit()
	if Time.get_ticks_msec()-ping_at >= 1000:
		ping_at = Time.get_ticks_msec()
		ping_request.rpc_id(1,ping_at)

@rpc("any_peer","call_remote","unreliable",3)
func ping_request(stamp: int) -> void:
	var id = transport.remote_sender_id()
	if server_mode and admission.admitted(id) and members.has(id): pong.rpc_id(id,stamp)

@rpc("authority","call_remote","unreliable",3)
func pong(stamp: int) -> void:
	if stamp == ping_at: ping_ms = Time.get_ticks_msec()-stamp

@rpc("authority","call_remote","reliable",0)
func announcement(message: String) -> void:
	notice.emit(message)

@rpc("authority","call_remote","unreliable",2)
func shot_event(shooter: int, victim: int) -> void:
	shot.emit(shooter,victim)

func _exit_tree() -> void:
	if transport: transport.close()
	admission.clear()
	if log_file: log_file.close()
