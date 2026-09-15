extends RefCounted
## Internal to this game's client. No process inspection or external access.
var enabled = false
var reacquisition = false

func direction(pawn: Node3D, pawns: Dictionary, own_id: int) -> Vector2:
	var best = INF
	var result = Vector2(pawn.yaw,pawn.pitch)
	for id in pawns:
		var other = pawns[id]
		if id == own_id or other.health <= 0: continue
		var offset: Vector3 = other.position-pawn.position
		if offset.length() < best:
			var query = PhysicsRayQueryParameters3D.create(pawn.position+Vector3.UP*1.55,other.position+Vector3.UP*1.55)
			query.exclude = [pawn.get_rid()]
			var hit = pawn.get_world_3d().direct_space_state.intersect_ray(query)
			if not hit.is_empty() and hit.collider == other:
				best = offset.length()
				result = Vector2(atan2(-offset.x,-offset.z),atan2(offset.y,Vector2(offset.x,offset.z).length()))
	if reacquisition and best < INF and fmod(Time.get_ticks_msec()/1000.0,0.8) < 0.25:
		result.x = wrapf(result.x+0.8,-PI,PI)
	return result
