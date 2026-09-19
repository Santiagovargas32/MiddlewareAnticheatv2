# MA-010 — Evidencia de diseño y aceptación futura

Base: `648ff3c06efbadd554cf199c05e16b0663c11af0`. Fecha: 2026-09-19.
[ADR 0010](../adr/0010-attestor-peer-binding.md) propuesta. Esta ficha separa lo
reproducido de los escenarios que deberán probar MA-012/013/014; no certifica
protegido, hardware, LAN física ni precisión conductual.

## Comprobado ahora

- MA-000 es ancestro de origin/main actualizado, que apunta al mismo `648ff3c`;
  árbol inicial limpio. Documentación de estado anterior aún decía IN_REVIEW:
  se corrige por evidencia Git, sin inferir número de PR ni hacer merge.
- Lectura de `session_admission.py`: siete campos, TTL 300/10/30 s, suspensión
  al pedir challenge, `status` sin push, 8 handlers/4 verificaciones y estados
  terminales de revocación. No existe binding de ese registro con Godot aún.
- Binario local: Godot `4.7.2.stable.official.ed1daf0bf`, SHA256
  `8d106cbe6144c2dc7e881d61d2429c1a8a76e6b22ef48bd5e48dcf934953f71e`, idéntico
  al pin de `tools/prepare_godot.py`. Reflexión: 23 firmas pertinentes, incluidas
  TLSOptions sin credenciales cliente y ENet/OS requeridas por la propuesta.
- Smoke Godot headless: atribución exacta del endpoint real del peer a su puerto
  cliente y eco por pipe privado no bloqueante, 27 frames durante la espera de
  150 ms del hijo. Sólo capacidades, no túnel ni integración de admisión.
- Primer sondeo de reflexión emitió errores al intentar crear directorios de
  usuario fuera del sandbox. Se corrigió el **ensayo**, usando proyecto temporal
  y XDG aislado; segunda ejecución sin errores. No se cambió el runtime del FPS.
- `cmake --build build-tpm --parallel 2`: PASS sobre configuración local Release,
  `-Werror`, `LAB_TPM=ON`, raíz actual. No se ejecutó CTest completo: fuentes C intactos.
- `python3 scripts/verificar-admision.py --inspector build-tpm/lab_quote_inspect`:
  PASS 14/14, firmas software, TLS loopback, relojes/carreras controlados. Ejecutado
  con permiso de sockets locales. Casos: allow/expiry/renewal, esquema/firma,
  nonce por binding, configuración, límites/restart, uso único/aislamiento,
  política PCR, evidencia reetiquetada, revoke concurrente, roles, ciclo CLI,
  timeout/verificación tardía, TLS/CLI y saturación/cierre.

Cierre documental: `python3 scripts/verificar-documentacion.py` PASS (139 archivos,
100 enlaces); `python3 tools/verify_release.py` PASS 6/6 grupos, incluidos 29 checks
Godot y 6 casos loopback headless. Extracción limpia con 139 hashes correctos,
ADR/sondeos presentes y privados excluidos. Los comandos de sondeo publicados más
abajo se ejecutaron literalmente y pasaron. Diff limitado a 11 archivos Markdown;
no se cambian runtime, inventario ni CI. Logs locales en `results/release-checks/`
y sondeos temporales ignorados; no se distribuyen credenciales ni trazas del host.

Las comprobaciones de API y del registro sostienen **viabilidad de APIs y semántica
actual del registro**. No prueban la barrera nueva de renovación, el forwarding,
el límite de 800 ms ni los parsers futuros. Su aceptación sigue pendiente.

## Fuentes primarias y contraste de versión

Consultadas el 2026-09-19. Las páginas `stable` son móviles; la disponibilidad
concreta se contrastó por reflexión con el binario fijado arriba, no se atribuye
una API futura a la versión instalada.

- [Godot TLSOptions](https://docs.godotengine.org/en/stable/classes/class_tlsoptions.html): firmas client/server; no configuración mTLS de cliente expuesta en la API inspeccionada.
- [Godot ENetConnection](https://docs.godotengine.org/en/4.5/classes/class_enetconnection.html): DTLS soportado por ENet; referencia conceptual 4.5, contrastada con API local 4.7.2.
- [Godot ENetMultiplayerPeer](https://docs.godotengine.org/en/stable/classes/class_enetmultiplayerpeer.html) y [ENetPacketPeer](https://docs.godotengine.org/en/stable/classes/class_enetpacketpeer.html): bind local, get_peer y endpoint remoto.
- [Godot OS.execute_with_pipe](https://docs.godotengine.org/en/stable/classes/class_os.html#class-os-method-execute-with-pipe): IO redirigido, modo no bloqueante, PID; el hijo necesita gestión explícita de cierre.
- [Python ssl](https://docs.python.org/3/library/ssl.html): CERT_REQUIRED y check_hostname, obtención del certificado del peer; la CA por sí sola no define roles de aplicación.
- [TLS 1.3, RFC 8446](https://www.rfc-editor.org/rfc/rfc8446.html): CertificateVerify/Finished prueban posesión en el handshake; 0-RTT tiene límites de replay, por lo que la propuesta lo excluye.
- Código de esta base: [registro](../../scripts/session_admission.py), [pruebas software](../../scripts/verificar-admision.py), [contexto TLS](../../scripts/bridge_transport.py), [QuoteVerifier](../../scripts/tpm_attestation.py), [Godot](../../game/scripts/network.gd).

No se diseñan primitivas criptográficas: framing, correlación y estados son
protocolo de aplicación sobre TLS estándar. Las cotas numéricas de la ADR son
presupuestos propios pendientes de E2E, no garantías de esas fuentes.

## Matriz E2E pendiente

Todos los casos de esta tabla están **PENDING**, no PASS. Implementar fixtures con
certificados temporales, reloj inyectable, barreras en las carreras y procesos
propios con deadline. Cerrar conexiones y comprobar que no quedan hijos/tareas/FDs.
El harness software debe ejecutar Godot, ambos auxiliares y registro reales;
mocks sólo para ubicar fallos/orden, nunca como prueba de transporte integrado.

| ID / paquete | Estímulo controlado | Oráculo observable |
| --- | --- | --- |
| T01 / MA-012–014 | Dos identidades admitidas completan canal, binding, barrera y Quote software | Sólo sus peers obtienen permiso; ready/partida/intención/snapshot funcionan. Etiquetado software. |
| T02 / MA-012 | Sin certificado, CA ajena, expirado, SAN/pin de gateway/servicio incorrectos o certificado sin rol | No ROUTE_ACK/permiso ni downgrade; recursos liberados. |
| T03 / MA-012 | Misma CA, attestor diferente; presentar fingerprint o ALLOW de otro jugador | Se usa certificado del canal; binding ajeno rechazado, estado de víctima intacto. |
| T04 / MA-012 | Entrar por UDP directo LAN/loopback, peer extra sobre canal, endpoint cambiado | Godot no admite asociación fuera de ruta propia reconocida; ningún spawn/acción. |
| T05 / MA-012 | Repetir ciphertext TLS, OPEN de canal cerrado o RPC de otra conexión | No transfiere permiso; conexión/generación nueva y rechazo de mensaje viejo. |
| T06 / MA-012 | Dos peers, desconectar uno y forzar reutilización de peer_id/puerto | Canal/binding/generación/ruta viejos nunca aplican al nuevo; sockets retirados no se reasignan. |
| T07 / MA-012 | Frame 0/excesivo, tipo inválido, JSON duplicado/no finito/profundo, bytes parciales y EOF | Rechazo antes de reserva excesiva, sin bloqueo ni desincronización recuperada a ciegas. |
| T08 / MA-012 | Pipe roto, hijo muerto, stderr lleno, escritor bloqueado, padre termina | Permisos invalidados; sólo procesos propios terminan; tick no espera TLS/subprocess. |
| T09 / MA-013 | Cambiar por separado cada uno de los siete campos del binding | Rechazo sin consumir intención válida ni tocar otra conexión. |
| T10 / MA-013 | Permiso ausente/negado/expirado, allow false, exit code 0 o submit ALLOW presentado por cliente | Sin ready/spawn/movimiento voluntario/fire/reload; status auténtico es imprescindible. |
| T11 / MA-013 | Cambiar nonce, salt, qualification, AK, firma o política PCR configurada | Quote no concede permiso; attestor no firma contexto de canal distinto. |
| T12 / MA-013 | ALLOWED auténtico pero retrasado >200 ms, remaining 0/inválido o deadline agotado en cola | No conceder; vigencia anclada al instante previo a encolar, no a recepción. |
| T13 / MA-013 | Guard acepta una intención y se pierde permiso antes de su aplicación | No movimiento/fire/jump/reload posterior; epoch viejo descartado, ready retirado. |
| T14 / MA-013 | Disparar a cuerpo suspendido, muerte y reactivación | Daño recibido normal, sin invulnerabilidad ni refill; respawn sólo con permiso. |
| T15 / MA-014 | Renovación a 20 s, Quote rápida/lenta, attestor omite submit o submit antes de barrera | Suspensión explícita; sólo CHALLENGED observado + ALLOW posterior reactivan; timeout cierra. |
| T16 / MA-014 | Retener ALLOW anterior y entregarlo después de suspensión/SUBMIT_GO | request_id/epoch/plazo lo descartan; no rehabilita sin nueva verificación. |
| T17 / MA-014 | Revocar con submit/verificación/status en vuelo; liberar resultado tarde | CLOSED permanece terminal; acciones y pendientes retirados; ni resultado ni reconexión vieja rehabilitan. |
| T18 / MA-014 | Servicio caído, TLS stall, respuestas truncadas, 8 handlers/4 verificaciones ocupados | Sin gracia ni fallback; deadline local funciona incluso sin respuesta negativa. |
| T19 / MA-014 | Restart de servicio/gateway/Godot | instance_id/run/generation anteriores inválidos; recuperación explícita con binding/Quote nuevos. |
| T20 / MA-014 | Partida 300 s iniciada tras lobby largo y otra de 3600 s | Rollover a 270 s, revoke confirmado antes de register; cero solapamiento de permisos, partida/puntuación continúan. |
| T21 / MA-014 | Revoke/register de rollover falla o respuesta se pierde; binding llega a 300 s | Cerrar sin revivir binding; no register ambiguo repetido sobre mismo peer. |
| T22 / MA-013–014 | Revancha con mismos peers; ready/input/snapshot de match/ronda anterior | IDs nuevos/rechazo; permiso independiente de ronda, detector no reseteado por admisión. |
| T23 / MA-014 | Tick pausado hasta superar valid_until, luego recuperar ticks | Antes del primer efecto se descarta intención y suspende; no ráfaga de acciones retenidas. |
| T24 / MA-014 | Capturar instante de revoke y último efecto, con polls perdidos/retardados, 20/60/120 Hz y 8 peers | Máximo ≤800 ms bajo G≤50 ms; registrar peor caso y retrasos de scheduler; cualquier exceso falla gate. |
| T25 / MA-012–014 | Llenar colas, ráfagas, frame lento, pérdida TCP y tráfico kernel retenido | Límites observables, cierre con razón; inputs demasiado antiguos rechazados por tick servidor, sin crecimiento ilimitado. |
| T26 / MA-013–014 | Cliente development contra protegido y viceversa; versión desconocida, falta configuración | Rechazo explícito; jamás reinterpretar legacy RPC o degradar perfil. |
| T27 / MA-014 | Renovar/rotar durante muerte, lobby, respawn y final de partida | Estado de conexión separado de partida/ronda; sin vidas, munición o score regalados. |
| T28 / MA-012–014 | 256 rutas retiradas, overflow de secuencia/request/generación, teardown concurrente | Rechazo/reinicio explícito y sin reutilización; sólo recursos propios liberados. |

Para T24 usar un harness que marque revoke confirmado y efectos del servidor en
**un solo reloj de observación** (procesos de prueba locales con eventos
correlacionados). En dos hosts no restar timestamps monotónicos remotos: medir
con observador único o acotar recorrido desde orden hasta ACK de retirada, declarar
la incertidumbre. Medir después de revoke confirmado subestima el inicio del
revoke si sólo se toma el ACK: el harness local debe instrumentar el commit de
revocación; alternativa conservadora, comenzar antes de enviar la orden.

## Reproducir los sondeos de capacidad

Python 3.11+, binario Godot fijado disponible, sockets loopback autorizados. El
comando extrae los dos bloques GDScript de este documento en directorio temporal,
aisla datos/caché, aplica timeout y falla ante errores del motor. No altera game/.
El número de frames es una observación variable, no un benchmark/gate de rendimiento.

```bash
python3 - <<'PYCODE'
import hashlib, os, re, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, 'tools')
from run_game import engine
from prepare_godot import BINARY_SHA256
binary = engine()
assert hashlib.sha256(Path(binary).read_bytes()).hexdigest() == BINARY_SHA256
source = Path('docs/development/ma-010-validation.md').read_text()
blocks = re.findall(r'```gdscript\n(.*?)```', source, re.S)
assert len(blocks) == 2
with tempfile.TemporaryDirectory(prefix='ma010-probe-') as temporary:
    root = Path(temporary)
    (root/'project.godot').write_text('[application]\nconfig/name="MA010Probe"\n')
    env = dict(os.environ, XDG_DATA_HOME=str(root/'data'),
               XDG_CONFIG_HOME=str(root/'config'), XDG_CACHE_HOME=str(root/'cache'))
    for i, block in enumerate(blocks):
        script = root/f'probe-{i}.gd'
        script.write_text(block)
        result = subprocess.run([binary, '--headless', '--path', str(root),
                                 '--script', str(script)], env=env,
                                capture_output=True, text=True, timeout=10)
        print(result.stdout, result.stderr)
        assert result.returncode == 0 and 'ERROR:' not in result.stdout+result.stderr
        if i == 1: assert '"passed":true' in result.stdout
PYCODE
```

Reflexión de API (disponibilidad, no seguridad demostrada):

```gdscript
extends SceneTree
func _initialize() -> void:
    print(JSON.stringify(Engine.get_version_info()))
    var wanted = {
        "TLSOptions": ["client", "server", "get_private_key", "get_trusted_ca_chain"],
        "ENetConnection": ["dtls_server_setup", "dtls_client_setup", "get_local_port"],
        "ENetMultiplayerPeer": ["create_client", "create_server", "set_bind_ip", "get_peer"],
        "ENetPacketPeer": ["get_remote_address", "get_remote_port"],
        "OS": ["execute_with_pipe", "is_process_running", "kill"],
        "FileAccess": ["get_buffer", "store_buffer", "get_error", "get_length"],
        "SceneMultiplayer": ["set_auth_callback", "complete_auth", "send_auth"]
    }
    for klass in wanted:
        for method in ClassDB.class_get_method_list(klass, true):
            if method.name in wanted[klass]:
                print(JSON.stringify({"class": klass, "method": method}))
    quit()
```

Ensayo de endpoint real y pipe privado:

```gdscript
extends SceneTree
var server = ENetMultiplayerPeer.new()
var client = ENetMultiplayerPeer.new()
var remote_id = 0
var child: Dictionary
var received = PackedByteArray()
var ticks = 0
var deadline = 0
var endpoint_ok = false
func fail(message: String) -> void:
    printerr(message)
    cleanup()
    quit(1)
func cleanup() -> void:
    server.close()
    client.close()
    if child.has("stdio"): child.stdio.close()
    if child.has("stderr"): child.stderr.close()
    if child.has("pid") and OS.is_process_running(child.pid): OS.kill(child.pid)
func _initialize() -> void:
    server.set_bind_ip("127.0.0.1")
    client.set_bind_ip("127.0.0.1")
    if server.create_server(0, 2, 4) != OK:
        fail("cannot bind local ENet probe")
        return
    server.peer_connected.connect(func(id: int): remote_id = id)
    if client.create_client("127.0.0.1",server.host.get_local_port(),4) != OK:
        fail("cannot connect local ENet probe")
        return
    child = OS.execute_with_pipe("/usr/bin/python3",["-u","-c","import sys,time; data=sys.stdin.buffer.read(4); time.sleep(0.15); sys.stdout.buffer.write(data); sys.stdout.buffer.flush()"],false)
    if child.is_empty() or not child.stdio.store_buffer("PING".to_utf8_buffer()):
        fail("cannot start/write private pipe")
        return
    deadline = Time.get_ticks_msec()+3000
func _process(_delta: float) -> bool:
    ticks += 1
    server.poll()
    client.poll()
    if remote_id != 0 and not endpoint_ok:
        var actual = server.get_peer(remote_id)
        if actual.get_remote_address() != "127.0.0.1" or actual.get_remote_port() != client.host.get_local_port():
            fail("endpoint mismatch")
            return true
        endpoint_ok = true
    if child.has("stdio"):
        received.append_array(child.stdio.get_buffer(4-received.size()))
    if received.size() == 4 and endpoint_ok:
        if received.get_string_from_utf8() != "PING" or ticks < 2:
            fail("pipe response mismatch or main loop blocked")
            return true
        print(JSON.stringify({"passed":true,"enet_endpoint_attribution":true,"nonblocking_private_pipe":true,"frames_during_wait":ticks,"scope":"API smoke only; no mTLS tunnel or admission integration"}))
        cleanup()
        quit()
        return true
    if Time.get_ticks_msec() >= deadline:
        fail("probe timeout")
        return true
    return false
```

Las pruebas de presión de pipe, muerte inesperada y EOF parcial son T07/T08,
pendientes de implementación. Este eco pequeño no demuestra esas propiedades.
