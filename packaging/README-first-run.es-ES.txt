CBRN Readiness Dashboard - notas de primer uso (español de España)
===================================================================

Lea estas notas antes de iniciar el programa por primera vez.
Texto en borrador. El comité aún debe revisar la terminología (Q14).

1. Qué es

   CBRN Readiness Dashboard es una herramienta de escritorio para Windows.
   Funciona sin conexión. No tiene ningún código de red.

   Versión preliminar — indicadores no validados institucionalmente.

   No use los indicadores en decisiones que exijan una herramienta validada.

2. Antes de introducir datos reales

   «Sensible» es una etiqueta de trabajo de este proyecto. No es una clasificación formal.
   No introduzca datos reales todavía. Espere a que la institución responda a estas preguntas:
   - Q19: la clasificación formal de los datos.
   - Q4: datos personales.
   - Q11: seguridad de la información.
   - Q13: despliegue.
   Hasta entonces, use el modo de demostración. Sus datos son ficticios:

      cbrn-dashboard.exe --demo

3. Extraiga primero todo el zip

   Extraiga todo el zip en una carpeta. Después inicie cbrn-dashboard.exe desde esa carpeta.
   No inicie el programa desde la vista previa del zip del Explorador de archivos.
   Allí falla, porque falta la carpeta _internal\.

4. Verifique la descarga

   Abra PowerShell. Vaya a la carpeta del zip. Ejecute:

      Get-FileHash .\cbrn-readiness-dashboard-<version>-win-x64.zip -Algorithm SHA256

   Compare el resultado con la línea del zip en SHA256SUMS.txt.
   Tome SHA256SUMS.txt de la misma página de release que el zip.
   Opcional: verifique la atestación de la compilación con GitHub CLI.

      gh attestation verify cbrn-readiness-dashboard-<version>-win-x64.zip --repo marco-jardim/cbrn-readiness-dashboard

   Este paso necesita acceso a la red. Lo hace usted. No lo hace el programa.

5. Qué demuestran las comprobaciones

   SHA256SUMS.txt de la misma página de release demuestra la integridad de la transferencia, no la autenticidad.
   La atestación demuestra dónde y cómo se ejecutó la compilación, no que el programa sea seguro.

6. Desbloquee si hace falta

   Windows marca los archivos que vienen de internet (Mark-of-the-Web).
   Abra las Propiedades del zip. Marque «Desbloquear». Pulse Aceptar.
   Hágalo ANTES de extraer el zip con el extractor del propio Windows.
   Si no, los archivos extraídos heredan la marca.
   Otros extractores se comportan de otra manera.

7. SmartScreen

   El ejecutable no está firmado. SmartScreen puede mostrar «Windows protegió su PC».
   Pulse «Más información» y después «Ejecutar de todas formas».
   Su organización puede prohibirlo. En ese caso, consulte con el equipo de TI.

8. Equipos con restricciones

   AppLocker, WDAC o Smart App Control pueden bloquear el programa.
   Con AppLocker o WDAC, extraiga el zip en una carpeta que TI permita.
   TI puede crear reglas de hash con el manifiesto por archivo SHA256-FILES.txt de la página de release.
   Las reglas de hash valen por archivo y por versión. Deben cubrir los archivos .pyd y DLL.
   Smart App Control no tiene excepción para un solo archivo.

9. Dónde están los datos

   Por defecto, los datos están en:

      %LOCALAPPDATA%\cbrn-readiness-dashboard

   Allí se guardan la base de datos, las copias de seguridad, los registros y las preferencias.
   Los datos siguen allí cuando extrae una versión nueva en una carpeta nueva.
   Una actualización hace una copia de seguridad de la base de datos. La migra en el primer inicio.
   Una base de datos escrita por una versión más reciente se rechaza.

10. Modo portátil

   Cambie el nombre de portable.ini.example a portable.ini. Déjelo junto a cbrn-dashboard.exe.
   Los datos pasan entonces a .\data\, junto al programa.
   AVISO: copiar la carpeta copia los datos.

11. Proteja el equipo

   La documentación de este proyecto exige cifrado de disco completo, por ejemplo BitLocker.
   El programa no puede comprobarlo.
   No protege los archivos que exporte a medios extraíbles.
   Varias personas solo pueden turnarse en un equipo de una de estas dos maneras:
   - Una única cuenta de Windows compartida.
   - La opción --data-dir con una carpeta local que solo el comité pueda abrir.
   Con cuentas de Windows separadas, cada persona tiene una base de datos separada.
   Haga copias de seguridad cifradas. Guárdelas en medios separados.
   Una frase de contraseña (passphrase) perdida no se puede recuperar.

12. Licencia y código fuente

   Licencia: GPL-3.0-or-later. No hay garantía.
   Código fuente: https://github.com/marco-jardim/cbrn-readiness-dashboard
   Los textos de las licencias de componentes de terceros están en la carpeta licenses\.
