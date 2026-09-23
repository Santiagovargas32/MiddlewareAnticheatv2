# Pruebas del laboratorio

Compilar con los comandos del [README](../README.md). Los verificadores usan
procesos y recursos propios, esperas máximas y resultados JSON mediante `--output`.
Un bloqueo de entorno es fallo o BLOCKED, nunca una aprobación por omisión.

| Comando | Cobertura |
| --- | --- |
| `python3 scripts/verificar-build.py` | Release -Werror; contrato, política/fuzz y errores de recursos; puertos inválidos |
| `python3 scripts/verificar-integracion.py --sessions` | Suite de sesiones original migrada a v2 |
| `python3 scripts/verificar-integracion.py --direct` | Nonces, ventanas completas, UINT32_MAX, tráfico continuo, malformed/oversize, cliente C, 13 fallos nativos, respuestas tardías, política y capacidades |
| `python3 scripts/verificar-integracion.py --via-adapter` | Misma suite y fallos adicionales de pérdida, retraso, duplicación, capacidad, colas, parada y reinicio |
| `python3 scripts/verificar-capacidades.py` | File/proc/sync reales, digest independiente, plazos, fallo de salida y muerte del padre |
| `python3 scripts/verificar-puente.py` | Dos trabajadores C Linux sobre TLS mutuo; identidad, framing, conservación y rechazo de origen Windows ficticio |
| `python3 scripts/verificar-cli.py` | Ciclo de servicio, idempotencia, conflicto de puerto y estado antiguo |
| `python3 scripts/verificar-windows.py` | Sólo cross-build PE con MinGW, hashes y DLLs; runtime Windows BLOCKED |
| `python3 scripts/verificar-admision.py --inspector build-tpm/lab_quote_inspect` | Registro por sesión/conexión, roles TLS, replay, caducidad, PCR, revocación concurrente y CLI; firmas software sin TPM físico. Incluido en CTest con LAB_TPM=ON. |

CTest incluye fixtures independientes y 2.560.000 llamadas acotadas al parser de
payloads, con buffers de red desalineados y destinos nativos alineados. El test de
recursos fuerza EMFILE y EAGAIN en su propio proceso y comprueba descriptores al
terminar. `server_random_fault.c` sólo se enlaza en la variante de prueba para
inyectar EINTR, lecturas parciales y fallo de entropía.

Añadir `--sanitize` a `verificar-integracion.py` activa ASan/UBSan también durante
CTest. No se deshabilitan comprobaciones si faltan runtimes; véase la alternativa
con bibliotecas locales en el README. Las suites de capacidades/TLS usan el
`--binary` o `--build` indicado: para sanitizarlas, proporcionar un build con esos
instrumentadores y su entorno de bibliotecas.

Las cifras de la demo son tiempos de trabajo completos, incluyendo arranque del
proceso y protocolo; RSS y FDs son muestras locales. La prueba TLS identifica
ambos trabajadores como Linux. No atribuir esos resultados a Windows.

## Núcleo de juego local

`game_tests` prueba fixture binaria independiente/desalineada, aislamiento,
movimiento/cadencia/munición/impactos, cierre, pérdida/replay/overflow y 20.000
entradas de parser más 160.000 intentos en historias de estado. Los rechazos se
comparan con el estado previo completo. CHECK permanece activo en Release.

`python3 scripts/verificar-juego.py` ejecuta siete grupos C, valida exactamente
los eventos/estado de `lab_game_demo` y comprueba argumentos/entropía fallida.
Admite `--build-dir build-tpm-sanitize` con los runtimes locales documentados y
`--output results/game-rules-sanitize.json`. No prueba red, motor o runtime Windows.

`python3 scripts/verificar-juego-red.py` añade nueve grupos reales con TLS mutuo,
trabajador C y CLI en procesos separados. Usa certificados temporales, sockets
loopback y plazos. Comprueba estado, aislamiento, cierre, controles privados,
reinicio con instancia nueva, cuota de entradas, timeout y muerte del trabajador.
El CTest `game_network` requiere `openssl` CLI y permiso para escuchar en loopback.
No interpreta un bloqueo del entorno como aprobación.

## Transporte interno MA-012

`python3 tests/gateway_tests.py` prueba codecs, límites, TLS y procesos con
certificados temporales. `python3 tools/verify_gateway.py` ejecuta Godot servidor,
dos clientes y auxiliares reales sobre loopback, reconexión y fallos de IPC/hijo.
`game/tests/gateway_rules.gd` prueba rutas y parser Godot. Los tres gates están en
verify_release; no requieren TPM. [Contrato](../docs/gateway-transport.md) y
[evidencia](../docs/development/ma-012-validation.md); no otorgan permiso protegido.
