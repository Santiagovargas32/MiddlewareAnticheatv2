extends CanvasLayer
signal connect_requested(ip: String, port: int, nickname: String)
signal host_requested(port: int)
signal ready_requested
signal leave_requested
signal quit_requested
signal lab_changed(enabled: bool)
signal reacquisition_changed(enabled: bool)
signal settings_changed(sensitivity: float)
var capture_input = true
var root: Control
var panel: PanelContainer
var content: VBoxContainer
var status: Label
var hud: Label
var score: Label
var crosshair: Label
var toast: Label
var toast_left = 0.0
var current_screen = ""
var ip = "127.0.0.1"
var port = 7777
var nickname = "Player"
var sensitivity = 0.002
var simulation = false
var reacquisition = false
var settings = ConfigFile.new()

func _ready() -> void:
	settings.load("user://settings.cfg")
	ip = settings.get_value("client","ip",ip)
	nickname = settings.get_value("client","name",nickname)
	sensitivity = float(settings.get_value("client","sensitivity",sensitivity))
	root = Control.new()
	root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(root)
	var theme = Theme.new()
	theme.default_font_size = 26
	for kind in ["normal","hover","pressed","focus"]:
		var style = StyleBoxFlat.new()
		style.bg_color = Color("1b3047") if kind == "normal" else Color("2b5970")
		style.set_corner_radius_all(8)
		style.content_margin_left = 22
		style.content_margin_right = 22
		style.content_margin_top = 12
		style.content_margin_bottom = 12
		theme.set_stylebox(kind,"Button",style)
	var bg = StyleBoxFlat.new()
	bg.bg_color = Color(0.025,0.045,0.075,0.97)
	bg.set_corner_radius_all(16)
	bg.content_margin_left = 40
	bg.content_margin_right = 40
	bg.content_margin_top = 30
	bg.content_margin_bottom = 30
	theme.set_stylebox("panel","PanelContainer",bg)
	root.theme = theme
	panel = PanelContainer.new()
	panel.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	panel.position = Vector2(-390,-440)
	panel.custom_minimum_size = Vector2(780,0)
	root.add_child(panel)
	content = VBoxContainer.new()
	content.add_theme_constant_override("separation",14)
	panel.add_child(content)
	hud = label("",30)
	hud.position = Vector2(35,30)
	root.add_child(hud)
	score = label("",28)
	score.position = Vector2(520,250)
	root.add_child(score)
	crosshair = label("+",38)
	crosshair.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	crosshair.position = Vector2(-10,-26)
	root.add_child(crosshair)
	toast = label("",27)
	toast.position = Vector2(35,900)
	toast.add_theme_color_override("font_color",Color("ffd28a"))
	root.add_child(toast)
	main_menu()

func label(text: String, size: int = 26) -> Label:
	var node = Label.new()
	node.text = text
	node.add_theme_font_size_override("font_size",size)
	node.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return node

func clear(title: String) -> void:
	for child in content.get_children():
		content.remove_child(child)
		child.queue_free()
	panel.show()
	crosshair.hide()
	score.hide()
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	content.add_child(label("MIDDLEWARE / ARENA LAB",20))
	content.add_child(label(title,42))

func button(text: String, callback: Callable) -> void:
	var node = Button.new()
	node.text = text
	node.pressed.connect(callback)
	content.add_child(node)

func main_menu() -> void:
	current_screen = "MAIN"
	clear("Linux Multiplayer FPS")
	content.add_child(label("Experimental · FFA · LAN",22))
	button("PLAY",join_menu)
	button("HOST GAME",host_menu)
	button("JOIN GAME",join_menu)
	button("ANTICHEAT LAB",lab_menu)
	button("SETTINGS",settings_menu)
	button("ABOUT PROJECT",about_menu)
	button("QUIT",func(): quit_requested.emit())

func field(title: String, value: String) -> LineEdit:
	content.add_child(label(title,22))
	var node = LineEdit.new()
	node.text = value
	content.add_child(node)
	return node

func join_menu() -> void:
	current_screen = "JOIN"
	clear("Join game")
	var address = field("IP",ip)
	var number = field("PORT",str(port))
	var player = field("PLAYER NAME · letras, números y _",nickname)
	player.max_length = 24
	button("CONNECT",func():
		if not address.text.is_valid_ip_address() or not number.text.is_valid_int() or int(number.text) < 1024 or int(number.text) > 65535 or not player.text.is_valid_identifier():
			show_notice("IP, puerto (1024–65535) o nombre inválido")
			return
		ip = address.text
		port = int(number.text)
		nickname = player.text
		save_settings()
		connect_requested.emit(ip,port,nickname))
	button("BACK",main_menu)

func host_menu() -> void:
	current_screen = "HOST"
	clear("Host game · desarrollo")
	content.add_child(label("Sin atestación TPM. No es una partida protegida.",22))
	var number = field("PORT",str(port))
	button("START DEVELOPMENT SERVER",func():
		if number.text.is_valid_int() and int(number.text) >= 1024 and int(number.text) <= 65535:
			port = int(number.text)
			host_requested.emit(port)
		else: show_notice("Puerto inválido"))
	button("BACK",main_menu)

func lab_menu() -> void:
	current_screen = "LAB"
	clear("Anticheat Lab")
	content.add_child(label("Simulación interna de nuestro juego. F8 en partida.",22))
	content.add_child(label("El detector sólo observa comportamiento.",22))
	var toggle = CheckButton.new()
	toggle.text = "Aim assist simulation / snap + tracking"
	toggle.button_pressed = simulation
	toggle.toggled.connect(func(value): simulation=value; lab_changed.emit(value))
	content.add_child(toggle)
	var cycle = CheckButton.new()
	cycle.text = "Repeated target acquisition simulation"
	cycle.button_pressed = reacquisition
	cycle.toggled.connect(func(value): reacquisition=value; reacquisition_changed.emit(value))
	content.add_child(cycle)
	button("BACK",main_menu)

func settings_menu() -> void:
	current_screen = "SETTINGS"
	clear("Settings")
	content.add_child(label("Mouse sensitivity",24))
	var slider = HSlider.new()
	slider.min_value = 0.0005
	slider.max_value = 0.006
	slider.step = 0.0001
	slider.value = sensitivity
	slider.value_changed.connect(func(value): sensitivity=value; settings_changed.emit(value); save_settings())
	content.add_child(slider)
	button("FULLSCREEN / WINDOW · F11",toggle_fullscreen)
	button("BACK",main_menu)

func toggle_fullscreen() -> void:
	var full = DisplayServer.window_get_mode() == DisplayServer.WINDOW_MODE_FULLSCREEN
	DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_WINDOWED if full else DisplayServer.WINDOW_MODE_FULLSCREEN)

func about_menu() -> void:
	current_screen = "ABOUT"
	clear("About project")
	content.add_child(label("Linux FPS + autoridad del servidor + investigación",22))
	content.add_child(label("TPM/IMA ≠ ausencia de cheats",24))
	content.add_child(label("Geometría original · Godot Engine (MIT)",22))
	content.add_child(label("Detección experimental, sin precisión validada aún.",22))
	button("BACK",main_menu)

func connection_screen(state: String) -> void:
	current_screen = state
	clear(state)
	status = label("Conectando…",24)
	content.add_child(status)
	button("DISCONNECT",func(): leave_requested.emit())

func lobby(state: String) -> void:
	current_screen = state
	clear("Match results" if state == "RESULTS" else "Lobby")
	content.add_child(label("DEVELOPMENT · NOT ATTESTED",23))
	status = label("",24)
	content.add_child(status)
	button("READY / NEXT MATCH",func(): ready_requested.emit())
	button("DISCONNECT",func(): leave_requested.emit())

func match_screen() -> void:
	current_screen = "IN_MATCH"
	panel.hide()
	crosshair.show()
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED if capture_input else Input.MOUSE_MODE_VISIBLE

func pause_menu() -> void:
	current_screen = "PAUSE"
	clear("Paused input · la partida continúa")
	button("RESUME",match_screen)
	button("DISCONNECT",func(): leave_requested.emit())

func update_game(net: Node, lab_on: bool) -> void:
	var text = "PLAYER                       ATTESTATION          READY\n"
	var table = "PLAYER           KILLS   DEATHS   PING     AIM SCORE\n"
	for id in net.members:
		var member = net.members[id]
		text += "%s     %s     %s\n" % [member.name,member.attestation,"YES" if member.ready else "NO"]
		var pawn = net.pawns.get(id)
		table += "%s       %d       %d       %s      %.0f\n" % [member.name,pawn.kills if pawn else 0,pawn.deaths if pawn else 0,str(net.ping_ms)+"ms" if id == net.own_id else "—",member.score]
	if current_screen in ["LOBBY","RESULTS"] and is_instance_valid(status):
		status.text = text + ("\n"+table if current_screen == "RESULTS" else "\nSe necesitan al menos 2 jugadores READY.")
	score.text = table
	score.visible = net.phase == "IN_MATCH" and Input.is_physical_key_pressed(KEY_TAB)
	var me = net.pawns.get(net.own_id)
	hud.visible = net.phase == "IN_MATCH"
	if me:
		var suspicion = net.members.get(net.own_id,{}).get("score",0)
		hud.text = "HEALTH %d     AMMO %d / 12     KILLS %d     %02d:%02d\n" % [me.health,me.ammo,me.kills,int(net.match_left)/60,int(net.match_left)%60]
		if me.health <= 0: hud.text += "ELIMINATED · respawn en 3 segundos\n"
		elif me.reload_time > 0: hud.text += "RELOADING…\n"
		if net.development:
			hud.text += "DEV / NOT_ATTESTED    Aim %.0f/100    RTT %dms\nTick %dµs · detector %dµs · F8 SIM %s" % [suspicion,net.ping_ms,net.tick_us,net.detector_us,"ON" if lab_on else "OFF"]

func show_notice(message: String) -> void:
	toast.text = message
	toast_left = 8

func _process(delta: float) -> void:
	toast_left -= delta
	toast.visible = toast_left > 0

func save_settings() -> void:
	settings.set_value("client","ip",ip)
	settings.set_value("client","name",nickname)
	settings.set_value("client","sensitivity",sensitivity)
	settings.save("user://settings.cfg")
