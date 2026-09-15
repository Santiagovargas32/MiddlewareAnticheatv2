extends SceneTree
const Detector = preload("res://scripts/aim_detector.gd")

func _initialize() -> void:
	var args = OS.get_cmdline_user_args()
	if args.size() != 1:
		printerr("Expected server telemetry JSONL path")
		quit(2)
		return
	var file = FileAccess.open(args[0],FileAccess.READ)
	if file == null or file.get_length() > 128*1024*1024:
		printerr("Invalid input file or size exceeds 128 MiB")
		quit(2)
		return
	var detectors = {}
	var rows = 0
	while not file.eof_reached():
		var line = file.get_line()
		if line.length() > 16384:
			quit(2)
			return
		if line.is_empty(): continue
		var value = JSON.parse_string(line)
		if not value is Dictionary:
			quit(2)
			return
		if value.get("schema","") != "arena-observation/1": continue
		for key in ["yaw","pitch","error","delta","visible_target","tick","player"]:
			if not value.has(key) or not (value[key] is float or value[key] is int) or not is_finite(value[key]):
				quit(2)
				return
		if value.delta <= 0 or value.delta > 1 or absf(value.yaw) > PI or absf(value.pitch) > 1.5 or value.error < 0 or value.error > PI:
			quit(2)
			return
		var key = str(value.get("session",""))+":"+str(int(value.player))
		if not detectors.has(key): detectors[key] = Detector.new()
		var result = detectors[key].observe(value.yaw,value.pitch,value.error,int(value.visible_target),value.delta)
		print(JSON.stringify({"session":value.session,"player":int(value.player),"tick":int(value.tick),"server_ms":value.server_ms,"score":result.score,"state":result.state}))
		rows += 1
	file.close()
	quit(0 if rows else 2)
