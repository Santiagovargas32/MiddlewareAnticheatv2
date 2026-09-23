# Transporte interno MA-012 — ENet sobre mTLS

Implementación experimental de la frontera de transporte de [ADR 0010](adr/0010-attestor-peer-binding.md).
**Sólo harness interno; no concede permiso de juego.** El servidor público sigue
requiriendo `--development`, y sin esa opción sigue rechazando el arranque.
No consulta arena-admission/1, no verifica Quote y no implementa MA-013/014.

## Componentes y propiedad

- [arena_gateway.py](../scripts/arena_gateway.py): auxiliar Python, TLS 1.3 mutuo,
  allowlist por SHA256 DER, socket UDP por canal, tareas/colas y cierre propios.
- [gateway_protocol.py](../scripts/gateway_protocol.py): codecs independientes
  del laboratorio C, JSON estricto, secuencias, cuotas y colas con edad máxima.
- [gateway_process.gd](../game/scripts/gateway_process.gd): Godot lanza al hijo
  con ruta absoluta y `OS.execute_with_pipe(..., false)`; CONFIG por stdin, stdout
  sólo IPC, stderr drenado a anillo de 64 KiB. Supervisor de un solo uso.
- [peer_routes.gd](../game/scripts/peer_routes.gd): consume una ruta reconocida al
  observar `ENetMultiplayerPeer.get_peer(id)`. Reutiliza el contexto MA-011 en
  PENDING; no llama a hello ni admite al jugador. Una ruta no admite dos peers.

Python es propietario de TLS/UDP y Godot de ENet/IPC/hijo. EOF, heartbeat vencido,
parser inválido o muerte del auxiliar invalidan rutas en el consumidor antes del
cierre. El harness demuestra esa retirada con un canal vivo. El futuro juego
debe hacer lo mismo y añadir sus guard/epochs; no se supone que eso ya esté integrado.

## Subconjunto implementado de los protocolos /1

Túnel `arena-enet-tunnel/1`: TLS 1.3 exclusivamente, certificado cliente obligatorio,
cadena/vigencia y SAN del servidor verificados, pin del gateway y allowlist de
attestors. El certificado servidor no puede figurar como attestor. No se aceptan
ALPN distintos ni sesiones TLS reanudadas; servidor sin tickets/0-RTT.

Frame: uint32 BE longitud, tipo uint8, payload. Tipo 1 lleva un datagrama opaco
de 1–4096 bytes; tipo 2 JSON de 1–4096 bytes. Tamaño total de cuerpo 2–4097.
Primer byte: timeout de inactividad 1 s; a partir de él, 200 ms totales para
cabecera y cuerpo. Cualquier error/EOF parcial cierra ese canal.

| Control | Campos exactos |
| --- | --- |
| OPEN servidor | operation, protocol_version, profile, server_run_id, channel_id, game_session_id |
| OPEN_ACK cliente | Los mismos valores, operation=OPEN_ACK; igualdad exacta |
| HEARTBEAT / CLOSE | Sólo operation |

`profile=verified_pinned_ak/1` nombra el perfil futuro de la ADR, **no demuestra
atestación ni permiso**. Aquí sólo se autentica transporte. BINDING, challenge,
submit y decisiones de admisión no están implementados y se rechazan.
El cliente aprende run/sesión del OPEN autenticado; no necesita conocer la sesión
aleatoria antes de establecer TLS. Cada canal recibe ID aleatorio nuevo de 128 bits.

IPC `arena-gateway-ipc/1`: uint32 BE + JSON de 1–4096 bytes, envelope exacto:
`protocol_version`, `server_run_id` (run del padre local), `gateway_generation`,
`request_id`, `operation`, `body`. Cada dirección tiene secuencia independiente,
contigua desde 1, máximo 2³¹−1; overflow cierra, nunca wrap. Generación 1..2³¹−1.
IDs run/canal/sesión: 32 hex minúsculas; fingerprints: 64. Puertos enteros 1..65535
(0 sólo al pedir escucha efímera/READY cliente). No bool como entero, floats,
claves duplicadas, campos extra ni profundidad >4. Python emite JSON con escapes
ASCII; Godot rechaza bytes no ASCII en esa dirección antes de decodificar.

| Operación IPC | Dirección / body exacto |
| --- | --- |
| CONFIG | Padre → hijo. Comunes: role, cert, key, ca (rutas absolutas), host (IPv4), port. Server añade game_port, game_session_id, attestors (1–8 pins distintos). Client añade gateway_pin y server_name. |
| READY | Hijo → padre: port (escucha TCP servidor; 0 cliente). Una vez. |
| ROUTE_OPEN | Hijo → padre: channel_id, attestor, address=127.0.0.1, port, remote_run_id, game_session_id. Identidad derivada del certificado TLS, nunca de OPEN_ACK. |
| ROUTE_ACK | Padre → hijo: channel_id, route_request_id (request_id de ROUTE_OPEN); cliente añade client_port observado en ENet. Un único ACK exacto por ruta. |
| ROUTE_CLOSE | Ambas direcciones: channel_id. Es terminal; cierre concurrente ya retirado es idempotente en Python. Un ACK tardío no rehabilita. |
| HEARTBEAT / SHUTDOWN | Body vacío; SHUTDOWN sólo padre → hijo. |

No hay socket de control local ni secretos en argv. La configuración inicial por
pipe contiene rutas, nunca material de clave. Las credenciales siguen fuera de Git.
Godot conserva PID/handles propios y debe llamar shutdown y seguir poll hasta la
salida: gracia 2 s, luego termina sólo su hijo; un segundo margen de 1 s permite
detectar fallo de cierre. Tras `OS.kill` exitoso no consulta otra vez el PID ya
recogido. Reinicio requiere supervisor/contexto/generación nuevos, no reutilizar
el objeto terminal ni transferir sus mensajes pendientes.

## Asociación, límites y particularidades comprobadas

Servidor ENet ligado a loopback. Python crea UDP conectado sólo a ese servidor y
no reenvía antes del ACK privado. Godot compara address/port observados, consume
la asociación una vez y crea contexto nuevo. Desconectar retira contexto y ruta.
Puertos/IDs retirados nunca se reasignan en el mismo gateway: se conservan sockets
UDP sin forwarding y se drenan. Máximo **256 rutas totales, activas + retiradas**;
es más conservador que 256 retiradas de la ADR. Al agotarse, rechazar nuevos canales
y exigir reinicio explícito. No se liberan puertos individuales para reutilizarlos.

El cliente fija origen antes del forwarding mediante client_port. Se valida también
el origen de cada recvfrom: datagramas ajenos encolados **antes** del ACK no se
vuelven confiables al conectar el socket. La prueba reproduce ese caso.

`create_client(local_port=0)` no liga el cliente a bind_ip. Se selecciona un puerto
efímero local y se crea ENet con ese puerto explícito; si otro proceso lo ocupa en
el intervalo, se rechaza sin fallback. Se comprueba el bind real en `/proc/net/udp*`
para los puertos propios. Referencia de API: [documentación Godot](https://docs.godotengine.org/en/stable/classes/class_enetmultiplayerpeer.html)
y [implementación upstream](https://github.com/godotengine/godot/blob/master/modules/enet/enet_multiplayer_peer.cpp),
contrastadas con el Godot 4.7.2 fijado mediante procesos reales (upstream es móvil).

| Recurso | Límite / oráculo |
| --- | --- |
| TLS | 4 handshakes pendientes antes de trabajo TLS, 3 s; 8 canales activos |
| Datagramas/control entrante | 512 mensajes/s, ráfaga 64; 512 KiB/s, ráfaga 64 KiB; cerrar exceso |
| Colas por canal/dirección | 64 frames / 64 KiB / 100 ms de edad; cerrar exceso, no eliminar cabeceras parciales |
| Escrituras TLS / IPC Python | 200 ms de progreso; IPC saliente 128 mensajes / 256 KiB / 200 ms de edad |
| Lectura IPC Godot | Hasta 32 mensajes, 64 KiB o presupuesto cooperativo 1 ms por poll; JSON individual acotado |
| Escritura IPC Godot | No bloqueante; resultado parcial/fallido de progreso desconocido cierra sin reenviar |
| Heartbeats | Cada 250 ms; timeout 1 s. No renuevan permiso |

El presupuesto de trabajo de poll se comprueba entre operaciones; no es tiempo
real duro del scheduler. Las colas no limitan por sí solas la edad dentro de
buffers TCP/kernel. TCP conserva orden y puede retener datagramas ENet unreliable.
Los tests miden RTT y retención parcial; **no acreditan vigencia de intenciones,
jugabilidad bajo renovación ni la cota de revocación de 800 ms**.

## Reproducir y continuar

```bash
python3 tests/gateway_tests.py
python3 tools/verify_gateway.py
python3 tools/verify_release.py
```

Requiere Python 3.11+, OpenSSL, Linux con sockets loopback y Godot fijado por el
proyecto. Las pruebas crean certificados temporales y limpian sólo procesos
propios, con deadline. No acceden a TPM ni modifican red/permisos del sistema.
[Evidencia y alcance](development/ma-012-validation.md),
[ficha MA-012](development/tasks/MA-012.md). MA-013 debe reutilizar estos módulos,
comprobar las garantías faltantes y añadir register/barrera/guard sin abrir todavía
protegido público. MA-014 completa lifecycle y su aceptación de tiempos; MA-015
aporta LAN/TPM físicos. No se implementan aquí.
