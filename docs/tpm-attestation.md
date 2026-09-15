# 0003: desafío TPM separado y confianza delimitada

Se implementa `lab-attest/1`, separado de `lab-udp/2` y de la propuesta
`lab-bridge/1`. Una Quote y su firma no caben en 128 bytes: ampliar UDP añadiría
fragmentación, compatibilidad y autenticación nuevas. Reutilizamos el contexto
TLS 1.3 mutuo de `bridge_transport.py`; conservamos los trabajadores C y UDP.

JSON UTF-8 con longitud de 32 bits en orden de red, máximo 16 KiB; biblioteca
estándar Python 3.11+. Rechaza claves duplicadas, números decimales/NaN, Unicode
inválido, profundidad mayor de cuatro, bytes sobrantes y esquema de petición
abierto. La cabecera y cuerpo comparten plazo absoluto. Una conexión admite
solicitud de desafío y una evidencia; cuatro conexiones activas y 64 sesiones
incluidas sus marcas de consumo. El plazo de evidencia es TTL + 1 s; recibirla
antes no evita el rechazo si termina la verificación después del TTL.

El desafío contiene versión, sesión de 128 bits, nonce de 256 bits, fechas en
milisegundos, política, evidencia solicitada y SHA256 de la AK fijada. La
qualification es SHA256 de dominio `lab-attest/1\0`, sesión, nonce, fechas
big-endian de 64 bits, SHA256 de policy_id y digest de AK. El servidor conserva
su copia; utiliza reloj monotónico propio para caducidad. Las fechas remotas no
se usan como autoridad temporal. La evidencia sólo contiene versión, sesión y
quote/signature/pcrs en base64; no acepta claves ni rutas remotas.

La AK se provisiona fuera de banda y se copia al iniciar el verificador. El
ensayo físico crea una AK local transitoria antes del desafío: esto es confianza
del operador, **no validación de certificado EK ni enrollment de producción**.
La clave no se acepta automáticamente desde una respuesta remota.

`lab_quote_inspect` utiliza el unmarshalling de TPM2-TSS 4.1.3 (BSD-2-Clause).
`tpm2_checkquote` 5.7 (BSD-3-Clause) comprueba firma y PCR con la AK fijada.
La qualification declarada permite separar verificación criptográfica de su
comparación con el desafío esperado. Se comprueban magic, tipo Quote, longitudes,
consumo completo y selección SHA256 PCR 0/7. Las dependencias se obtienen como
paquetes del sistema; las cabeceras locales extraídas no se modifican ni publican.

Cada desafío tiene un único intento criptográfico. Un schema inválido o cliente
ajeno no lo consume; payload criptográfico inválido sí. La reserva es atómica
ante concurrencia. No cambia la semántica de rechazos del protocolo UDP.
Marcas de consumo se retienen hasta 60 s después del vencimiento, dentro del
límite de 64; reiniciar pierde las sesiones y obliga a nuevos desafíos.

Los resultados separan validez criptográfica, frescura, política e identidad TPM.
`ALLOW` exige firma/digest/nonce/selección válidos. `DENY` cubre evidencia inválida,
replay, sesión desconocida y expiración; `INDETERMINATE` cubre errores de herramientas.
PCR 0/7 **no tienen baseline de valores aprobados**: esta política comprueba el
protocolo y la posesión de la clave, no el estado de arranque aceptable.

| Amenaza | Cobertura actual | Límite |
| --- | --- | --- |
| Repetición o traslado de Quote | Nonce, sesión, AK y política ligados; consumo atómico y TTL | No continuidad tras terminar el desafío |
| Sustitución de clave | AK fijada fuera de la petición | No EK/cadena de fabricante ni atributos AK atestados |
| Red no confiable | TLS mutuo con CA y nombre verificados | Un certificado no acredita integridad del host |
| Payload malformado/agotamiento | Límites de tamaño, sesiones, concurrencia y tiempos; parser mantenido | Sin protección distribuida frente a denegación de servicio |
| Root/kernel comprometido, relay a otro TPM | Ninguna garantía de host íntegro | No vinculación fuerte entre TPM, proceso de juego y ejecución |
| TOCTOU, periféricos/DMA/cheats externos | Fuera de cobertura | Una Quote no prueba ausencia de cheats |
| Logs IMA manipulados | Pendiente replay y cotejo PCR | La lista local no basta y no se transmite todavía |

Para autorizar un juego bajo un perfil que exige atestación se necesita Quote
física reproducible, enrollment más fuerte y política justificable. La decisión
[alcance vigente](../README.md) permite desarrollar por separado un perfil
explícito de reglas de servidor sin TPM; no equivale a este perfil atestado. Evaluar
Keylime para esa fase: este experimento mínimo permite comprobar el contrato y
las primitivas, pero no sustituye su enrollment, verificación IMA y operación.
No se ha ejecutado una PoC Keylime ni se afirma que toda esa parte esté resuelta.

## Incremento comprobado con el TPM del host

Ocho casos físicos pasan con `/dev/tpmrm0` y AK de laboratorio: éxito, replay,
firma/PCR/nonce alterados, sesión anterior tras reinicio y referencia PCR que
coincide o diverge. La referencia del ensayo se observa localmente y se destruye;
no se registra como baseline aprobado. La identidad de fabricante/EK sigue pendiente.

`--pcr-policy` carga un JSON local cerrado `pcr-reference/1` con exactamente los
PCR SHA256 0 y 7. No admite valores desde la solicitud. El digest de sus 64 bytes
forma parte de `policy_id`, ligado al desafío. La copia cargada es inmutable;
cambiar el fichero exige reiniciar y descarta las sesiones previas. Se distingue
`pcr_reference_validity` (`not_configured`, `not_evaluated`, `matched`, `mismatch`).
Una divergencia con firma y nonce válidos produce `PCR_REFERENCE_MISMATCH`.
La política por defecto conserva el comportamiento de laboratorio anterior;
ninguna de ellas queda conectada al servidor UDP ni concede admisión a un juego.

Se corrigió la limpieza del ensayo: los archivos `.ctx` de objetos no son los
archivos de sesión que admite `tpm2_flushcontext`. Bajo el gestor de recursos,
la vida de los objetos pertenece a la conexión y sus procesos se esperan con
plazo; los archivos guardados pertenecen al directorio temporal y se eliminan en
éxito y excepción. No se ejecuta un flush global ni se persisten handles. Véase
[la documentación oficial de flushcontext](https://tpm2-tools.readthedocs.io/en/latest/man/tpm2_flushcontext.1/).

El diagnóstico IMA ahora abre la ruta canónica del kernel y sólo alias de lista
permitidos dentro del directorio. Inicialmente devolvía EACCES: el permiso del TPM no concedía lectura de IMA.
El operador concedió después lectura de dos listas; el parser C y replay local
SHA256 coinciden con PCR 10 estable. La Quote del log y su política siguen
pendientes; véase [estado de esta versión](release-status.md). No se cambió la política IMA.

## Perfil PCR10 y log preparado — 2026-09-13

Se compone `ImaQuoteVerifier` con el verificador de firma/nonce y el replay C.
`pinned-ak-ima-chain-v1` requiere exactamente SHA256 PCR10; la selección esperada
la fija el operador, no la evidencia. La ruta del log también es configuración
local, sin seguir un enlace final ni admitir rutas en solicitudes. La clase se
prueba mediante sesiones propias; no se añade un endpoint de subida.

El PCR reconstruido debe coincidir con el PCR firmado, además de cumplir firma,
nonce, selección y caducidad. Así se comprueba el vínculo criptográfico bajo la AK
fijada, pero no la legitimidad de los archivos medidos ni la identidad del TPM.
`measurement_policy_validity=not_evaluated` sigue explícito. Las pruebas actuales
usan firmas software y aceptan logs locales mayores de una trama sin cambiar
`lab-attest/1`; el transporte remoto requiere decisión y validación separadas.

Se revisaron [seguridad Keylime 7.14.3](https://keylime-docs.readthedocs.io/en/latest/design/security.html)
y [su implementación TPM 7.14.3](https://raw.githubusercontent.com/keylime/keylime/v7.14.3/keylime/tpm/tpm_main.py).
Su evaluación de enrollment/IMA se mantiene como próximo trabajo; no hay PoC
instalada ni se afirma compatibilidad de nuestros mensajes con sus interfaces.
