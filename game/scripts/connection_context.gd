extends RefCounted
## Server-local connection lifetime, independent of lobby/match/round state.
## This generation is not an authenticated binding or a wire protocol field.
enum State { PENDING, ADMITTED, CLOSED }
var peer_id: int
var generation: int
var connected_at_ms: int
var state = State.PENDING
var last_sequence = 0
var last_input_tick = -1

func _init(id: int, serial: int, now_ms: int) -> void:
	peer_id = id
	generation = serial
	connected_at_ms = now_ms

func close() -> void:
	state = State.CLOSED
	last_sequence = 0
	last_input_tick = -1
