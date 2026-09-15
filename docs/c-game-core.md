# 0005: núcleo autoritativo C e intenciones de juego

Estado: núcleo local y continuación TLS de laboratorio implementados, 2026-09-13.
Continúa [alcance vigente](../README.md). M0.1, M1.1, M3.1 y M7.1/M7.2
avanzan de forma parcial; no selecciona motor ni completa admisión atestada.
La sección final distingue el flujo de red real de la primera simulación local.

## Alcance y propiedad

`lab/game/game.c` es una biblioteca C11 sin sockets, reloj, heap ni dependencias
criptográficas. El servidor posee el estado y llama a `game_advance` por tick;
el cliente no proporciona tiempo ni posición. La demo avanza ticks virtuales:
no mide latencia ni implementa un scheduler en tiempo real.

Dos jugadores, arena vacía 2D de ±10.000 mm, movimiento cardinal de 100 mm por
tick nominal de 50 ms. No hay diagonal, salto, aceleración, recarga ni respawn.
Un comando aceptado por jugador y tick; la espera no acumula crédito. La futura
red debe acotar colas y descartar intenciones caducadas: este núcleo no detecta
la antigüedad de un comando nuevo retenido por el transporte.

El servidor calcula orientación, alcance cardinal de 2.000 mm, impactos de 25 HP,
vida inicial 100 y cuatro balas. Disparos separados por cuatro ticks. No acepta
objetivo, impacto, daño ni puntuación del cliente. Otro jugador vivo ocupa su
posición. El orden de llamadas determina el orden de acciones dentro del tick;
un scheduler justo y compensación de latencia quedan pendientes de integración.

## Modelo de amenazas de este incremento

Activos: estado de partida, munición/vida/puntuación, separación de jugadores y
presupuesto de trabajo. Atacante: cliente que controla bytes, orden y ráfagas.
Servidor, mapeo de identidad a slot y su scheduler son de confianza. El estado
C sólo se modifica mediante API por un único hilo propietario; no se copia de red.

| Amenaza | Regla y prueba real | Cobertura pendiente |
| --- | --- | --- |
| Teleport/velocidad por ráfaga | Sin coordenadas cliente; un paso/tick; límites y colisión; `movement` | Scheduler real, caducidad de cola, física del motor |
| Disparo acelerado/munición infinita | Cooldown, munición servidor, rechazo atómico; `combat` | Recarga, armas y reglas específicas del FPS |
| Impactos o puntuación inventados | Objetivo derivado por alcance/orientación; `aiming`, `combat` | Geometría, visibilidad y simulación 3D |
| Suplantar partida/jugador | Match/session comparados con slot del llamador; `isolation` | Autenticar canal, usuario y servidor; IDs no son credenciales |
| Replay, reordenamiento, wrap | Secuencia creciente con saltos; rechazo repetición y UINT32_MAX; `sequences` | Respuesta de estado, reconexión e instancia de proceso |
| Payload inválido/lectura fuera de límites | Tamaño exacto, versión/esquema cerrado; fixture desalineada y 20.000 entradas fuzz | Transporte y cuotas globales |
| Entropía fallida | Demo aborta; prueba de enlace `--wrap=lab_random_bytes` | Enrollment y gestión de claves de producto |
| Cliente/root/kernel comprometido, relay TPM | No cubierto por este núcleo | Modelo de confianza TPM/IMA y límites del producto |
| Aimbot externo, wallhack, hardware de entrada | No se afirma detección | Datos mínimos al cliente y evaluación específica |

Los rechazos describen una acción, no prueban trampa ni producen bans. Jitter y
pérdida se modelan con ticks/saltos de secuencia en las pruebas, no con una red
real; pueden perderse acciones sin justificar sanción. El modelo de amenazas
completo del producto sigue pendiente, especialmente red, admisión y operación.

## Contrato implementado lab-game-input/1

Se conserva `lab-udp/2` sin cambios. Este registro binario nuevo tiene 48 bytes;
no está conectado al listener UDP ni al servicio de atestación. Codificación
explícita, sin casts ni estructuras empaquetadas. Todo rechazo deja intacta la
salida del decoder y el estado de juego.

| Offset | Tamaño | Campo |
| --- | --- | --- |
| 0 | 4 | ASCII LGIN |
| 4 | 1 | Versión 1, otras se rechazan |
| 5 | 1 | Acción: MOVE=1, FIRE=2, WAIT=3 |
| 6, 7 | 1 cada uno | Ejes x/y: NONE=0, NEG=1, POS=2 |
| 8 | 16 | Instancia de partida, binaria no toda cero |
| 24 | 16 | Sesión del jugador, binaria no toda cero |
| 40 | 4 | Secuencia LE32; 0 inválida, UINT32_MAX exige renovación |
| 44 | 4 | Reservado, todo cero |

MOVE exige exactamente un eje no nulo; FIRE/WAIT ambos nulos. Bytes sobrantes,
versión/campos desconocidos y longitudes incorrectas se rechazan. Los saltos de
secuencia permiten pérdida; secuencia menor o igual a la última aceptada se
rechaza, sin aritmética circular. Una acción inválida no consume secuencia ni tick.

El llamador provee IDs frescos obtenidos con entropía real al iniciar partida;
la demo reutiliza `lab_random_bytes` y falla sin respaldo constante. Slots cerrados
no se reabren en esta versión. El transporte futuro deberá ligar IDs a identidad,
juego, servidor y canal, y versionar cualquier cambio de wire. El tick es uint64
con agotamiento explícito, no wrap. Las constantes actuales son reglas del ensayo,
no parámetros validados para competición.

## Ejecución y evidencia

```bash
cmake --build build --parallel 2
./build/lab_game_demo
python3 scripts/verificar-juego.py --output results/game-rules.json
```

Demo con diez registros JSON: ráfaga/replay/cadencia/cierre rechazados y estado
final comprobado (jugador 0 x=100 mm, dos balas y dos impactos; jugador 1 x=600 mm,
50 HP y sesión cerrada). Prueba independiente de eventos y estado final, siete
grupos C y fallos de argumentos/entropía: nueve grupos en el informe Python.

La simulación no son dos procesos cliente ni un FPS interactivo. Siguiente unión:
seleccionar motor mediante prueba de autoridad, integrar scheduler/canal y adaptar
intenciones/respuestas sin fiarse del estado calculado por el cliente.

## Continuación: red real de laboratorio

Implementado `lab_game_host` (C, un proceso dueño del estado), `game_service.py`
y `game.py serve/client`. La suite ejecuta dos clientes CLI separados y servidor
TLS con trabajador C. Reutiliza el framing de `bridge_transport.py`: longitud
BE32, payload máximo 256 bytes, TLS 1.3 mínimo y verificación mutua. Sólo loopback;
no es un servicio para exponer a Internet.

El operador fija dos certificados distintos. Su huella DER SHA256, después de
verificar la cadena TLS, determina el slot. IDs del payload se cotejan además en
C; un cliente no puede seleccionar el slot ni enviar controles del supervisor.
El perfil implementado es `server_rules_v1`: no exige ni declara atestación TPM.
Se requiere que ambos jugadores estén conectados para actuar, evitando atacar un
jugador aún no conectado. Desconectar termina el slot hasta iniciar nueva partida.
No hay reconexión automática, lobby, respawn ni revocación dinámica de certificados.

`scripts/game_service.py` asigna ticks desde su propio reloj monotónico, nominalmente
cada 50 ms, al procesar entradas. No se acumula movimiento ni se avanza simulación
en un hilo de render. Las peticiones al trabajador y sus respuestas se serializan.
Un timeout o cancelación de un intercambio invalida el trabajador para evitar
asociar una respuesta tardía con otra petición; no se reinicia automáticamente.

El pipe privado recibe 50 bytes: operación y slot de un byte cada uno, seguidos de
48 bytes. Operaciones: 1=intención, 2=tick LE64 y resto cero, 3=cierre y 4=consulta
con payload cero. El cliente TLS sólo puede enviar los 48 bytes `LGIN`; no estos
sobres. El proceso rechaza EOF parcial, slot inválido, control desconocido y reloj
hacia atrás, y falla al escribir salida. La CLI gestiona sólo su trabajador hijo.

Respuesta `lab-game-session/1`: registro LGST de 80 bytes. Offsets 4/5/6/7:
versión 1, código de resultado del enum C, slot y perfil 1. Tick LE64 en 8,
secuencia LE32 en 16, partida en 20 y sesión del receptor en 36. En 52 y 64:
x/y LE32 con signo, HP, munición, impactos y bajas de cada jugador (12 bytes).
En 76 máscara de slots abiertos y tres bytes reservados cero. El hello es un
estado con secuencia 0. Errores del supervisor: LGRE más un byte, según `ERRORS`
en `game_service.py`; no son una aprobación. Los clientes cotejan partida,
sesión, slot y secuencia de cada respuesta. Un cambio incompatible exige versión.

Límites: cuatro handlers TLS aceptados activos, dos identidades, una conexión por
slot, 256 entradas/conexión, 2 s por trama inactiva y 30 s de ventana de lectura
por sesión. Una operación ya recibida puede terminar dentro de su plazo de IPC;
no se afirma una caducidad atómica dentro de C. IPC y envío tienen plazos de 2 s.
La aplicación no limita globalmente handshakes TCP/TLS previos al handler;
protección pública frente a DoS, colas caducadas y cuotas globales siguen pendientes.

Nueva evidencia: `results/game-network.json` y `results/game-network-sanitize.json`,
nueve grupos. CTest final: Release 9/9; TPM + ASan/UBSan 11/11. Se corrigió una
cancelación durante cierre TLS que impedía eliminar la tarea del registro; la
prueba exige proceso terminado y registro vacío. Certificados de prueba eliminados.
PE del trabajador compilado; supervisor y clientes ejecutados sólo en Fedora Linux.

```bash
python3 scripts/verificar-juego-red.py --output results/game-network.json
```

Este comando crea credenciales efímeras, ejecuta las pruebas y la demo entre
procesos y limpia lo creado. Los tests no aprovisionan certificados para uso futuro.
Para sesiones manuales con certificados propios, consultar `game.py serve --help`
y `game.py client --help`. Terminar el servidor en primer plano con Ctrl+C.
