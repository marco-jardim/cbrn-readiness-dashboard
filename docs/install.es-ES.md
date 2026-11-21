# Guía de instalación (español de España)

Esta guía es para quienes instalan el CBRN Readiness Dashboard y para los equipos de TI que
autorizan su ejecución. Existe en tres idiomas con la misma estructura:
[pt-BR](install.pt-BR.md), [en-US](install.en-US.md) y [es-ES](install.es-ES.md). El texto de las
notas de primera ejecución del zip (`README-first-run.*.txt`) es más corto y dice lo mismo.

**Versión preliminar — indicadores no validados institucionalmente.** No introduzca todavía datos
reales: vea [data-protection.md](data-protection.md) (en inglés).

## 1. Estado de esta guía

La versión del árbol de código es `1.1.0`, que también es la última versión **publicada**: se
publicó en GitHub el 2026-11-21, con la etiqueta
`v1.1.0`: [página de la versión](https://github.com/marco-jardim/cbrn-readiness-dashboard/releases/tag/v1.1.0).
La versión anterior a esa, la 1.0.2, se publicó el 2026-11-14
([página de la versión](https://github.com/marco-jardim/cbrn-readiness-dashboard/releases/tag/v1.0.2)),
y la 1.0.1 el 2026-11-13
([página de la versión](https://github.com/marco-jardim/cbrn-readiness-dashboard/releases/tag/v1.0.1)).
El flujo de publicación (`.github/workflows/release.yml`) solo se ejecuta cuando se envía una
etiqueta `vX.Y.Z`, construye el paquete y crea una versión en *borrador* que una persona publica
(la 1.0.0 se construyó igual, pero su borrador nunca se publicó y fue retirado). El propietario
publicó la 1.1.0 antes de la prueba manual en un perfil limpio de Windows
([smoke-test.pt-BR.md](smoke-test.pt-BR.md) y
[manual-test-script.pt-BR.md](manual-test-script.pt-BR.md), en portugués), que **sigue
pendiente**; su resultado se registrará en el registro de cambios. En los archivos descargados,
todos los SHA-256 coincidieron con `SHA256SUMS.txt`, `gh attestation verify` fue aprobado para el
instalador y para el zip, y el instalador pasó la prueba de instalación silenciosa, autoprueba y
desinstalación silenciosa.

Todo lo que sigue sobre la descarga describe los archivos de esa página y los scripts de
`scripts/` que los producen. Ninguna persona ha probado todavía el programa en un perfil limpio de
Windows.

Como el flujo de publicación construye un **instalador** por usuario (`...-setup.exe`) en cada
versión, sin ningún paso manual, las versiones desde la 1.0.2 lo llevan junto al zip; la
1.0.1 solo tiene el zip. El flujo lo instala en modo silencioso, ejecuta la autoprueba del
programa instalado y lo vuelve a quitar antes de crear la versión; un fallo ahí hace fallar la
publicación. El instalador es la descarga recomendada y el zip es el portátil; ambos son sin
firma. Ninguna persona lo ha instalado todavía en un perfil limpio de Windows.

Para probar el programa hoy, ejecútelo desde una copia del código fuente (requiere
[uv](https://docs.astral.sh/uv/)):

```text
uv sync --locked --all-groups
uv run cbrn-dashboard --demo
```

## 2. Requisitos

- Windows 10 (versión 1809 o posterior) o Windows 11, de 64 bits (x64).
- Sin derechos de administrador. Dos formas de obtener el programa: el **instalador** (recomendado
  para el usuario final; instala solo para su usuario de Windows) o el **zip** que se extrae (modo
  portátil, equipos de TI).
- Python y Qt están dentro del instalador y del zip; no hay que instalar nada más.
- Una carpeta donde Windows permita ejecutar programas (vea la sección 7 sobre equipos restringidos).
- El puesto de trabajo debe usar cifrado de disco completo (por ejemplo, BitLocker). El programa no
  puede comprobarlo.

## 3. Descarga

La página de versiones de `https://github.com/marco-jardim/cbrn-readiness-dashboard` lleva estos
archivos por versión:

| Archivo | Contenido |
|---|---|
| `cbrn-readiness-dashboard-<version>-win-x64-setup.exe` | el instalador (recomendado para el usuario final) |
| `cbrn-readiness-dashboard-<version>-win-x64.zip` | el programa en una carpeta (modo portátil, TI) |
| `SHA256SUMS.txt` | la suma de comprobación SHA-256 del instalador y del zip |
| `SHA256-FILES.txt` | la suma SHA-256 de cada archivo dentro de la carpeta del zip |

Descargue el archivo que quiera y `SHA256SUMS.txt` de la **misma** página de versión. El zip
contiene una carpeta,
`cbrn-readiness-dashboard\`, con `cbrn-dashboard.exe`, la carpeta `_internal\`, la carpeta
`licenses\` (textos de las licencias de terceros), las tres notas de primera ejecución y
`portable.ini.example`.

## 4. Verificar la descarga

### 4.1 Suma de comprobación con Get-FileHash

Abra PowerShell en la carpeta de los archivos y ejecute:

```powershell
Get-FileHash .\cbrn-readiness-dashboard-<version>-win-x64.zip -Algorithm SHA256
```

Compare el valor de `Hash` con la línea del zip en `SHA256SUMS.txt`. Deben ser iguales. Haga lo
mismo con el instalador, antes de ejecutarlo:

```powershell
Get-FileHash .\cbrn-readiness-dashboard-<version>-win-x64-setup.exe -Algorithm SHA256
```

`SHA256SUMS.txt` tiene una línea para el instalador y otra para el zip.

### 4.2 Procedencia con gh attestation verify (opcional)

Si tiene la [CLI de GitHub](https://cli.github.com/), puede verificar la atestación de la
compilación:

```powershell
gh attestation verify .\cbrn-readiness-dashboard-<version>-win-x64.zip --repo marco-jardim/cbrn-readiness-dashboard
gh attestation verify .\cbrn-readiness-dashboard-<version>-win-x64-setup.exe --repo marco-jardim/cbrn-readiness-dashboard
```

Este paso necesita acceso a la red **de su lado**. El programa en sí sigue sin conexión: no tiene
código de red, ni comprobación de actualizaciones, ni telemetría.

### 4.3 Qué prueban y qué no prueban las comprobaciones

- El `SHA256SUMS.txt` de la misma página de versión prueba la integridad de la transferencia (el
  archivo no se dañó por el camino). No prueba la autenticidad: quien pudiera cambiar el zip en esa
  página podría cambiar también el archivo de sumas.
- La atestación prueba dónde y cómo se ejecutó la compilación. No prueba que el programa sea seguro.
- El ejecutable es **no firmado** hoy. Las versiones podrán firmarse en el futuro mediante el
  programa de código abierto de la SignPath Foundation (vea la [política de firma de
  código](../CODE-SIGNING-POLICY.md), en inglés). Una versión así lo indica en sus notas. Para
  comprobarlo, extraiga el zip y abra las Propiedades de `cbrn-dashboard.exe`, pestaña *Firmas
  digitales*, o ejecute en PowerShell
  `Get-AuthenticodeSignature .\cbrn-readiness-dashboard\cbrn-dashboard.exe`: el estado debe ser
  `Valid` y el firmante "SignPath Foundation". Solo ese ejecutable se firmaría, no los archivos de
  Qt, de Python y de Microsoft que lo acompañan.
- El instalador (el `.exe` de instalación) **tampoco está firmado**, y no se prevé firmarlo: el
  paso de firma se ejecuta antes de que el instalador exista. SmartScreen también avisa sobre él
  (sección 6).

## 5. Instalar: instalador o zip

### 5.1 El instalador (recomendado)

1. Descargue `cbrn-readiness-dashboard-<version>-win-x64-setup.exe` y `SHA256SUMS.txt` de la misma
   página de versión y compruebe el hash (sección 4.1).
2. Ejecute el instalador. SmartScreen puede avisar (sección 6). No se necesitan derechos de
   administrador: instala solo para su usuario de Windows, en
   `%LOCALAPPDATA%\Programs\CBRN Readiness Dashboard`, y crea un acceso directo en el menú Inicio
   (un icono en el escritorio es opcional y viene desactivado). El instalador está en portugués de
   Brasil, inglés o español, según el idioma de su Windows. Muestra la licencia y un aviso breve
   antes de instalar.
3. Inicie el programa desde el menú Inicio, o marque la opción al final de la instalación.
4. Para los equipos de TI, el cuadro de diálogo del inicio del instalador ofrece instalar para todos
   los usuarios (exige administrador y usa `Program Files`; vea la sección 7). Instalación
   silenciosa para scripts: `...-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /DIR="C:\carpeta"`.

El programa instalado no usa el modo portátil: sus datos permanecen en
`%LOCALAPPDATA%\cbrn-readiness-dashboard` (sección 10.1). El instalador no escribe ninguna clave del
registro salvo la entrada que Windows muestra en Configuración > Aplicaciones, y no usa la red.

### 5.2 El zip (modo portátil, equipos de TI)

1. Pulse con el botón derecho en el zip, elija *Propiedades*, marque *Desbloquear* si aparece y
   pulse *Aceptar*. Hágalo **antes** de extraer: el extractor de Windows transmite la marca de la
   web (Mark-of-the-Web) a los archivos extraídos, salvo que el zip se haya desbloqueado antes.
   Otros extractores se comportan de otra manera.
2. Extraiga el zip **completo** a una carpeta donde pueda ejecutar programas. No ejecute el
   programa desde la vista previa del zip del Explorador: allí falla, porque falta `_internal\`.
3. Inicie `cbrn-dashboard.exe` desde la carpeta extraída.

## 6. Primer inicio y SmartScreen

Como el instalador y el ejecutable no están firmados, Microsoft Defender SmartScreen puede mostrar
"Windows protegió su PC" al ejecutar el instalador y de nuevo la primera vez que inicia el
programa. Elija "Más información" y después "Ejecutar de todas formas", salvo que su organización
lo prohíba; en ese caso consulte a su equipo de TI (sección 7).

## 7. Equipos restringidos (AppLocker, WDAC, Smart App Control)

Para los equipos de TI:

- **Carpeta de extracción.** Cuando AppLocker está activo, sus reglas predeterminadas solo permiten
  programas en la carpeta de Windows, en Program Files y para administradores. Elija una carpeta de
  extracción que su política permita. La compilación en una carpeta está pensada para no necesitar
  nunca ejecutar código desde `%TEMP%`.
- **Instalador.** La instalación por usuario va a `%LOCALAPPDATA%\Programs`, una carpeta en la que
  el usuario puede escribir; por eso las reglas predeterminadas de AppLocker la bloquean. TI puede
  elegir la instalación para todos los usuarios (el cuadro de diálogo del instalador la ofrece;
  exige administrador e instala en `Program Files`, que las reglas predeterminadas permiten), o
  instalar con `/DIR=` en una carpeta que la política permita, o comprobar los archivos instalados
  con `SHA256-FILES.txt` y crear las reglas con las herramientas de política de su propia
  organización. El propio instalador también debe tener permiso para ejecutarse, y no está
  firmado.
- **Comprobar los archivos.** `SHA256-FILES.txt` de la misma versión lista el SHA-256 de cada
  archivo de la carpeta, incluidos los archivos `.pyd` y DLL (los valores que muestra
  `Get-FileHash`); úselo para comprobar cada archivo extraído. `SHA256SUMS.txt` cubre solo el zip.
  Cree sus reglas de autorización a partir de la carpeta comprobada, con las herramientas de
  política de su propia organización. Esas reglas son por archivo y por versión, y deben cubrir
  también los archivos `.pyd` y DLL.
- **Smart App Control** no admite excepciones por archivo. En un equipo donde está activo, el
  programa no firmado puede sencillamente no ejecutarse.
- Solo la firma de código eliminaría la mayor parte de esta fricción, y solo para el ejecutable (las
  DLL y los archivos `.pyd` siguen sin firma). Está preparada pero inactiva (sección 4.3) y sigue
  aplazada hasta que se respondan las preguntas sobre el despliegue.

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

**Aviso:** copiar la carpeta del programa copia también los datos. El modo portátil es para el zip:
el instalador nunca crea `portable.ini`; así, el programa instalado guarda los datos en el perfil,
no junto al programa.

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
seguridad sí. **Archivo > Abrir carpeta de datos** muestra la carpeta de datos local. La
versión 1.1.0 contiene estas entradas (sección 1); una persona todavía no las ha probado en un
perfil limpio.

## 12. Actualizaciones

Con el instalador, ejecute el instalador de la versión más nueva: reconoce el programa instalado,
sustituye sus archivos en la misma carpeta y conserva los datos. Con el zip, extraiga la nueva
versión a una carpeta **nueva** e iníciela; los datos del perfil no se tocan. En
el primer inicio, si la nueva versión tiene una migración de la base de datos que aplicar, el
programa hace primero una copia de seguridad de la base de datos (la de antes de cada actualización
de la base de datos, sección 11) y después la migra. Si no hay migración pendiente, no hace esa
copia y no migra nada. Una base de datos escrita por una versión más nueva se rechaza, de modo que
volver a una versión anterior queda bloqueado.

En modo portátil los datos están en `data\` junto al programa; por eso una carpeta nueva del
programa empieza sin datos, salvo que copie en ella la carpeta `data\` antigua o inicie el programa
nuevo con `--data-dir` apuntando a la carpeta `data\` antigua.

## 13. Desinstalación

Instalado con el instalador: abra Configuración > Aplicaciones > Aplicaciones instaladas, elija
"CBRN Readiness Dashboard" y desinstálelo. El desinstalador elimina solo el programa. Con el zip:
elimine la carpeta del programa. En ambos casos los datos permanecen en
`%LOCALAPPDATA%\cbrn-readiness-dashboard` hasta que usted mismo elimine esa carpeta; contiene la base de datos, las copias de seguridad y el
registro. En modo portátil los datos están dentro de la carpeta del programa y se eliminan con ella.
Las copias cifradas guardadas en otros medios no se ven afectadas en ninguno de los dos casos.

## 14. Límites conocidos

- La versión 1.1.0 está publicada, pero su prueba manual en un perfil limpio sigue pendiente
  (sección 1). El ejecutable no está firmado.
- El instalador lo construye y lo prueba en modo silencioso solo el flujo de publicación; no está
  firmado (sección 4.3), y una persona todavía no lo ha ejecutado en un perfil limpio.
- Una base de datos de solo lectura en una ruta UNC (`\\servidor\recurso\...`) nunca se probó en un
  recurso compartido de red real. La forma en que el programa construye la dirección de solo
  lectura para esa ruta solo está cubierta por una prueba con una ruta inventada.
- Qt escribe la fecha de creación de un informe PDF a partir del reloj del sistema; no se puede
  fijar mediante el escritor de PDF, de modo que dos generaciones del mismo informe difieren en ese
  campo.
- Las traducciones al pt-BR y al es-ES son borradores y siguen marcadas como `unfinished`; el comité
  aún no ha revisado la terminología.
- Los indicadores no tienen metas hasta que el comité las introduzca, y no están validados
  institucionalmente.
