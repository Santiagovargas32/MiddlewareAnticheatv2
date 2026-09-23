# Modelo de amenazas del FPS propio

## Fronteras

1. TPM/IMA: evidencia de plataforma y mediciones dentro de una política explícita.
2. Telemetría: evidencia del comportamiento observable en nuestro juego.
3. Autoridad del servidor: cumplimiento de reglas de partida.

Ninguna equivale a ausencia completa de trampas. El cliente, sus archivos y sus
entradas son no confiables. El servidor dedicado, configuración y futuro verifier
son parte de la base confiable. El perfil development no autentica la plataforma.

| Amenaza | Implementado | Límite / pendiente |
| --- | --- | --- |
| Movimiento manipulado | Sólo vector acotado; física, velocidad y colisiones de servidor | Sin predicción/reconciliación; falta fuzzing intensivo y medidas LAN |
| Fire-rate / ammo / health | Cadencia, munición, recarga, daño, vida y respawn del servidor | No cubre fallos del motor ni abuso volumétrico de red |
| Hit spoofing | Raycast servidor; no se aceptan IDs de víctima enviados | Aim sigue siendo intención manipulable |
| Aimbot interno | Snap preciso repetido y tracking preciso acumulan score | Heurística sin calibración humana; movimientos suaves, ruido o tracking intermitente pueden evitar señales |
| Triggerbot | Concepto incluido en alcance | No detector de reacción validado ni simulador específico |
| Packet manipulation | Tipos RPC, peer servidor, límites de entrada, fase y sesión | ENet sin cifrar; LAN hostil fuera del perfil development |
| Replay | Secuencia creciente, sesión aleatoria, una entrada por tick | No sustituye autenticación criptográfica; la sesión viaja sin cifrar |
| Modified client | Manifiesto local detecta cambios contra referencia externa | Un cliente comprometido puede mentir sobre su propio hash; no está ligado a admisión |
| Client impersonation | Asociación al peer y rechazo de nombres duplicados | Nombre no es identidad; falta enrollment y vínculo con sesión autenticada |
| Atestación falsa | Perfil protegido no arranca; no se confía en un booleano cliente | Integración de admisión, TTL, reatestación y revocación pendientes |

## Detector experimental

`aim-v1` observa error angular y cambios de dirección frente a objetivos vivos
visibles por raycast del servidor. Un snap >18° con error <1° suma 18; tracking con
error <0.12° y movimiento angular suma tras 1 s; score decae 0.7/s. Estados:
NORMAL, OBSERVING (20), SUSPICIOUS (45), HIGH_SUSPICION (75). Umbral de alerta
configurable, predeterminado 75. Una anomalía aislada no llega al umbral.

Acciones implementadas LOG_ONLY y WARN. SPECTATE/KICK quedan pendientes; se
posponen hasta medir falsos positivos. La etiqueta HIGH_SUSPICION es experimental,
no una atribución definitiva de cheats. El toggle F8 nunca entra en la API del
detector. Tampoco se inyecta, inspecciona ni modifica otro proceso o juego.

Las pruebas sintéticas comprueban propiedades del detector, no su precisión con
jugadores humanos. Faltan sesiones normales reales, tamaños muestrales,
calibración por conjunto separado y evaluación fuera de muestra. No publicar
precision/recall si no hay etiquetas comparables. Cuantificar también coste CPU,
bytes/s y latencia de detección; actualmente tick/detector µs y RTT son mediciones
operativas iniciales, no un benchmark representativo.

## Diseño de integración y transporte interno

La [ADR 0010](adr/0010-attestor-peer-binding.md) está aceptada como base experimental.
MA-011 conserva la frontera development. [MA-012](gateway-transport.md) añade un
harness interno con todo ENet sobre mTLS, IPC heredado y asociación del certificado
con el endpoint real; no conecta arena-admission/1 ni concede permiso de juego.
El FPS público conserva su protocolo y rechazo de protegido. La
[evidencia MA-012](development/ma-012-validation.md) detalla negativos/límites;
la [matriz completa](development/ma-010-validation.md) sigue pendiente para
MA-013/014 en barrera, guard/epochs, renovación, rollover y revocación medida.
