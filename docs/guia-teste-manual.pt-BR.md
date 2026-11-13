# Guia prático para executar o teste manual - versão 1.0.1

**Versão preliminar - indicadores não validados institucionalmente.**

Este guia é para a pessoa que vai executar os roteiros de teste da versão 1.0.1 em um **perfil limpo
do Windows, sem direitos de administrador**. Ele diz como preparar o computador, como obter e conferir
o pacote, o que executar e como registrar o resultado. Os testes em si estão nestes dois roteiros:

1. [smoke-test.pt-BR.md](smoke-test.pt-BR.md): o roteiro rápido de instalação e de perfil limpo
   (execute este primeiro);
2. [manual-test-script.pt-BR.md](manual-test-script.pt-BR.md): o roteiro completo, página por página.

Os dois partem de um perfil em que o programa nunca foi usado. O guia de instalação,
[install.pt-BR.md](install.pt-BR.md), explica o mesmo caminho para quem instala de verdade.

**Não insira dados reais.** Todo o teste usa dados fictícios (códigos como `TESTE-001`) e o modo de
demonstração (`--demo`). Dados reais só podem ser inseridos depois que a instituição responder às
perguntas Q19, Q4, Q11 e Q13 (veja [questionario-comite.pt-BR.md](questionario-comite.pt-BR.md) e
[data-protection.md](data-protection.md), em inglês).

## 0. O que você precisa

- Um computador com Windows 10 (versão 1809 ou posterior) ou Windows 11, 64 bits (x64).
- Uma pessoa com conta de administrador **uma única vez**, só para o passo 1 (criar a conta de
  teste). O teste em si roda na conta nova, sem administrador.
- O zip e os arquivos de checksum do rascunho da versão (passo 3), ou alguém que os baixe para você.
- Um pen drive (ou outra mídia removível) para o teste de backup, e uma frase secreta inventada para
  o teste, com pelo menos 12 caracteres. Não a escreva em nenhuma folha de resultado.
- Um dia livre para executar os dois roteiros. Os dados de demonstração envelhecem: execute no mesmo
  dia e **não altere o relógio do computador**.

## 1. Criar uma conta local de usuário padrão

Este passo precisa de um administrador, **uma vez**. Depois dele, tudo é feito na conta nova.

### 1.1 Pelo Windows (Configurações)

1. Abra **Configurações > Contas > Outros usuários** e escolha **Adicionar conta**. (No Windows 11 o
   caminho é o mesmo, mas a lista pode aparecer em **Contas > Família e outros usuários**.)
2. Na janela da Microsoft, escolha **Não tenho as informações de entrada desta pessoa**.
3. Escolha **Adicionar um usuário sem conta Microsoft**.
4. Digite um nome de usuário (por exemplo, `teste-cbrn`), uma senha e as respostas às perguntas de
   segurança, e conclua.
5. **Mantenha o tipo de conta "Usuário padrão".** Não escolha "Alterar tipo de conta" para
   administrador.

### 1.2 Alternativa: PowerShell com privilégios elevados

Abra o PowerShell como administrador e execute:

```powershell
New-LocalUser -Name "teste-cbrn" -Password (Read-Host -AsSecureString)
Add-LocalGroupMember -Group "Users" -Member "teste-cbrn"
```

O `Read-Host -AsSecureString` pede a senha no terminal, sem mostrá-la. Em um Windows em português o
grupo se chama **"Usuários"**, e não "Users": use `-Group "Usuários"`. Se preferir não depender do
idioma, use o identificador do grupo:

```powershell
Add-LocalGroupMember -Group (Get-LocalGroup -SID S-1-5-32-545) -Member "teste-cbrn"
```

Não adicione a conta ao grupo "Administradores".

## 2. Entrar na conta nova e conferir que ela não é administradora

1. Saia da sua sessão (ou use **Trocar usuário**) e entre na conta `teste-cbrn`. A primeira entrada
   cria o perfil, o que leva alguns minutos.
2. Abra um PowerShell **comum** (não "como administrador") e execute:

   ```powershell
   whoami
   whoami /groups
   ```

3. Confira: `whoami` mostra `<computador>\teste-cbrn`, e a lista de `whoami /groups` **não** traz
   `BUILTIN\Administrators` (no Windows em português, `BUILTIN\Administradores`) com o estado
   habilitado. Se o grupo aparecer, mesmo como "somente negação", a conta é de administrador: volte ao
   passo 1 e corrija o tipo da conta.
4. Confira também que a pasta `%LOCALAPPDATA%\cbrn-readiness-dashboard` **não existe**. Se existir, o
   perfil não é limpo.

## 3. Obter o zip do rascunho da versão

A versão 1.0.1 é um **rascunho** (*draft*) no GitHub: ele aparece só para quem colabora no
repositório `marco-jardim/cbrn-readiness-dashboard`, na página
[releases](https://github.com/marco-jardim/cbrn-readiness-dashboard/releases). Quem não colabora não
o vê. Há duas formas de obtê-lo; escolha uma:

- **A. Baixar com a conta do responsável pelo projeto**, em um navegador, em outro perfil ou outro
  computador. Baixe os três arquivos da **mesma** página de versão:
  - `cbrn-readiness-dashboard-1.0.1-win-x64.zip`
  - `SHA256SUMS.txt`
  - `SHA256-FILES.txt`
- **B. Pedir ao responsável pelo projeto** que copie esses três arquivos para um pen drive ou uma
  pasta compartilhada, e copie-os de lá para uma pasta da conta de teste (por exemplo,
  `%USERPROFILE%\Downloads`).

Não entre na conta do GitHub do responsável dentro do perfil de teste: as credenciais ficariam
guardadas nele. Se um pen drive em exFAT ou FAT32 for usado, o Windows pode não manter a marca de
"arquivo baixado da internet" (Mark-of-the-Web) no zip; isso não atrapalha o teste, mas anote como o
arquivo chegou (navegador, pen drive ou pasta compartilhada) na folha de resultado.

## 4. Verificar o checksum

1. Abra o PowerShell na pasta dos arquivos e execute:

   ```powershell
   Get-FileHash .\cbrn-readiness-dashboard-1.0.1-win-x64.zip -Algorithm SHA256
   ```

2. Compare o valor da coluna `Hash` com a linha do zip em `SHA256SUMS.txt`. Os dois devem ser
   iguais. Para esta compilação, o valor esperado é:

   ```text
   consulte o arquivo SHA256SUMS.txt do release
   ```

   O `Get-FileHash` mostra o valor em maiúsculas; a comparação não diferencia maiúsculas de
   minúsculas. **Se o valor diferir, pare:** não extraia nem execute nada e avise o responsável pelo
   projeto. Se o rascunho tiver sido gerado de novo, o valor muda; nesse caso vale o do
   `SHA256SUMS.txt` da mesma página, e o responsável deve confirmá-lo.
3. Opcional (precisa do [GitHub CLI](https://cli.github.com/) e de rede): verifique a proveniência da
   compilação.

   ```powershell
   gh attestation verify .\cbrn-readiness-dashboard-1.0.1-win-x64.zip --repo marco-jardim/cbrn-readiness-dashboard
   ```

   Se a atestação não estiver disponível, anote o fato; ele não impede o teste. O checksum prova a
   integridade da transferência, não a autenticidade; a atestação prova onde e como a compilação foi
   feita, não que o programa é seguro (veja a seção 4.3 de [install.pt-BR.md](install.pt-BR.md)).

## 5. Desbloquear e extrair

1. Clique com o botão direito no zip, escolha **Propriedades**, marque **Desbloquear** (se a opção
   aparecer) e clique em **OK**. Alternativa no PowerShell:

   ```powershell
   Unblock-File .\cbrn-readiness-dashboard-1.0.1-win-x64.zip
   ```

   Faça isso **antes** de extrair.
2. Extraia o zip **inteiro** (botão direito > **Extrair tudo**) para uma pasta em que a conta de
   teste possa gravar e executar programas, por exemplo `%USERPROFILE%\Apps\cbrn`. O programa fica em
   `%USERPROFILE%\Apps\cbrn\cbrn-readiness-dashboard\cbrn-dashboard.exe`. Não o execute de dentro da
   visualização de zip do Explorador: lá ele falha.
3. Na primeira vez que iniciar `cbrn-dashboard.exe`, o Windows pode mostrar **"O Windows protegeu o
   computador"**, porque o executável **não é assinado**. Escolha **Mais informações** e depois
   **Executar assim mesmo**. Se uma política da organização (SmartScreen, Smart App Control,
   AppLocker ou WDAC) impedir a execução, não a contorne: anote qual foi o bloqueio e a mensagem
   exata. Um bloqueio por política é um achado do teste, não necessariamente um defeito.
4. O Windows **não** deve pedir elevação de administrador em nenhum momento. Se pedir, anote.

## 6. Executar os roteiros

1. Execute primeiro [smoke-test.pt-BR.md](smoke-test.pt-BR.md) e depois
   [manual-test-script.pt-BR.md](manual-test-script.pt-BR.md). Siga os passos na ordem; cada um traz o
   "resultado esperado".
2. A pasta dos dados do programa neste perfil é `%LOCALAPPDATA%\cbrn-readiness-dashboard` (por
   exemplo, `C:\Users\teste-cbrn\AppData\Local\cbrn-readiness-dashboard`). Ela só passa a existir
   depois da primeira execução do programa.
3. Preencha as tabelas de resultado enquanto testa: a seção 11 do roteiro rápido e a seção 16 do
   roteiro completo. Preencha uma **cópia** das tabelas, guardada **fora do repositório**. Nunca
   escreva dados reais nem frases secretas nelas.
4. Para cada passo que falhar, anote o número do passo e a **mensagem exata** da tela, e tire uma
   captura de tela (tecla Windows + Shift + S, ou a tecla Print Screen). Guarde as capturas na mesma
   pasta de resultados, fora do repositório.
5. Diferenças de redação ou de tradução nas telas (o texto em português é um rascunho) são
   **achados a anotar**, não falhas do teste; anote-as no campo de terminologia (Q14).
6. Se algum passo falhar, continue com os demais passos e anote tudo, mas o rascunho **não deve ser
   publicado** até que a causa seja entendida.

## 7. Registrar o resultado

1. **Quem testou** preenche as tabelas de resultado (seção 11 do roteiro rápido e seção 16 do roteiro
   completo) e envia ao responsável pelo projeto: as tabelas, as capturas de tela e a decisão
   sugerida sobre publicar o rascunho (sim ou não). Informe a data da execução, a edição e a versão do
   Windows e o valor do `Get-FileHash` do zip que foi testado.
2. **O responsável pelo projeto** registra o status em [CHANGELOG.md](../CHANGELOG.md), na entrada da
   versão 1.0.1: data, versão testada, resultado e decisão sobre publicar, **sem** o conteúdo das
   respostas ao questionário. Depois troca a linha de status no início dos dois roteiros de "NÃO
   EXECUTADO" para o formato que os testes do repositório aceitam:

   ```text
   Status da execução: EXECUTADO em AAAA-MM-DD, resultado: <resumo curto>
   ```

   (por exemplo, `EXECUTADO em 2026-12-01, resultado: aprovado`; a data pode ser escrita também como
   `DD/MM/AAAA`).
3. Só então o responsável pelo projeto **publica o rascunho** da versão. O registro não substitui a
   decisão do comitê sobre dados reais.

## 8. Limpeza

Quando o teste terminar, na conta de teste:

1. Feche o programa pelo menu **Arquivo > Sair**.
2. Apague a pasta do programa extraída (`%USERPROFILE%\Apps\cbrn`), os arquivos baixados, o arquivo
   `.cbrnbak` do teste (e o do pen drive), `C:\Temp\cbrn-selftest` e `C:\Temp\cbrn-teste`.
3. Apague a pasta de dados `%LOCALAPPDATA%\cbrn-readiness-dashboard` **deste perfil**: ela contém o
   banco de teste, os backups e o registro (log) do programa.

Depois, em uma sessão de administrador (de outra conta), remova a conta de teste:

- Pelo Windows: **Configurações > Contas > Outros usuários**, escolha a conta `teste-cbrn` e
  **Remover**, depois **Excluir conta e dados**. Isso apaga também a pasta do perfil
  (`C:\Users\teste-cbrn`).
- Ou pelo PowerShell com privilégios elevados:

  ```powershell
  Get-CimInstance Win32_UserProfile | Where-Object { $_.LocalPath -like '*\teste-cbrn' } | Remove-CimInstance
  Remove-LocalUser -Name "teste-cbrn"
  ```

  A primeira linha remove o perfil (a pasta `C:\Users\teste-cbrn`) e a segunda remove a conta. Faça
  nessa ordem, enquanto a conta ainda existe.

Os arquivos de resultado (tabelas e capturas de tela) ficam com o responsável pelo projeto, fora do
repositório.
