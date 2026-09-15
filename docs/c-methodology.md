# Guía de desarrollo C

## Cambios y revisión

Mantener cambios pequeños con entrada, salida, errores y criterio de aceptación
explícitos. Reproducir el fallo antes del parche cuando sea posible y revisar el
diff junto a los resultados. Las pruebas deben ejecutar código real y detectar
regresiones de comportamiento, sin duplicar su implementación.

## Código

- Mantener C11 y los avisos de CMake; verificar Release con `-Werror`.
- Definir quién posee cada socket, buffer e hilo. Liberar recursos en éxito y
  error, sin liberar dos veces ni usar referencias después del cierre.
- Validar longitudes antes de restar, indexar, convertir a tipos más pequeños o
  deserializar. No consumir la salida de un parser que devuelve error.
- Inicializar antes de leer. Preferir un único propietario del estado; evitar
  tablas auxiliares que duplican datos sin aportar una función comprobable.
- Comprobar retornos de sistema y tratar EINTR, lecturas parciales y EOF.
  Un fallo de entropía debe rechazar la sesión, nunca generar un valor constante.
- Comparar direcciones por familia, IP y puerto, sin depender del relleno de
  `sockaddr_in`.
- Definir secuencias, wraparound, retransmisiones y expiración mediante pruebas
  observables contra el servidor.
- Mantener JSON válido en los logs y evitar secretos o datos ajenos al ensayo.

## Protocolo y portabilidad

El contrato actual tiene cabecera de 16 bytes, datagramas de hasta 128 bytes y
payloads little-endian codificados explícitamente, sin copiar estructuras nativas
a la red. El contrato v2 tiene fixtures independientes. Linux está ejecutado;
Windows está compilado con MinGW y mantiene validación runtime pendiente.

Todo cambio incompatible necesita una versión y casos de rechazo definidos.
Las pruebas sobre procesos propios no acreditan aceptación de un servicio externo.

## Verificación

```bash
python3 scripts/verificar-build.py
python3 scripts/verificar-integracion.py --sessions
```

Para cambios de memoria y recursos, ejecutar además `--sessions --sanitize` en
un entorno con AddressSanitizer y UBSan disponibles. Comprobar respuestas exactas,
rechazos y estado observable después del error. Limitar las esperas y terminar
sólo procesos creados por la prueba. Los detalles están en [pruebas](../tests/README.md).

Los builds y resultados locales se excluyen de Git. La documentación describe
uso, diseño, decisiones y fuentes; no sustituye las pruebas del código.
