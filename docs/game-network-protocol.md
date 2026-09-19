# Arena game protocol / 1

El FPS Godot usa ENet y RPC de Godot 4, **separado** de `lab-udp/2`,
`lab-game-input/1` y `lab-attest/1`. No modifica sus cabeceras ni codecs C.
Se recomienda el mismo Godot 4.7.2 y los mismos scripts en todos los peers:
Godot comprueba la firma RPC y el servidor comprueba `VERSION = 1` en hello.
No es un formato interoperable con implementaciones ajenas a Godot.

## Transporte y autoridad

Servidor dedicado, UDP 7777 configurable, hasta 8 clientes, IPv4 LAN inicial.
El peer 1 es autoridad. El ID del jugador se obtiene de `get_remote_sender_id()`;
ningún argumento de cliente selecciona el jugador al que aplicar una intención.
Godot no deserializa objetos arbitrarios (se conserva el valor predeterminado).

| Familia | Canal / entrega | Datos y validación |
| --- | --- | --- |
| Conexión | 0, reliable | hello: versión 1 y nombre de 1–24 caracteres identificador; rechazo de versión/nombre inválido, nombre duplicado y partida en curso. Handshake máximo 5 s. |
| Sesión | 0, reliable | welcome: ID aleatorio servidor de 128 bits y perfil development. Es un identificador de asociación, no un secreto sobre ENet sin cifrar. |
| Lobby | 0, reliable | ready_request: sesión vigente, peer admitido, fase LOBBY/RESULTS. Dos o más READY inician FFA. |
| Gameplay | 1, unreliable ordered | intención: sesión, secuencia positiva <= 2³¹−1, Vector2 de movimiento de módulo <=1, yaw en ±π, pitch en ±1.5, jump/fire/reload booleanos. Rechaza NaN/infinito. |
| Estado | 2, unreliable ordered | snapshot autoritativo: sesión, fase, roster, posiciones, vida, munición, puntuación, reloj de partida y tick servidor. 20 Hz por defecto. |
| Eventos | 0 reliable / 2 unreliable | alertas y kill feed fiables; feedback de disparo no fiable. |
| RTT | 3, unreliable | ping/pong: duración calculada en un solo reloj cliente. No compara relojes de hosts. |

Un rechazo de intención no consume secuencia. Máximo una intención aceptada por
peer y tick. El servidor conserva el último movimiento por un máximo de 250 ms;
después deja de mover/disparar. Jump/reload son pulsos consumidos. El servidor
simula a 60 Hz, aplica gravedad y colisiones y hace raycast de impactos desde la
posición autoritativa, con cadencia 180 ms, cargador 12, recarga 1.4 s, daño 25,
vida 100 y respawn 3 s. No recibe posiciones, vida, munición ni impactos del cliente.

Los snapshots se interpolan exponencialmente; el mouse local actualiza la cámara
inmediatamente. **No hay predicción de movimiento, reconciliación ni lag
compensation todavía**. La latencia de movimiento es perceptible y debe medirse
en la LAN real. Las colisiones usan física Godot, no el modelo cardinal C previo.

Desconexión elimina jugador/entrada/detector. La partida sigue con el superviviente.
Conexión sin respuestas durante 8 s retorna al menú con aviso. El cierre del
cliente que inició HOST detiene sólo su PID de servidor. Para persistencia
independiente se usa `./game-server --development`.

## Admisión: límite vigente

Único perfil jugable: `development_unattested`, UI `NOT_ATTESTED_DEV`. Requiere
`--development` en servidor. Sin esa opción el servidor sale con código 2.
No existe mensaje `attestation=passed`, token aceptado desde cliente ni modo
protegido desbloqueado artificialmente. **La integración con el verificador
TPM/IMA está pendiente.** ENet aquí no aporta confidencialidad/autenticación
criptográfica de host; no presentar este modo como seguro frente a LAN hostil.

La integración posterior debe obtener la decisión por un canal autenticado de
servidor, ligada a instancia de servidor, sesión, identidad del peer y challenge;
con TTL local, consumo único, reatestación y revocación. Una Quote válida aislada
no satisface ese contrato. Mantener attestor/verifier Python/C independientes.

## Telemetría

`arena-observation/1`, JSONL del servidor, contiene sesión aleatoria, ID de peer,
tick, tiempo monotónico **del servidor**, yaw/pitch, error angular al objetivo
visible, delta y resultados de la heurística. No incluye nombre del sistema,
procesos ajenos ni variable del simulador. Máximo 200000 observaciones por arranque;
los eventos de alerta se guardan aparte en el mismo archivo. Sin rotación continua.

`arena-ground-truth/1`, sólo cliente, registra cambios del simulador y último tick
servidor observado. No se envía al servidor. El análisis compara etiquetas después
de ejecutar el detector y excluye transiciones por incertidumbre de red. Un peer
ID es seudónimo de sesión, no identidad permanente.

## Diseño de integración propuesto

La [ADR 0010](adr/0010-attestor-peer-binding.md) propone el vínculo attestor–peer,
protección de todo el tráfico ENet, IPC y lifecycle. Su [matriz de aceptación](development/ma-010-validation.md)
distingue pruebas existentes de E2E pendientes. Es una propuesta MA-010: no
modifica el contrato/runtime vigente ni habilita protegido en esta revisión.
