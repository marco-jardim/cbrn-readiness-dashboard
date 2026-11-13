# Guía de instalación (español de España)

Esta guía es para quienes instalan el CBRN Readiness Dashboard y para los equipos de TI que
autorizan su ejecución. Existe en tres idiomas con la misma estructura:
[pt-BR](install.pt-BR.md), [en-US](install.en-US.md) y [es-ES](install.es-ES.md). El texto de las
notas de primera ejecución del zip (`README-first-run.*.txt`) es más corto y dice lo mismo.

**Versión preliminar — indicadores no validados institucionalmente.** No introduzca todavía datos
reales: vea [data-protection.md](data-protection.md) (en inglés).

## 1. Estado de esta guía

La versión del árbol de código es `1.0.0`. Está **preparada** en el repositorio (con registro de
cambios y guion de prueba manual), pero no se ha marcado ninguna etiqueta (tag); por tanto,
**todavía no se ha publicado ninguna versión y hoy no hay ningún archivo que descargar**. El flujo
de publicación (`.github/workflows/release.yml`) solo se ejecuta cuando se envía una etiqueta
`vX.Y.Z`, construye el paquete y crea una versión en *borrador* (marcada como prelanzamiento
mientras la versión sea inferior a 1.0.0). El flujo nunca se ha ejecutado. Una persona publica el
borrador tras la prueba manual ([smoke-test.pt-BR.md](smoke-test.pt-BR.md), en portugués); hasta
entonces esta guía sigue siendo cierta: no hay ninguna versión publicada.

Todo lo que sigue sobre la descarga describe lo que ese flujo y los scripts de `scripts/` están
escritos para producir. Nada de ello se ha probado con una versión publicada.

Para probar el programa hoy, ejecútelo desde una copia del código fuente (requiere
[uv](https://docs.astral.sh/uv/)):

```text
uv sync --locked --all-groups
uv run cbrn-dashboard --demo
```

## 2. Requisitos

- Windows 10 (versión 1809 o posterior) o Windows 11, de 64 bits (x64).
- Sin derechos de administrador y sin instalador: el programa es una carpeta que se extrae.
- Python y Qt están dentro de la carpeta; no hay que instalar nada más.
- Una carpeta donde Windows permita ejecutar programas (vea la sección 7 sobre equipos restringidos).
- El puesto de trabajo debe usar cifrado de disco completo (por ejemplo, BitLocker). El programa no
  puede comprobarlo.

## 3. Descarga

La página de versiones de `https://github.com/marco-jardim/cbrn-readiness-dashboard` llevará tres
archivos por versión:

| Archivo | Contenido |
|---|---|
| `cbrn-readiness-dashboard-<version>-win-x64.zip` | el programa |
| `SHA256SUMS.txt` | la suma de comprobación SHA-256 del zip |
| `SHA256-FILES.txt` | la suma SHA-256 de cada archivo dentro de la carpeta del zip |

Descargue los tres de la **misma** página de versión. El zip contiene una carpeta,
`cbrn-readiness-dashboard\`, con `cbrn-dashboard.exe`, la carpeta `_internal\`, la carpeta
`licenses\` (textos de las licencias de terceros), las tres notas de primera ejecución y
`portable.ini.example`.

## 4. Verificar la descarga

### 4.1 Suma de comprobación con Get-FileHash

Abra PowerShell en la carpeta de los archivos y ejecute:

```powershell
Get-FileHash .\cbrn-readiness-dashboard-<version>-win-x64.zip -Algorithm SHA256
```

Compare el valor de `Hash` con la línea del zip en `SHA256SUMS.txt`. Deben ser iguales.

### 4.2 Procedencia con gh attestation verify (opcional)

Si tiene la [CLI de GitHub](https://cli.github.com/), puede verificar la atestación de la
compilación:

```powershell
gh attestation verify .\cbrn-readiness-dashboard-<version>-win-x64.zip --repo marco-jardim/cbrn-readiness-dashboard
```

Este paso necesita acceso a la red **de su lado**. El programa en sí sigue sin conexión: no tiene
código de red, ni comprobación de actualizaciones, ni telemetría.

### 4.3 Qué prueban y qué no prueban las comprobaciones

- El `SHA256SUMS.txt` de la misma página de versión prueba la integridad de la transferencia (el
  archivo no se dañó por el camino). No prueba la autenticidad: quien pudiera cambiar el zip en esa
  página podría cambiar también el archivo de sumas.
- La atestación prueba dónde y cómo se ejecutó la compilación. No prueba que el programa sea seguro.
- El ejecutable es **no firmado** (la firma de código es una decisión aplazada).

## 5. Desbloquear y extraer

1. Pulse con el botón derecho en el zip, elija *Propiedades*, marque *Desbloquear* si aparece y
   pulse *Aceptar*. Hágalo **antes** de extraer: el extractor de Windows transmite la marca de la
   web (Mark-of-the-Web) a los archivos extraídos, salvo que el zip se haya desbloqueado antes.
   Otros extractores se comportan de otra manera.
2. Extraiga el zip **completo** a una carpeta donde pueda ejecutar programas. No ejecute el
   programa desde la vista previa del zip del Explorador: allí falla, porque falta `_internal\`.
3. Inicie `cbrn-dashboard.exe` desde la carpeta extraída.

## 6. Primer inicio y SmartScreen

Como el ejecutable no está firmado, Microsoft Defender SmartScreen puede mostrar "Windows protegió
su PC" la primera vez. Elija "Más información" y después "Ejecutar de todas formas", salvo que su
organización lo prohíba; en ese caso consulte a su equipo de TI (sección 7).

## 7. Equipos restringidos (AppLocker, WDAC, Smart App Control)

Para los equipos de TI:

- **Carpeta de extracción.** Cuando AppLocker está activo, sus reglas predeterminadas solo permiten
  programas en la carpeta de Windows, en Program Files y para administradores. Elija una carpeta de
  extracción que su política permita. La compilación en una carpeta está pensada para no necesitar
  nunca ejecutar código desde `%TEMP%`.
- **Comprobar los archivos.** `SHA256-FILES.txt` de la misma versión lista el SHA-256 de cada
  archivo de la carpeta, incluidos los archivos `.pyd` y DLL (los valores que muestra
  `Get-FileHash`); úselo para comprobar cada archivo extraído. `SHA256SUMS.txt` cubre solo el zip.
  Cree sus reglas de autorización a partir de la carpeta comprobada, con las herramientas de
  política de su propia organización. Esas reglas son por archivo y por versión, y deben cubrir
  también los archivos `.pyd` y DLL.
- **Smart App Control** no admite excepciones por archivo. En un equipo donde está activo, el
  programa no firmado puede sencillamente no ejecutarse.
- Solo la firma de código eliminaría la mayor parte de esta fricción. Está aplazada hasta que se
  respondan las preguntas sobre el despliegue.

## 8. Opciones de la línea de comandos

Las opciones son las de `cli.py`. Valen para `cbrn-dashboard.exe` y para `uv run cbrn-dashboard`.

| Opción | Significado |
|---|---|
| `--data-dir PATH` | carpeta que guarda la base de datos y los demás datos de la aplicación |
| `--lang pt-BR`, `--lang en-US` o `--lang es-ES` | idioma de la interfaz solo en esta ejecución (no se guarda) |
| `--self-test` | ejecuta las comprobaciones internas, escribe `selftest.json` en la carpeta de datos y termina |
| `--demo` | abre la base de datos de demostración separada, con datos ficticios, nunca la real |
| `--version` | muestra la versión y termina (véase la nota bajo la tabla) |

`cbrn-dashboard.exe` es un programa de ventanas: no tiene consola. Por eso `--version` no imprime
nada con lo que se pueda contar en un prompt del programa congelado. En una copia del código
fuente, `uv run cbrn-dashboard --version` muestra la versión. La versión también está en el recurso
de versión del ejecutable.

El idioma predeterminado es el portugués de Brasil, sea cual sea el idioma de Windows; se cambia en
el programa y se guarda en `prefs.json` en la carpeta de datos.

## 9. Autoprueba y modo de demostración

```text
cbrn-dashboard.exe --self-test --data-dir C:\Temp\cbrn-selftest
```

La autoprueba nunca abre la base de datos real. Trabaja en una carpeta desechable `tmp\selftest-*`
dentro de la carpeta de datos y solo escribe `selftest.json` junto a ella. El programa de ventanas
no tiene consola, y por eso el resultado es un archivo. El código de salida es 0 cuando todas las
comprobaciones pasan y 1 en caso contrario.

Como el programa es de ventanas, un prompt puede volver antes de que termine la autoprueba. Lea
`selftest.json` (el campo `passed`) solo después de que el programa haya terminado. Un script que
necesite el código de salida debe iniciar el programa de un modo que lo espere, como hacen las
pruebas de empaquetado (lo ejecutan como proceso hijo, esperan y leen el código de salida y
`selftest.json`).

```text
cbrn-dashboard.exe --demo
```

El modo de demostración abre `demo\demo.sqlite3` en la carpeta de datos, un archivo separado con
copias de seguridad propias, lleno de registros ficticios cuyos identificadores empiezan por
`DEMO`. Un aviso permanente lo indica. Vea [demo-walkthrough.md](demo-walkthrough.md) (en inglés).

## 10. Ubicación de los datos y modo portátil

### 10.1 Dónde están los datos

Por defecto: `%LOCALAPPDATA%\cbrn-readiness-dashboard` (por ejemplo,
`C:\Users\<nombre>\AppData\Local\cbrn-readiness-dashboard`). La carpeta contiene
`cbrn-dashboard.sqlite3` (la base de datos), `prefs.json`, `backups\`, `logs\`, `tmp\` y `demo\`.
La descripción completa, las amenazas y los deberes del operador están en
[data-protection.md](data-protection.md) (en inglés).

### 10.2 Elegir otra carpeta

La carpeta de datos se elige en este orden; vale la primera regla que se aplique:

1. la opción `--data-dir`;
2. la variable de entorno `CBRN_DASHBOARD_DATA_DIR`;
3. el modo portátil (sección 10.3);
4. el archivo puntero `%LOCALAPPDATA%\cbrn-readiness-dashboard\location.json`, escrito por el
   programa cuando usted elige otra carpeta después de que la carpeta de datos resultara inutilizable;
5. la carpeta predeterminada de arriba.

### 10.3 Modo portátil

Cambie el nombre de `portable.ini.example` a `portable.ini` y déjelo junto a `cbrn-dashboard.exe`.
Los datos pasan entonces a la carpeta `data\` junto al programa. El programa solo comprueba que
`portable.ini` exista; las claves que contiene no se leen. `--data-dir` y
`CBRN_DASHBOARD_DATA_DIR` tienen prioridad.

**Aviso:** copiar la carpeta del programa copia también los datos.

### 10.4 Carpetas de solo lectura y de red

Si la carpeta de datos o el archivo de la base de datos no se pueden escribir y existe una base de
datos, el programa la abre en solo lectura, muestra un aviso y desactiva toda acción que modifique
datos. Si la carpeta no se puede escribir y no contiene base de datos, el programa lo explica y
ofrece otra carpeta.

El programa avisa cuando la carpeta de datos está en una ruta de red (ruta UNC o unidad asignada),
porque el bloqueo de archivos de SQLite no es fiable en recursos compartidos de red, y cuando está
dentro de una carpeta de OneDrive, porque los datos saldrían del equipo. No use un recurso
compartido de red para los datos. Varias personas solo pueden turnarse en un equipo con una única
cuenta de Windows compartida, o con `--data-dir` apuntando a una carpeta local restringida al
comité; las cuentas de Windows separadas tienen bases de datos separadas.

Un perfil de Windows obligatorio o no persistente descarta `%LOCALAPPDATA%` cuando el usuario cierra
la sesión. En un equipo así, use `--data-dir` con una carpeta local que persista.

## 11. Copias de seguridad

El programa guarda copias simples de la base de datos en `backups\`: una en el primer inicio de cada
día (se conservan las 7 más recientes, nunca menos de 2) y una antes de cada actualización de la
base de datos (se conservan las 3 últimas). Antes de una restauración guarda además una copia de
seguridad junto a la base de datos (se conservan las 2 últimas). Estas copias son tan sensibles
como la base de datos.

Las copias manuales cifradas (`.cbrnbak`) son los únicos archivos pensados para salir del equipo,
por ejemplo en un medio extraíble. La contraseña tiene al menos 12 caracteres, nunca se guarda y no
se puede recuperar: una contraseña perdida significa una copia que no se puede abrir. Guarde las
copias cifradas en medios separados del ordenador.

Para crear una, elija **Archivo > Hacer copia de seguridad...** en la ventana principal, elija
dónde guardar el archivo y escriba la contraseña dos veces. Para restaurar, elija **Archivo >
Restaurar...**, elija el archivo `.cbrnbak`, confirme que se sustituirán todos los datos actuales
y escriba la contraseña. Restaurar no está disponible en el modo de solo lectura; la copia de
seguridad sí. **Archivo > Abrir carpeta de datos** muestra la carpeta de datos local. Ninguna
versión publicada contiene todavía estas entradas (sección 1).

## 12. Actualizaciones

Extraiga la nueva versión a una carpeta **nueva** e iníciela; los datos del perfil no se tocan. En
el primer inicio, si la nueva versión tiene una migración de la base de datos que aplicar, el
programa hace primero una copia de seguridad de la base de datos (la de antes de cada actualización
de la base de datos, sección 11) y después la migra. Si no hay migración pendiente, no hace esa
copia y no migra nada. Una base de datos escrita por una versión más nueva se rechaza, de modo que
volver a una versión anterior queda bloqueado.

En modo portátil los datos están en `data\` junto al programa; por eso una carpeta nueva del
programa empieza sin datos, salvo que copie en ella la carpeta `data\` antigua o inicie el programa
nuevo con `--data-dir` apuntando a la carpeta `data\` antigua.

## 13. Desinstalación

Elimine la carpeta del programa. Los datos permanecen en `%LOCALAPPDATA%\cbrn-readiness-dashboard`
hasta que usted mismo elimine esa carpeta; contiene la base de datos, las copias de seguridad y el
registro. En modo portátil los datos están dentro de la carpeta del programa y se eliminan con ella.
Las copias cifradas guardadas en otros medios no se ven afectadas en ninguno de los dos casos.

## 14. Límites conocidos

- Todavía no existe ninguna versión publicada (sección 1). El ejecutable no está firmado.
- Una base de datos de solo lectura en una ruta UNC (`\\servidor\recurso\...`) nunca se probó en un
  recurso compartido de red real. La forma en que el programa construye la dirección de solo
  lectura para esa ruta solo está cubierta por una prueba con una ruta inventada.
- Las ruedas (wheels) de PySide6 usadas para el paquete no incluyen SBOM ni archivos de atribución
  de terceros; por eso el paquete solo lleva un puntero a la lista de licencias de Qt
  (`licenses\QT-THIRD-PARTY.md`), no los textos de atribución.
- Qt escribe la fecha de creación de un informe PDF a partir del reloj del sistema; no se puede
  fijar mediante el escritor de PDF, de modo que dos generaciones del mismo informe difieren en ese
  campo.
- Las traducciones al pt-BR y al es-ES son borradores y siguen marcadas como `unfinished`; el comité
  aún no ha revisado la terminología.
- Los indicadores no tienen metas hasta que el comité las introduzca, y no están validados
  institucionalmente.
