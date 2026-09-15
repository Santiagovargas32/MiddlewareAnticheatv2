extends CharacterBody3D
## Only the server simulates these bodies. Clients interpolate snapshots.
var health = 100
var ammo = 12
var kills = 0
var deaths = 0
var yaw = 0.0
var pitch = 0.0
var cooldown = 0.0
var reload_time = 0.0
var respawn_time = 0.0
var target_position = Vector3.ZERO
var capsule: MeshInstance3D
var camera: Camera3D

func _ready() -> void:
	var shape = CollisionShape3D.new()
	shape.shape = CapsuleShape3D.new()
	shape.shape.radius = 0.35
	shape.shape.height = 1.8
	shape.position.y = 0.9
	add_child(shape)
	capsule = MeshInstance3D.new()
	capsule.mesh = CapsuleMesh.new()
	capsule.mesh.radius = 0.35
	capsule.mesh.height = 1.8
	capsule.position.y = 0.9
	var material = StandardMaterial3D.new()
	material.albedo_color = Color("e6a15a")
	capsule.material_override = material
	add_child(capsule)
	camera = Camera3D.new()
	camera.position.y = 1.55
	camera.fov = 85
	add_child(camera)
	var weapon = MeshInstance3D.new()
	weapon.mesh = BoxMesh.new()
	weapon.mesh.size = Vector3(0.14,0.18,0.65)
	weapon.position = Vector3(0.28,-0.23,-0.55)
	var metal = StandardMaterial3D.new()
	metal.albedo_color = Color("597887")
	metal.metallic = 0.6
	weapon.material_override = metal
	camera.add_child(weapon)
	weapon.hide()

func aim(y: float, p: float) -> void:
	yaw = y
	pitch = p
	camera.rotation = Vector3(pitch,yaw,0)

func simulate(delta: float, intent: Dictionary) -> void:
	cooldown = maxf(0,cooldown-delta)
	if reload_time > 0:
		reload_time = maxf(0,reload_time-delta)
		if reload_time == 0:
			ammo = 12
	if health <= 0:
		return
	aim(intent.get("yaw",yaw), intent.get("pitch",pitch))
	var axis: Vector2 = intent.get("move",Vector2.ZERO)
	var direction = Basis(Vector3.UP,yaw) * Vector3(axis.x,0,axis.y)
	velocity.x = direction.x * 6.0
	velocity.z = direction.z * 6.0
	if not is_on_floor():
		velocity.y -= 22.0*delta
	elif intent.get("jump",false):
		velocity.y = 7.5
	else:
		velocity.y = 0
	move_and_slide()
	if intent.get("reload",false) and ammo < 12 and reload_time == 0:
		reload_time = 1.4

func can_fire() -> bool:
	return health > 0 and ammo > 0 and reload_time == 0 and cooldown == 0

func pack() -> Dictionary:
	return {"position":position,"yaw":yaw,"pitch":pitch,"health":health,"ammo":ammo,"kills":kills,"deaths":deaths,"reload":reload_time}

func unpack(value: Dictionary, local: bool, delta: float) -> void:
	target_position = value.position
	if position.distance_to(target_position) > 3:
		position = target_position
	else:
		position = position.lerp(target_position,1-exp(-20*delta))
	for key in ["health","ammo","kills","deaths"]:
		set(key,value[key])
	reload_time = value.reload
	capsule.visible = not local and health > 0
	camera.get_child(0).visible = local and health > 0
	if not local:
		aim(value.yaw,value.pitch)
