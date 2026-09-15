# Guía LAN de v0.1.0

El procedimiento completo y vigente está en el [README](../README.md): descarga,
preparación de Godot, PC A, PC B, firewall temporal, controles, configuración,
telemetría, TPM opcional y empaquetado.

Para validar la LAN física, comprobar en ambos Fedora: conexión por IP, lobby y
READY, movimiento y colisión, disparos/daño, recarga, muerte, respawn, marcador,
fin de partida y continuidad al cerrar un cliente. Registrar versión, configuración,
resultados y fallos. Probar F8/adquisición repetida y conservar por separado
telemetría de servidor y ground truth de cada cliente.

El perfil debe mostrar `NOT_ATTESTED_DEV`. No interpretar permisos TPM concedidos
o una Quote aislada como admisión atestada del FPS. La prueba física entre equipos
queda pendiente de ejecución por el operador; las pruebas loopback no la completan.
