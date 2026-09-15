# 0002 — Extender el binario con procedencia y cierres asociados a sesión

Se conserva el código UDP y se implementa `lab-udp/2`. Adoptar ahora el JSON
`lab-bridge/1` propuesto exigiría reemplazar el contrato y añadir una biblioteca
JSON sin resolver por sí mismo sesiones, autenticación ni procedencia. La opción
binaria permite reutilizar el servidor, sus pruebas y el adaptador.

La versión 2 es incompatible con v1: RST pasa a 60 bytes de payload y BYE a 24,
ambos con sesión de 16 bytes. Se rechaza v1 explícitamente. Todos los enteros del
payload se codifican little-endian; ninguna estructura nativa se copia a la red.
La cabecera sigue teniendo 16 bytes y el datagrama, como máximo, 128.

Nuevos tipos: REQUEST (0x40, 44 bytes), OBSERVATION (0x41, 104) y DECISION (0x42,
28). El layout exacto y sus fixtures están en `lab/contracts/evidence.c` y
`tests/evidence_tests.c`. Incluyen sesión, request_id, secuencia, tipo, origen,
instancia, sujeto y clase de evidencia. REQUEST liga la instancia al nonce HELLO.
Sólo se acepta `self_reported_lab`; una política que requiera atestación rechaza.
Rechazar no modifica la solicitud pendiente ni consume la secuencia.

Nonce HELLO: cualquier valor binario salvo todo cero; retransmitir el mismo HELLO
activo devuelve el mismo ACK y no renueva el plazo. Otro peer con ese nonce activo
se rechaza. Las instancias nuevas usan nonces nuevos. La ventana admite adelanto
8 e historia 16; UINT32_MAX exige terminar y renovar la sesión, sin wraparound.

Para trabajadores supervisados se enmarcan registros binarios por longitud
uint32 big-endian, límite 256 bytes y plazo absoluto de lectura de 4 segundos.
Un trabajo contiene REQUEST, opcionalmente seguido de OBSERVATION Linux. La salida
conserva esa observación y añade otra nativa. No es JSON ni `lab-bridge/1`.
TLS 1.3 mutuo usa `ssl` de Python/OpenSSL, certificados de una CA dedicada y
verificación de nombre del servidor; nunca cambia origin_os. El supervisor limita
cuatro trabajos y un trabajo por proceso/conexión. EOF, tamaño inválido o error
del trabajador son fallo; no hay reanudación de peticiones al reconectar.

Quedan externos a esta decisión la aceptación comercial, la atestación real y la
gestión de VM. Un digest del archivo temporal describe la lectura de ensayo.
