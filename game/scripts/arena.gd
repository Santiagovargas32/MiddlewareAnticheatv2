extends Node3D
## Original procedural geometry, shared by headless physics and rendering.
const SPAWNS = [Vector3(-10,1,-10), Vector3(10,1,10), Vector3(-10,1,10), Vector3(10,1,-10), Vector3(0,1,-12), Vector3(0,1,12), Vector3(-12,1,0), Vector3(12,1,0)]

func _ready() -> void:
	box(Vector3(0,-0.5,0), Vector3(30,1,30), Color("202d40"))
	for p in [Vector3(-15,2,0),Vector3(15,2,0)]:
		box(p, Vector3(1,5,30), Color("384763"))
	for p in [Vector3(0,2,-15),Vector3(0,2,15)]:
		box(p, Vector3(30,5,1), Color("384763"))
	for p in [Vector3(-5,1,-4),Vector3(5,1,4)]:
		box(p, Vector3(3,2,6), Color("346979"))
	for p in [Vector3(-9,0.6,3),Vector3(9,0.6,-3),Vector3(0,0.6,0)]:
		box(p, Vector3(3,1.2,2), Color("ad7446"))
	# Walkable stairs to two elevated firing positions.
	for side in [-1,1]:
		for step in range(1,6):
			box(Vector3(side*10,step*0.15,-6+step*0.7), Vector3(3,step*0.3,0.7), Color("42627a"))
		box(Vector3(side*10,0.75,-1.5),Vector3(3,1.5,3),Color("42627a"))
	var sun = DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-55,-25,0)
	sun.light_energy = 1.3
	add_child(sun)
	var world = WorldEnvironment.new()
	world.environment = Environment.new()
	world.environment.background_mode = Environment.BG_COLOR
	world.environment.background_color = Color("0e1728")
	world.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	world.environment.ambient_light_color = Color("aec4e0")
	world.environment.ambient_light_energy = 0.65
	add_child(world)

func box(pos: Vector3, size: Vector3, color: Color) -> void:
	var body = StaticBody3D.new()
	body.position = pos
	var shape = CollisionShape3D.new()
	shape.shape = BoxShape3D.new()
	shape.shape.size = size
	body.add_child(shape)
	var mesh = MeshInstance3D.new()
	mesh.mesh = BoxMesh.new()
	mesh.mesh.size = size
	var material = StandardMaterial3D.new()
	material.albedo_color = color
	mesh.material_override = material
	body.add_child(mesh)
	add_child(body)
