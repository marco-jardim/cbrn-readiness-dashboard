# Guia de instalação (português do Brasil)

Este guia é para quem instala o CBRN Readiness Dashboard e para as equipes de TI que autorizam a
sua execução. Ele existe em três idiomas com a mesma estrutura:
[pt-BR](install.pt-BR.md), [en-US](install.en-US.md) e [es-ES](install.es-ES.md). O texto das notas
de primeira execução do zip (`README-first-run.*.txt`) é mais curto e diz o mesmo.

**Versão preliminar — indicadores não validados institucionalmente.** Ainda não insira dados reais:
veja [data-protection.md](data-protection.md) (em inglês).

## 1. Situação deste guia

A versão na árvore de código é `1.0.0`. Ela está **preparada** no repositório (com registro de
alterações e roteiro de teste manual), mas nada foi marcado com tag; portanto **nenhuma versão foi
publicada e hoje não há arquivo para baixar**. O fluxo de publicação (`.github/workflows/release.yml`)
só roda quando uma tag `vX.Y.Z` é enviada, monta o pacote e cria uma versão em *rascunho* (marcada
como pré-lançamento enquanto a versão for menor que 1.0.0). O fluxo nunca foi executado. Uma pessoa
publica o rascunho depois do teste manual ([smoke-test.pt-BR.md](smoke-test.pt-BR.md)); até lá este
guia continua verdadeiro: não há versão publicada.

Tudo o que abaixo fala de download descreve o que esse fluxo e os scripts em `scripts/` foram
escritos para produzir. Nada disso foi testado em uma versão publicada.

Para experimentar o programa hoje, execute-o a partir de uma cópia do código-fonte (requer
[uv](https://docs.astral.sh/uv/)):

```text
uv sync --locked --all-groups
uv run cbrn-dashboard --demo
```

## 2. Requisitos

- Windows 10 (versão 1809 ou posterior) ou Windows 11, 64 bits (x64).
- Sem direitos de administrador e sem instalador: o programa é uma pasta que você extrai.
- Python e Qt estão dentro da pasta; não é preciso instalar mais nada.
- Uma pasta onde o Windows permita executar programas (veja a seção 7 sobre máquinas restritas).
- A estação de trabalho deve usar criptografia de disco completo (por exemplo, BitLocker). O
  programa não consegue verificar isso.

## 3. Download

A página de versões de `https://github.com/marco-jardim/cbrn-readiness-dashboard` trará três
arquivos para cada versão:

| Arquivo | Conteúdo |
|---|---|
| `cbrn-readiness-dashboard-<version>-win-x64.zip` | o programa |
| `SHA256SUMS.txt` | o checksum SHA-256 do zip |
| `SHA256-FILES.txt` | o checksum SHA-256 de cada arquivo dentro da pasta do zip |

Baixe os três da **mesma** página de versão. O zip contém uma pasta,
`cbrn-readiness-dashboard\`, com `cbrn-dashboard.exe`, a pasta `_internal\`, a pasta `licenses\`
(textos das licenças de terceiros), as três notas de primeira execução e `portable.ini.example`.

## 4. Verificar o download

### 4.1 Checksum com Get-FileHash

Abra o PowerShell na pasta dos arquivos e execute:

```powershell
Get-FileHash .\cbrn-readiness-dashboard-<version>-win-x64.zip -Algorithm SHA256
```

Compare o valor de `Hash` com a linha do zip em `SHA256SUMS.txt`. Os dois devem ser iguais.

### 4.2 Proveniência com gh attestation verify (opcional)

Se você tem o [GitHub CLI](https://cli.github.com/), pode verificar a atestação da compilação:

```powershell
gh attestation verify .\cbrn-readiness-dashboard-<version>-win-x64.zip --repo marco-jardim/cbrn-readiness-dashboard
```

Esta etapa precisa de acesso à rede **do seu lado**. O programa em si continua offline: não tem
código de rede, verificação de atualizações nem telemetria.

### 4.3 O que as verificações provam e não provam

- O `SHA256SUMS.txt` da mesma página de versão prova a integridade da transferência (o arquivo não
  foi danificado no caminho). Não prova a autenticidade: quem pudesse alterar o zip nessa página
  poderia alterar também o arquivo de checksums.
- A atestação prova onde e como a compilação foi feita. Não prova que o programa é seguro.
- O executável é **não assinado** (a assinatura de código é uma decisão adiada).

## 5. Desbloquear e extrair

1. Clique com o botão direito no zip, escolha *Propriedades*, marque *Desbloquear* se a opção
   aparecer e clique em *OK*. Faça isso **antes** de extrair: o extrator do Windows repassa a marca
   da web (Mark-of-the-Web) aos arquivos extraídos, a menos que o zip tenha sido desbloqueado
   antes. Outros extratores se comportam de forma diferente.
2. Extraia o zip **inteiro** para uma pasta onde você possa executar programas. Não execute o
   programa de dentro da visualização de zip do Explorer: lá ele falha, porque falta `_internal\`.
3. Inicie `cbrn-dashboard.exe` a partir da pasta extraída.

## 6. Primeira execução e SmartScreen

Como o executável não é assinado, o Microsoft Defender SmartScreen pode mostrar "O Windows
protegeu o computador" na primeira vez. Escolha "Mais informações" e depois "Executar assim mesmo",
a menos que a sua organização proíba; nesse caso, fale com a equipe de TI (seção 7).

## 7. Máquinas restritas (AppLocker, WDAC, Smart App Control)

Para equipes de TI:

- **Pasta de extração.** Quando o AppLocker está em vigor, as regras padrão só permitem programas na
  pasta do Windows, em Program Files e para administradores. Escolha uma pasta de extração que a
  sua política permita. A compilação em uma pasta foi feita para nunca precisar executar código a
  partir de `%TEMP%`.
- **Conferir os arquivos.** O `SHA256-FILES.txt` da mesma versão lista o SHA-256 de cada arquivo da
  pasta, inclusive os arquivos `.pyd` e DLL (os valores que o `Get-FileHash` mostra); use-o para
  conferir cada arquivo extraído. O `SHA256SUMS.txt` cobre apenas o zip. Crie as suas regras de
  liberação a partir da pasta conferida, com as ferramentas de política da própria organização.
  Essas regras valem por arquivo e por versão, e precisam cobrir também os arquivos `.pyd` e DLL.
- O **Smart App Control** não tem exceção por arquivo. Em uma máquina em que ele está ativo, o
  programa não assinado pode simplesmente não executar.
- Só a assinatura de código eliminaria a maior parte desse atrito. Ela está adiada até que as
  perguntas sobre a implantação sejam respondidas.

## 8. Opções de linha de comando

As opções são as de `cli.py`. Valem para `cbrn-dashboard.exe` e para `uv run cbrn-dashboard`.

| Opção | Significado |
|---|---|
| `--data-dir PATH` | pasta que guarda o banco de dados e os demais dados do aplicativo |
| `--lang pt-BR`, `--lang en-US` ou `--lang es-ES` | idioma da interface só nesta execução (não é salvo) |
| `--self-test` | executa as verificações internas, grava `selftest.json` na pasta de dados e termina |
| `--demo` | abre o banco de demonstração separado, com dados fictícios, nunca o banco real |
| `--version` | mostra a versão e termina (veja a nota abaixo da tabela) |

O `cbrn-dashboard.exe` é um programa em modo janela: não tem console. Por isso o `--version` não
imprime nada com que se possa contar em um prompt do programa congelado. Em uma cópia do código-fonte,
`uv run cbrn-dashboard --version` mostra a versão. A versão também está no recurso de versão do
executável.

O idioma padrão é o português do Brasil, qualquer que seja o idioma do Windows; ele é trocado no
programa e salvo em `prefs.json` na pasta de dados.

## 9. Autoteste e modo de demonstração

```text
cbrn-dashboard.exe --self-test --data-dir C:\Temp\cbrn-selftest
```

O autoteste nunca abre o banco real. Ele trabalha em uma pasta descartável `tmp\selftest-*` dentro
da pasta de dados e grava apenas `selftest.json` ao lado dela. O programa em modo janela não tem
console, e por isso o resultado é um arquivo. O código de saída é 0 quando todas as verificações
passam e 1 caso contrário.

Como o programa é em modo janela, um prompt pode voltar antes de o autoteste terminar. Leia o
`selftest.json` (o campo `passed`) só depois que o programa tiver terminado. Um script que precisa
do código de saída deve iniciar o programa de um modo que espere por ele, como fazem os testes de
empacotamento (eles o executam como processo filho, esperam e leem o código de saída e o
`selftest.json`).

```text
cbrn-dashboard.exe --demo
```

O modo de demonstração abre `demo\demo.sqlite3` na pasta de dados, um arquivo separado com
backups próprios, cheio de registros fictícios cujos identificadores começam com `DEMO`. Uma faixa
permanente avisa isso. Veja [demo-walkthrough.md](demo-walkthrough.md) (em inglês).

## 10. Local dos dados e modo portátil

### 10.1 Onde ficam os dados

Por padrão: `%LOCALAPPDATA%\cbrn-readiness-dashboard` (por exemplo,
`C:\Users\<nome>\AppData\Local\cbrn-readiness-dashboard`). A pasta contém `cbrn-dashboard.sqlite3`
(o banco de dados), `prefs.json`, `backups\`, `logs\`, `tmp\` e `demo\`. A descrição completa, as
ameaças e os deveres do operador estão em [data-protection.md](data-protection.md) (em inglês).

### 10.2 Escolher outra pasta

A pasta de dados é escolhida nesta ordem; vale a primeira regra que se aplicar:

1. a opção `--data-dir`;
2. a variável de ambiente `CBRN_DASHBOARD_DATA_DIR`;
3. o modo portátil (seção 10.3);
4. o arquivo de ponteiro `%LOCALAPPDATA%\cbrn-readiness-dashboard\location.json`, gravado pelo
   programa quando você escolhe outra pasta depois que a pasta de dados se mostrou inutilizável;
5. a pasta padrão acima.

### 10.3 Modo portátil

Renomeie `portable.ini.example` para `portable.ini` e deixe-o ao lado de `cbrn-dashboard.exe`. Os
dados passam a ir para a pasta `data\` ao lado do programa. O programa apenas verifica se
`portable.ini` existe; as chaves dentro dele não são lidas. `--data-dir` e
`CBRN_DASHBOARD_DATA_DIR` têm prioridade.

**Aviso:** copiar a pasta do programa copia também os dados.

### 10.4 Pastas somente leitura e de rede

Se a pasta de dados ou o arquivo do banco não puderem ser gravados e já existir um banco, o
programa o abre somente para leitura, mostra uma faixa e desativa toda ação que altera dados. Se a
pasta não puder ser gravada e não tiver banco, o programa explica o problema e oferece outra pasta.

O programa avisa quando a pasta de dados está em um caminho de rede (caminho UNC ou unidade
mapeada), porque o bloqueio de arquivos do SQLite não é confiável em compartilhamentos de rede, e
quando está dentro de uma pasta do OneDrive, porque os dados sairiam da máquina. Não use um
compartilhamento de rede para os dados. Várias pessoas só podem se revezar em uma máquina com uma
única conta do Windows compartilhada, ou com `--data-dir` apontando para uma pasta local restrita à
comissão; contas do Windows separadas têm bancos separados.

Um perfil do Windows obrigatório ou não persistente descarta `%LOCALAPPDATA%` quando o usuário
encerra a sessão. Em um computador assim, use `--data-dir` com uma pasta local que persista.

## 11. Backups

O programa guarda cópias simples do banco em `backups\`: uma na primeira execução de cada dia (as 7
mais recentes são mantidas, nunca menos de 2) e uma antes de cada atualização do banco (as últimas
3 são mantidas). Antes de uma restauração, ele também guarda uma cópia de segurança ao lado do
banco (as últimas 2 são mantidas). Essas cópias são tão sensíveis quanto o banco.

Os backups manuais criptografados (`.cbrnbak`) são os únicos arquivos feitos para sair da máquina,
por exemplo em mídia removível. A senha tem pelo menos 12 caracteres, nunca é guardada e não pode
ser recuperada: senha perdida significa backup que não abre. Guarde os backups criptografados em
mídia separada do computador.

Para fazer um, escolha **Arquivo > Fazer backup...** na janela principal, escolha onde salvar o
arquivo e digite a senha duas vezes. Para restaurar, escolha **Arquivo > Restaurar...**, escolha o
arquivo `.cbrnbak`, confirme que todos os dados atuais serão substituídos e digite a senha.
Restaurar não fica disponível no modo somente leitura; Fazer backup fica. **Arquivo > Abrir pasta
de dados** mostra a pasta de dados local. Nenhuma versão publicada contém esses itens ainda
(seção 1).

## 12. Atualizações

Extraia a nova versão para uma pasta **nova** e inicie-a; os dados no perfil não são alterados. Na
primeira execução, se a nova versão tiver uma migração do banco a aplicar, o programa faz primeiro
um backup do banco (o de antes de cada atualização do banco, seção 11) e depois o migra. Se não
houver migração pendente, não faz esse backup e não migra nada. Um banco gravado por uma versão mais
nova é recusado; portanto, voltar a uma versão mais antiga é bloqueado.

No modo portátil os dados ficam em `data\` ao lado do programa; assim, uma nova pasta do programa
começa sem dados, a menos que você copie para ela a pasta `data\` antiga ou inicie o novo programa
com `--data-dir` apontando para a pasta `data\` antiga.

## 13. Remoção

Apague a pasta do programa. Os dados continuam em `%LOCALAPPDATA%\cbrn-readiness-dashboard` até que
você mesmo remova essa pasta; ela contém o banco, os backups e o log. No modo portátil os dados
estão dentro da pasta do programa e são apagados junto com ela. Cópias de backups criptografados
em outras mídias não são tocadas por nenhuma das duas formas.

## 14. Limites conhecidos

- Ainda não existe nenhuma versão publicada (seção 1). O executável não é assinado.
- Um banco somente leitura em um caminho UNC (`\\servidor\compartilhamento\...`) nunca foi testado
  em um compartilhamento de rede real. A forma como o programa monta o endereço somente leitura
  para esse caminho é coberta apenas por um teste com um caminho inventado.
- O Qt grava a data de criação de um relatório PDF a partir do relógio do sistema; ela não pode ser
  definida pelo gerador de PDF, de modo que duas gerações do mesmo relatório diferem nesse campo.
- As traduções para pt-BR e es-ES são rascunhos e continuam marcadas como `unfinished`; a comissão
  ainda não revisou a terminologia.
- Os indicadores não têm metas até que a comissão as insira, e não são validados
  institucionalmente.
