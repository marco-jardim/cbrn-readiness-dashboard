CBRN Readiness Dashboard - notas de primeiro uso (português do Brasil)
======================================================================

Leia estas notas antes de iniciar o programa pela primeira vez.
Texto em rascunho. O comitê ainda precisa revisar a terminologia (Q14).

1. O que é

   O CBRN Readiness Dashboard é uma ferramenta de área de trabalho para Windows.
   Ele funciona offline. Não tem nenhum código de rede.

   Versão preliminar — indicadores não validados institucionalmente.

   Não use os indicadores em decisões que exijam uma ferramenta validada.

2. Antes de inserir dados reais

   "Sensível" é um rótulo de trabalho deste projeto. Não é uma classificação formal.
   Não insira dados reais ainda. Espere até que a instituição responda estas perguntas:
   - Q19: a classificação formal dos dados.
   - Q4: dados pessoais.
   - Q11: segurança da informação.
   - Q13: implantação.
   Até lá, use o modo de demonstração. Os dados dele são fictícios:

      cbrn-dashboard.exe --demo

3. Extraia o zip inteiro primeiro

   Extraia o zip inteiro para uma pasta. Depois inicie cbrn-dashboard.exe a partir dessa pasta.
   Não inicie o programa de dentro da visualização do zip no Explorador de Arquivos.
   Ele falha ali, porque a pasta _internal\ não existe.

4. Verifique o download

   Abra o PowerShell. Vá até a pasta do zip. Execute:

      Get-FileHash .\cbrn-readiness-dashboard-<version>-win-x64.zip -Algorithm SHA256

   Compare o resultado com a linha do zip em SHA256SUMS.txt.
   Pegue o SHA256SUMS.txt na mesma página de release do zip.
   Opcional: verifique a atestação da compilação com o GitHub CLI.

      gh attestation verify cbrn-readiness-dashboard-<version>-win-x64.zip --repo marco-jardim/cbrn-readiness-dashboard

   Este passo precisa de acesso à rede. Quem o faz é você. O programa não faz.

5. O que as verificações provam

   O SHA256SUMS.txt da mesma página de release prova a integridade da transferência, não a autenticidade.
   A atestação prova onde e como a compilação foi executada, não que o programa é seguro.

6. Desbloqueie, se necessário

   O Windows marca arquivos que vêm da internet (Mark-of-the-Web).
   Abra as Propriedades do zip. Marque "Desbloquear". Clique em OK.
   Faça isso ANTES de extrair o zip com o extrator do próprio Windows.
   Caso contrário, os arquivos extraídos herdam a marca.
   Outros extratores se comportam de outra forma.

7. SmartScreen

   O executável não é assinado. O SmartScreen pode mostrar "O Windows protegeu o computador".
   Clique em "Mais informações" e depois em "Executar assim mesmo".
   Sua organização pode proibir isso. Nesse caso, fale com a equipe de TI.

8. Computadores com restrições

   AppLocker, WDAC ou o Controle Inteligente de Aplicativos (Smart App Control) podem bloquear o programa.
   Com AppLocker ou WDAC, extraia o zip em uma pasta que a TI permita.
   O manifesto SHA256-FILES.txt da página de release lista o SHA-256 de cada arquivo da pasta,
   inclusive os arquivos .pyd e DLL. A TI pode conferir cada arquivo extraído com ele.
   Depois a TI cria suas regras de liberação a partir da pasta conferida, com as ferramentas de política da própria organização.
   As regras valem por arquivo e por versão.
   O Smart App Control não tem exceção para um único arquivo.

9. Onde ficam os dados

   Por padrão, os dados ficam em:

      %LOCALAPPDATA%\cbrn-readiness-dashboard

   Ali ficam o banco de dados, os backups, os logs e as preferências.
   Os dados continuam ali quando você extrai uma nova versão em uma nova pasta.
   Se a nova versão tiver uma alteração do banco de dados a aplicar, o programa faz primeiro um backup
   do banco e depois o migra, na primeira inicialização. Caso contrário, não migra nada.
   Um banco de dados gravado por uma versão mais nova é recusado.

10. Modo portátil

   Renomeie portable.ini.example para portable.ini. Deixe-o ao lado de cbrn-dashboard.exe.
   Os dados então passam a ficar em .\data\, ao lado do programa.
   AVISO: copiar a pasta copia os dados.

11. Proteja o computador

   A documentação deste projeto exige criptografia de disco completo, por exemplo o BitLocker.
   O programa não consegue verificar isso.
   Ele não protege arquivos que você exporta para mídia removível.
   Várias pessoas só podem se revezar em um computador de uma destas formas:
   - Uma única conta do Windows compartilhada.
   - A opção --data-dir com uma pasta local que só o comitê consiga abrir.
   Com contas do Windows separadas, cada pessoa tem um banco de dados separado.
   Faça backups criptografados. Guarde-os em mídias separadas.
   Uma senha (passphrase) perdida não pode ser recuperada.

12. Licença e código-fonte

   Licença: o código-fonte do projeto é GPL-3.0-or-later; o pacote como um todo é GPL-3.0
   (veja licenses\README.md). Não há garantia.
   Código-fonte: https://github.com/marco-jardim/cbrn-readiness-dashboard
   Os textos das licenças de componentes de terceiros estão na pasta licenses\.
