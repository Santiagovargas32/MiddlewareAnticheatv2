extends RefCounted
## No lab toggle or ground truth enters this API. Heuristic, not a cheat verdict.
var previous: Dictionary = {}
var score = 0.0
var snaps = 0
var samples = 0
var tracking_seconds = 0.0
var alert_sent = false

func observe(yaw: float, pitch: float, error: float, visible_target: int, delta: float) -> Dictionary:
	samples += 1
	var snap = 0.0
	if not previous.is_empty() and delta > 0:
		snap = Vector2(angle_difference(previous.yaw,yaw),pitch-previous.pitch).length()
		if snap > deg_to_rad(18) and error < deg_to_rad(1.0) and visible_target != 0:
			score += 18
			snaps += 1
		if error < deg_to_rad(0.12) and visible_target != 0 and snap > 0.00005:
			tracking_seconds += delta
			if tracking_seconds > 1.0:
				score += delta*8
		else:
			tracking_seconds = maxf(0,tracking_seconds-delta*2)
	score = clampf(score-delta*0.7,0,100)
	previous = {"yaw":yaw,"pitch":pitch}
	var state = "NORMAL"
	if score >= 20: state = "OBSERVING"
	if score >= 45: state = "SUSPICIOUS"
	if score >= 75: state = "HIGH_SUSPICION"
	return {"score":score,"state":state,"snap_radians":snap,"snaps":snaps,"samples":samples,"tracking_seconds":tracking_seconds}
