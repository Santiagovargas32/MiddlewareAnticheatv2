# Servicio de admisión por conexión — arena-admission/1

Incremento posterior a v0.1.0. [session_admission.py](../scripts/session_admission.py)
expone un registro de permisos sobre TLS 1.3 mutuo, reutilizando el verificador
[lab-attest/1](tpm-attestation.md). **Todavía no controla el tráfico ENet de Godot**;
el FPS conserva su arranque exclusivo `--development`.

## Identidades y alcance

El operador configura dos roles, identificados por SHA256 del certificado TLS
en formato DER:

- `controllers`: servidores de juego autorizados para registrar, consultar y
  revocar sus propias conexiones.
- `attestors`: clientes autorizados para solicitar desafíos y presentar evidencia
  de sus conexiones, cada uno con su AK pública fijada por el operador.

Un certificado firmado por la misma CA no recibe permisos automáticamente.
Los roles son disjuntos. El servicio verifica la firma contra la AK configurada;
la asociación entre ese certificado y esa AK depende del operador. No prueba EK,
origen hardware, exclusividad de la clave ni ausencia de cheats. Sin `pcr_policy`,
se verifica la selección PCR 0/7 y el digest firmado, sin aprobar sus valores.

El registro genera `instance_id`, `admission_id` y `connection_id` aleatorios.
Cada permiso queda ligado además a `game_session_id` (32 hex), `peer_id`
(entero entre 2 y 2147483647), `controller` y `attestor` (64 hex).
El servidor deberá guardar la respuesta junto a la conexión real y comprobar
todos esos campos al consultar. `peer_id` sólo tiene sentido dentro de su partida.

## Ejecutar el servicio

Compilar con `LAB_TPM=ON` siguiendo el [README](../README.md). Preparar fuera de
Git una CA, certificado/clave del servicio con SAN correcto, credenciales separadas
de servidor de juego y attestor, y la AK pública obtenida por un canal de confianza.
No compartir claves privadas. Para calcular una huella:

```bash
openssl x509 -in controller.crt -outform DER | openssl dgst -sha256
```

Crear `.tmp/admission/roles.json`, sustituyendo las dos huellas de ejemplo y
colocando `ak-public.pem` junto al fichero. Las rutas de AK/política son relativas
al directorio del JSON, no al cliente de red:

```json
{
  "controllers": ["<SHA256 DER del certificado del servidor de juego>"],
  "attestors": {
    "<SHA256 DER del certificado del attestor>": {
      "ak_public": "ak-public.pem"
    }
  }
}
```

Opcionalmente añadir `"pcr_policy": "pcr-approved.json"` dentro de la entrada
del attestor, usando una referencia [pcr-reference/1](tpm-attestation.md) aprobada
por el operador. La configuración se carga al arrancar; cambiarla requiere
reiniciar y registrar de nuevo las conexiones.

```bash
python3 scripts/session_admission.py \
  --config .tmp/admission/roles.json \
  --inspector build-tpm/lab_quote_inspect \
  --cert .tmp/admission/server.crt --key .tmp/admission/server.key \
  --ca .tmp/admission/ca.crt --host 127.0.0.1 --port 9445
```

Para otro host, el operador elige explícitamente la dirección de escucha y la
conectividad de ese puerto. El cliente verifica el SAN del servicio mediante
`--server-name`; no deshabilitar esa comprobación. El servicio no abre el firewall
ni modifica permisos TPM. SIGINT/SIGTERM detiene la escucha y espera las tareas
propias; no deja verificaciones en segundo plano tras su salida normal.

## Mensajes y ciclo

Cada conexión TLS admite una petición y una respuesta: longitud unsigned de
4 bytes big endian, seguida de JSON UTF-8, máximo 16384 bytes. Se rechazan campos
extra, claves duplicadas, números no finitos y profundidad excesiva. Todas las
peticiones incluyen `protocol_version: "arena-admission/1"` y `operation`.

| Operación | Rol | Campos adicionales | Resultado |
| --- | --- | --- | --- |
| `register` | controller | `game_session_id`, `peer_id`, `attestor` | `binding`, estado inicial sin permiso |
| `status` | controller propietario | `admission_id` | Estado y duración restante |
| `revoke` | controller propietario | `admission_id` | `REVOKED`, sin permiso |
| `challenge` | attestor asociado | `admission_id` | `binding`, `salt`, `challenge` lab-attest/1 |
| `submit` | attestor asociado | `admission_id`, `evidence` lab-attest/1 | Estado y resultado del verificador |

Ejemplo de registro en `.tmp/admission/request.json`, sustituyendo la huella:

```json
{
  "protocol_version": "arena-admission/1",
  "operation": "register",
  "game_session_id": "0123456789abcdef0123456789abcdef",
  "peer_id": 2,
  "attestor": "<SHA256 DER del certificado del attestor>"
}
```

```bash
python3 scripts/session_admission.py --request .tmp/admission/request.json \
  --host 127.0.0.1 --port 9445 --server-name localhost \
  --cert .tmp/admission/controller.crt --key .tmp/admission/controller.key \
  --ca .tmp/admission/ca.crt
```

Un error devuelve `allow: false` y `error`; el cliente CLI sale con código 1.
Una respuesta válida `REGISTERED`, `DENIED` o `REVOKED` tiene código 0: éste sólo
indica intercambio correcto, **no autorización para jugar**. La integración deberá
exigir `allow == true`, binding esperado y vigencia; fallo de transporte significa
sin permiso. `status` es la fuente de autoridad; la respuesta de `submit` presentada
por un jugador no es un token de admisión.

El desafío contiene un nonce igual a
`SHA256("arena-admission/1" || 0x00 || binding_JSON_canónico || 0x00 || salt_bytes)`.
El JSON canónico ordena claves, usa ASCII sin espacios ni escapes innecesarios;
el binding sólo contiene los identificadores ASCII y el entero validados.
`salt` tiene 32 bytes aleatorios representados en 64 hex minúsculas. El attestor
deberá contrastar el binding con su conexión autenticada y calcular este nonce
antes de producir una Quote con `qualification(challenge)` de lab-attest/1.
No se cambia el formato TPM ni el contrato del verificador previo.

Valores iniciales del registro: máximo 256 bindings, vida absoluta 300 s,
desafío 10 s y permiso 30 s desde la emisión del desafío. Se usa el reloj monotónico
del servicio; nunca se comparan relojes monotónicos de dos máquinas. `remaining_ms`
es una duración orientativa al responder: una revocación posterior la invalida.
No hay notificaciones push de revocación en este incremento.

Cada desafío admite un intento. Pedir renovación suspende el permiso anterior;
una verificación inválida deja `DENIED`. No se pueden sustituir desafíos pendientes
ni verificaciones en curso. Tras expirar un desafío se puede pedir otro. Un
resultado tardío no prolonga la concesión y una revocación concurrente prevalece.
Tras 300 s hay que registrar otra conexión lógica; reconectar o reutilizar peer
requiere revocar el registro anterior y obtener un nuevo `connection_id`.
Reiniciar pierde permisos y cambia la instancia, por lo que exige registro nuevo.

El servicio admite como máximo ocho handlers activos y cuatro verificaciones
costosas concurrentes, con plazos de lectura y subprocess. La saturación produce
rechazo/cierre, nunca `ALLOW`; no constituye protección volumétrica de red.

## Comprobaciones y siguiente integración

```bash
python3 scripts/verificar-admision.py --inspector build-tpm/lab_quote_inspect
ctest --test-dir build-tpm -R session_admission --output-on-failure
```

La suite usa firmas software independientes, relojes controlados, carreras con
sincronización explícita, certificados temporales, TLS loopback y CLI en procesos
separados. No accede a `/dev/tpm*`. CTest la incluye con `LAB_TPM=ON` y el workflow
existente la ejecutará en las próximas propuestas de cambio.

Falta enlazar el attestor con la conexión autenticada del juego, consultar y hacer
cumplir estos permisos desde Godot, renovar durante la partida y verificar caída,
revocación y reconexión extremo a extremo. La [continuación](next-steps.md)
describe los criterios de aceptación antes de habilitar el modo protegido.

## Diseño de integración aceptado, pendiente de implementar

La [ADR 0010](adr/0010-attestor-peer-binding.md) propone el vínculo attestor–peer,
protección de todo el tráfico ENet, IPC y lifecycle. Su [matriz de aceptación](development/ma-010-validation.md)
distingue pruebas existentes de E2E pendientes. MA-010 está aceptada como base
experimental. MA-011 extrajo la frontera development; no modifica arena-admission/1
ni lo enlaza todavía al peer Godot. Túnel/IPC, enforcement y lifecycle siguen
pendientes y protegido permanece cerrado.
