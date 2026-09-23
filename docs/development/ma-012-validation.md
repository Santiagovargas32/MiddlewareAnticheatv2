# MA-012 — Evidencia de transporte y pendientes

Base: `a9baba8808f655b6cba2061a2071902c74edce20`. Encargo 2026-09-22.
[Ficha](tasks/MA-012.md), [contrato implementado](../gateway-transport.md).
Validación local del diff completada el 2026-09-23; no corresponde a main ni a CI
nueva. Estado del paquete: IN_REVIEW, sin publicación ni integración.

## Reproducido durante implementación

- Harness real: Godot servidor, dos Godot clientes, reconexión y sus auxiliares
  Python. Certificados temporales distintos, TLS 1.3 mutuo, cuatro canales ENet y
  tres modos de entrega, identidad obtenida del certificado y endpoint real.
  Ningún contexto obtiene permiso. UDP directo rechazado y puertos cliente
  comprobados como loopback en tablas del kernel.
- 49 comprobaciones Godot de IPC/rutas, con JSON ambiguo, replay/contexto incorrecto,
  identidad ajena, peer reciclado, 8 rutas activas, 256 reservas y overflow.
- 15 grupos Python: TLS/roles/CA/SAN/expiración/ALPN/pin, framing fragmentado,
  tamaños/EOF/deadlines, replay de OPEN/IPC, ACK exacto, reserva de sockets,
  capacidad previa a TLS, ocho canales, heartbeat y backpressure/EOF del padre.
- Datagrama ajeno encolado antes del ACK: descartado, sólo el origen explícito
  llega al servidor. Frame TLS fragmentado retenido 60 ms: observado ~62 ms;
  frame parcial >200 ms cierra (comprobado a 250 ms). Son observaciones locales.
- Presión stderr: anillo limitado a 65536 bytes. Escritura Godot sin lector:
  falla sin bloquear y termina el hijo propio; frame IPC incompleto se cierra.
- Build Release -Werror LAB_TPM=ON y CTest session_admission PASS 1/1, fixtures
  software. No se modifica ni se reimplementa arena-admission/1.

Incidencias corregidas: puerto cliente ENet cero antes de asignación; bind_ip
ignorado con local_port=0 (ahora bind explícito); UDP ajeno ya encolado antes de
connect; consulta de PID después del kill/reap de Godot. La primera fixture de
certificado expirado usó días negativos no admitidos por OpenSSL local; se cambió
a fechas explícitas con openssl ca, compatibles con CI. No se retiraron gates.

## Relación con la matriz protegida

La [matriz MA-010](ma-010-validation.md#matriz-e2e-pendiente) sigue siendo aceptación
del sistema protegido completo, no una lista que estas fixtures conviertan en PASS.

| Casos | Cobertura MA-012 / límite |
| --- | --- |
| T02/T03 | Certificados/pins/roles/CA/SAN/expiración, dos identidades y rechazo de campos extra. Sin permiso ni Quote que transferir. |
| T04/T06 | Endpoint observado ENet, UDP directo rechazado, reconexión real; segundo peer/ruta reciclada y generación mediante fixtures. |
| T05 | Replay de OPEN_ACK entre canales y secuencias IPC; no se afirma un ensayo independiente de captura/replay de ciphertext TLS. La protección de registros es OpenSSL/TLS. |
| T07 | Framing/EOF/parcial/tipos/tamaño/JSON duplicado/profundo y timeout; parsers Python y Godot. |
| T08 | EOF/backpressure Python, stderr saturado, pipe parcial/escritura fallida Godot y limpieza de hijos. Harness PASS al matar el auxiliar con ruta viva: cero rutas restantes y cliente cerrado. |
| T25/T28 parcial | Cuotas, edad/count/bytes de cola, retención parcial, 8 canales, 256 reservas y overflow. No campaña de pérdida TCP/kernel con gameplay/8 jugadores. |
| T01/T09–24/T26–27 y resto de T25/T28 | PENDING para MA-013/014; no register/status/Quote, RPC protegidos, guard, epochs, suspensión/rollover ni medida de revocación. |

LAN física, TPM hardware/IMA/EK y campaña humana no ejecutadas; no son condiciones
para este harness software. MA-015 debe registrar BLOCKED si falta su entorno.
El FPS público sigue sólo development. No hay afirmación de ausencia de cheats.

## Validación final

Entorno: Fedora 44, Python 3.14.7, OpenSSL 3.5.8 y Godot 4.7.2 fijado. Diff contra
la base indicada; la revisión se identifica por los commits que incorporan esta
ficha. Sin cambios C ni contratos C; no se repiten sanitizers C por este diff.

| Comando / comprobación | Resultado real |
| --- | --- |
| python3 scripts/verificar-documentacion.py | PASS, 158 fuentes públicas y enlaces locales, incluidas las notas de cierre |
| python3 tools/verify_release.py | PASS 10/10, conserva los siete gates y añade tres de gateway |
| game/tests/gateway_rules.gd (en verify_release) | PASS 49 checks |
| python3 tests/gateway_tests.py (en verify_release) | PASS 15 grupos, fixtures TLS/software |
| python3 tools/verify_gateway.py (en verify_release) | PASS 12 escenarios con procesos reales |
| python3 tools/verify_game.py --graphical | PASS 6 escenarios automatizados con render real; captura de alerta inspeccionada, sin campaña humana |
| cmake --build build-tpm --parallel 2 y CTest session_admission | PASS 1/1, Release -Werror LAB_TPM=ON |
| python3 scripts/verificar-admision.py --inspector build-tpm/lab_quote_inspect | PASS 14/14, sin TPM físico |
| package_game.py, extracción temporal, hashes y verify_release desde ella | PASS 158 fuentes, ejecutables preservados y 10/10 gates, incluidos los últimos ajustes de parser/poll |
| git diff --check y revisión contra base | PASS; runtime público, detector, física, assets y formatos C preservados |

RTT del harness de la extracción (no juego ni garantía de latencia):


| Cliente | Ecos | p50 / p95 / máximo (ms) |
| --- | --- | --- |
| 1 | 44 | 7 / 8 / 49 |
| 2 | 89 | 7 / 14 / 48 |
| 3 | 43 | 7 / 48 / 49 |

Los gates completos desde extracción incluyen la profundidad de contenedores
vacíos y el límite de bytes procesados corregidos al revisar. Las notas de cierre
posteriores sólo cambian documentación; se vuelve a comprobar inventario/enlaces.
Clone local limpio de `0afaf28f62ffe749633c0abb7a90adc433da6a59`: PASS 10/10.
Incluye AGENTS, workflow, fichas, plantilla y fuentes, sin privados ni results
previos. Comprueba también el último refuerzo del harness: cada eco conserva
canal y modo, y se observan los cuatro canales y tres modos de entrega. Ese
refuerzo se validó tras la extracción inicial y nuevamente en este clone.
El cierre posterior sólo actualiza esta evidencia documental; no cambia runtime.
Paquete final de revisión con notas de cierre: hashes verificados y código
idéntico al clone probado; documentación verificada desde la extracción final.

El primer intento al retomar no pudo crear sockets en el sandbox; se reprodujo
fuera de esa restricción mediante aprobación del entorno y pasó. No se quitaron
verificaciones. Artefactos ignorados: results/release-checks/, gateway-network.json,
ma012-package-validation.json/log y capturas FPS. No publicar credenciales ni
trazas privadas. La CI existente ejecutará los nuevos gates al publicar una PR;
no se ha ejecutado CI nueva ni se ha extendido la autorización anterior de merge.
MA-012 requiere revisión/integración antes de DONE. MA-013/014 y sus medidas de
permiso/lifecycle siguen pendientes; MA-015 requiere su propio entorno físico.
