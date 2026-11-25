# Roteiro de teste manual (smoke test) - versão 1.2.0

**Status da execução: NÃO EXECUTADO.** Este roteiro foi escrito a partir do que o código e os guias
descrevem. Nenhuma pessoa o executou ainda, nem em um computador Windows limpo, nem em outro. Nenhum
resultado abaixo foi observado: cada "resultado esperado" é o que o programa deve fazer segundo o
código e a documentação, e é isso que o teste deve confirmar ou desmentir.

A versão 1.2.0 está em preparação: ainda não tem tag nem execução do fluxo de publicação. A última
versão publicada é a 1.1.0, publicada em 21/11/2026, por decisão do responsável, antes da execução
deste roteiro. Execute-o sobre os arquivos da página pública da versão (ou, para a 1.2.0, sobre o
rascunho dela, quando existir; troque 1.2.0 por 1.1.0 nos nomes de arquivo ao testar a 1.1.0). O fluxo de publicação
(`.github/workflows/release.yml`) cria um *rascunho* de lançamento; nas próximas versões, **uma
pessoa executa este roteiro sobre o rascunho, antes de publicá-lo**. Se algum passo falhar, avise o
responsável pelo projeto.

Os nomes de menus, botões e mensagens abaixo são os do português do programa, que ainda é um
rascunho de tradução (marcado `unfinished`): a redação na tela pode diferir levemente. Em caso de
dúvida, o texto em inglês do código-fonte é a referência (por exemplo, "Back up..." aparece como
"Fazer backup...").

## 0. Antes de começar

- Para preparar o computador (conta local sem direitos de administrador, download, checksum e
  limpeza), siga o [guia prático](guia-teste-manual.pt-BR.md).
- Um computador com Windows 10 (versão 1809 ou posterior) ou Windows 11, 64 bits, **com um perfil de
  usuário limpo**, que **não** seja administrador. Nunca tenha usado o programa nesse perfil: a pasta
  `%LOCALAPPDATA%\cbrn-readiness-dashboard` não deve existir. Se existir, o teste não é de perfil
  limpo; use outro perfil.
- O zip do rascunho do lançamento, `SHA256SUMS.txt` e `SHA256-FILES.txt` baixados da **mesma** página.
- Uma pasta fora da pasta de dados para guardar o backup de teste (de preferência uma mídia removível).
- Uma frase secreta inventada para o teste, com pelo menos 12 caracteres e que não seja uma palavra
  comum. Não a escreva na folha de resultado.
- **Não insira dados reais.** Todos os dados deste roteiro são fictícios (códigos como `TESTE-001`).
  Sobre a proteção dos dados, veja [data-protection.md](data-protection.md).
- Ao terminar, registre o resultado na seção 11.

## 1. Verificar o download

1. Abra o PowerShell na pasta do zip e execute
   `Get-FileHash .\cbrn-readiness-dashboard-1.2.0-win-x64.zip -Algorithm SHA256`.
   - Resultado esperado: o valor de `Hash` é igual ao da linha do zip em `SHA256SUMS.txt`, e igual ao
     valor mostrado no corpo do rascunho do lançamento.
2. Opcional (precisa de rede e do GitHub CLI): `gh attestation verify` com o zip, como em
   [install.pt-BR.md](install.pt-BR.md).
   - Resultado esperado: a verificação é concluída sem erro. Se a atestação não estiver disponível
     (ela pode depender de o repositório ser público; isso está **a confirmar**), anote o fato.
   - Lembrete: o checksum prova a integridade da transferência, não a autenticidade; a atestação prova
     onde e como a compilação foi executada, não que o programa é seguro.

## 2. Extrair e iniciar

1. Abra as Propriedades do zip. Se houver a opção "Desbloquear", marque-a e confirme. Extraia o zip
   **inteiro** para uma pasta onde o Windows permita executar programas.
   - Resultado esperado: a pasta `cbrn-readiness-dashboard\` contém `cbrn-dashboard.exe`, `_internal\`,
     `licenses\`, as três notas `README-first-run.*.txt` e `portable.ini.example`.
2. Confira alguns arquivos com `SHA256-FILES.txt` (por exemplo `cbrn-dashboard.exe` e uma DLL).
   - Resultado esperado: os valores de `Get-FileHash` são iguais aos do manifesto.
3. Inicie `cbrn-dashboard.exe` com um duplo clique.
   - Resultado esperado: como o executável **não é assinado**, o SmartScreen pode mostrar "O Windows
     protegeu o computador"; use "Mais informações" e "Executar assim mesmo" (se a política da
     organização permitir). Anote se o SmartScreen, o Smart App Control, o AppLocker ou o WDAC
     bloqueou o programa. Um bloqueio por política é um achado, não necessariamente um defeito.
   - Não deve ser pedida elevação de administrador em nenhum momento.
4. Na primeira inicialização com um perfil limpo, aparece o aviso "Aviso de proteção de dados".
   - Resultado esperado: o aviso informa a pasta de dados (`%LOCALAPPDATA%\cbrn-readiness-dashboard`),
     a exigência de criptografia de disco completo, o funcionamento dos backups, que "sensível" é um
     rótulo de trabalho e não uma classificação formal, e como várias pessoas podem se revezar em um
     computador. Feche o aviso.
   - Fechando e abrindo o programa de novo, o aviso **não** deve voltar.
5. Observe a janela principal.
   - Resultado esperado: o idioma é português do Brasil; nenhuma faixa de versão ou de validação
     é exibida e não há faixa de DEMO; há navegação ("Navegação")
     para Painel, Pessoal, Infraestrutura, Exercícios, Orçamento, Alertas, Relatórios e Configurações.
   - Pode aparecer a faixa de lembrete de backup ("O último backup criptografado é antigo ou não
     existe"): é esperado em um perfil novo, pois nenhum backup criptografado foi feito.
6. Abra `%LOCALAPPDATA%\cbrn-readiness-dashboard` no Explorador de Arquivos.
   - Resultado esperado: a pasta existe e contém o banco de dados `cbrn-dashboard.sqlite3` e
     `prefs.json`; também `logs\` e `backups\`.

## 3. Autoteste

1. Em um PowerShell, na pasta do programa, execute (a janela do programa não tem console; aguarde o
   término antes de ler o resultado):

   ```text
   Start-Process .\cbrn-dashboard.exe -ArgumentList '--self-test','--data-dir','C:\Temp\cbrn-selftest' -Wait -PassThru
   ```

   - Resultado esperado: o processo termina sem abrir a janela principal, com código de saída 0
     (`ExitCode` do objeto retornado). Existe `C:\Temp\cbrn-selftest\selftest.json` com `passed`
     igual a `true`.
2. O autoteste não deve ter aberto nem alterado o banco de dados real do passo 2.6.

## 4. Modo de demonstração

1. Feche o programa e execute `.\cbrn-dashboard.exe --demo`.
   - Resultado esperado: abre-se um banco **separado** (`demo\demo.sqlite3` na pasta de dados). Uma
     faixa permanente "DEMO — dados fictícios" está visível. O aviso de proteção de dados não aparece
     no modo de demonstração.
2. Percorra as páginas. As situações descritas em [demo-walkthrough.md](demo-walkthrough.md) são as
   **do dia em que o banco de demonstração foi criado**; como o banco foi criado agora, são as de
   hoje. Confira:
   - Pessoal: 24 pessoas fictícias, com identificadores que começam com `DEMO`; `DEMO-P003` tem um
     habilitação de EPI de nível A vencida.
   - Infraestrutura: 20 ativos; `DEMO-A001` com manutenção em atraso.
   - Exercícios: nove edições, `DEMO-EX-01` a `DEMO-EX-09`.
   - Orçamento: entradas com identificação `DEMO`.
   - Alertas: alertas críticos, de aviso e informativos (por exemplo, habilitação de EPI vencida de
     `DEMO-P003`, habilitação de EPI a vencer de `DEMO-P002`, manutenção em atraso de `DEMO-A001`).
   - Painel: indicadores em todos os estados (OK, Aviso, Crítico) e outros como "Sem meta". As metas
     existem apenas neste banco de demonstração e são ilustrativas. Exceção conhecida: se o banco
     foi criado antes de 13 de fevereiro, `BUD_EXEC_RATE` para BRL e DIRSA aparece como OK em vez
     de Crítico.
3. Feche e abra de novo com `--demo`, **no mesmo dia**.
   - Resultado esperado: o banco é reaberto sem gerar nada de novo e **sem** a pergunta sobre recriar
     os dados.
4. Opcional, só se o banco de demonstração tiver sido criado em um dia anterior: abra com `--demo`.
   - Resultado esperado: o programa pergunta, uma vez, "Dados de demonstração de outro dia" - se deseja
     criar os dados novamente para hoje. "Sim" substitui o banco de demonstração por um novo, com a data
     de hoje (alterações feitas nele se perdem); "Não" o mantém como está. O banco real nunca é tocado.
     Se o banco foi criado hoje, este passo não se aplica; **não altere o relógio do computador** para
     forçá-lo.
5. Feche o programa.

## 5. Perfil limpo: um registro por módulo

Inicie `cbrn-dashboard.exe` (sem `--demo`). Use apenas dados fictícios. Se a tela recusar um valor,
anote a mensagem exata; ela deve explicar o problema e não alterar nada.

1. **Pessoal.** Abra a página Pessoal e use "Adicionar pessoa". Informe o código `TESTE-001` (um código
   local, sem nomes) e salve. Selecione a pessoa e use "Adicionar habilitação": nível A, uma data de
   emissão passada e uma validade futura.
   - Resultado esperado: a pessoa aparece ativa na lista e a habilitação aparece no detalhe, como
     válido.
2. **Infraestrutura.** Na página Infraestrutura, use "Adicionar ativo": um leito com código
   `TESTE-L01`, em serviço desde uma data passada.
   - Resultado esperado: o ativo aparece na lista. Se o formulário pedir outros campos, use valores
     fictícios.
3. **Exercícios.** Na página Exercícios, use "Adicionar edição": uma edição CBRAMED fictícia, com datas
   de início e fim passadas.
   - Resultado esperado: a edição aparece na lista.
4. **Orçamento.** Na página Orçamento, use "Adicionar entrada": exercício do ano corrente, uma fonte
   de recursos, moeda BRL e um valor alocado fictício. Depois "Adicionar execução" com uma data
   passada e um valor menor que o alocado.
   - Resultado esperado: a entrada e a execução aparecem, com a taxa de execução calculada.
5. **Alertas.** Abra a página Alertas.
   - Resultado esperado: a lista mostra os alertas do dia, ordenados por gravidade e depois por data
     de vencimento. Com os registros acima, um ativo sem intervalo de manutenção pode gerar um alerta
     informativo de "agenda de manutenção desconhecida". Não é necessário que haja alertas.
6. O registro de alterações (`change_log`) é gravado no banco de dados, mas **não tem página** nesta
   versão; este roteiro não o verifica.

## 6. Trocar o idioma

1. No menu "Idioma", escolha English (United States).
   - Resultado esperado: a janela inteira muda para inglês **sem reiniciar** (menus, navegação e
     textos das páginas).
2. Escolha Español (España).
   - Resultado esperado: a janela muda para espanhol, também sem reiniciar.
3. Volte para Português (Brasil).
4. Escolha English, feche o programa e abra-o de novo.
   - Resultado esperado: o programa abre em inglês (a escolha foi guardada em `prefs.json`). Volte
     para Português ao terminar.
5. Observe se alguma tela mostra texto em inglês no meio do português ou texto cortado.
   - Resultado esperado: a tradução é um rascunho; textos faltantes ou termos estranhos são
     **achados a anotar**, não falhas deste teste. A revisão da terminologia (Q14) está pendente.

## 7. Backup criptografado e restauração

1. Menu "Arquivo" > "Fazer backup...". Escolha o arquivo de destino em uma pasta **fora** da pasta de
   dados (o nome sugerido termina em `.cbrnbak`).
   - Resultado esperado: se você escolher um local dentro da pasta de dados, em uma unidade de rede ou
     em uma pasta sincronizada com a nuvem, o programa avisa e pergunta se deseja continuar; prefira
     uma mídia removível.
2. Informe a frase secreta duas vezes.
   - Resultado esperado: com frases diferentes, curtas demais (menos de 12 caracteres) ou fáceis de
     adivinhar, o programa recusa e explica o motivo. Com uma frase válida, aparece "O backup
     criptografado foi gravado em ..." e o arquivo `.cbrnbak` existe. A faixa de lembrete de backup
     desaparece.
3. Adicione uma segunda pessoa fictícia (`TESTE-002`) na página Pessoal.
4. Menu "Arquivo" > "Restaurar...". Escolha o arquivo do passo 2 e **digite uma frase secreta errada**.
   - Resultado esperado: o programa pede a confirmação de que TODOS os dados atuais serão substituídos;
     depois, com a frase errada, mostra "A frase secreta está incorreta. Nada foi alterado." e
     `TESTE-002` continua na lista.
5. Repita a restauração com a frase correta.
   - Resultado esperado: aparece "O backup foi restaurado. Os dados anteriores foram mantidos como ...".
     `TESTE-002` **não** está mais na lista; `TESTE-001`, o ativo, a edição e a entrada de orçamento
     voltam como estavam no passo 2. Uma cópia de segurança dos dados anteriores existe ao lado do
     banco de dados, na pasta de dados.
6. Troca entre demonstração e dados reais. Feche o programa e abra-o com `--demo`. Em "Arquivo" >
   "Restaurar...", escolha o mesmo arquivo `.cbrnbak` (feito a partir do banco real) e informe a
   frase correta.
   - Resultado esperado: o programa recusa: "Dados de demonstração e dados reais não podem ser
     trocados. Nada foi alterado." Feche o programa.
7. Menu "Arquivo" > "Abrir pasta de dados".
   - Resultado esperado: o Explorador de Arquivos abre a pasta de dados.

## 8. Painel e faixas

Abra o programa sem `--demo` e vá para o Painel.

1. Resultado esperado: há um bloco para cada indicador (pessoal, infraestrutura, exercícios,
   orçamento), com os valores calculados a partir dos registros do passo 5. Como este banco real
   novo **não tem metas**, os indicadores aparecem como "Sem meta" e nenhum alerta de indicador é
   gerado: o programa não inventa padrões.
2. Mude a "Data de referência" na barra de ferramentas para uma data anterior e depois use "Hoje".
   - Resultado esperado: os valores são recalculados para a data escolhida (a partir dos registros
     como são conhecidos hoje) e voltam ao normal com "Hoje".
3. Em todas as páginas e no Painel, confirme que nenhuma faixa além de DEMO (só no modo de
   demonstração) e dos lembretes de backup e de somente leitura aparece. Sem `--demo`, não deve
   haver faixa de DEMO.

## 9. Modo portátil (opcional)

1. Em uma cópia **descartável** da pasta do programa, renomeie `portable.ini.example` para
   `portable.ini` e inicie o programa.
   - Resultado esperado: os dados passam a ficar em `data\` ao lado do executável, e não em
     `%LOCALAPPDATA%`. Copiar a pasta copia os dados (aviso do próprio arquivo de exemplo).

## 10. Encerramento e limpeza

1. Feche o programa pelo menu "Arquivo" > "Sair".
   - Resultado esperado: o programa termina sem mensagem de erro e não deixa processo aberto no
     Gerenciador de Tarefas.
2. Apague a pasta do programa extraída, o arquivo `.cbrnbak` de teste, `C:\Temp\cbrn-selftest` e, se
   o perfil era só para o teste, `%LOCALAPPDATA%\cbrn-readiness-dashboard`.

## 11. Registro do resultado

Preencha após a execução e guarde a folha **fora** do repositório (ela não deve conter dados reais
nem frases secretas). O resultado resumido pode ser anotado em `CHANGELOG.md` quando o rascunho for
publicado, apenas como status.

| Campo | Valor |
|---|---|
| Status da execução | NÃO EXECUTADO |
| Versão testada (`Get-FileHash` do zip conferido) | |
| Data da execução | |
| Pessoa que executou | |
| Windows (edição e versão) e perfil sem direitos de administrador (sim/não) | |
| Passos que falharam (número e mensagem exata) | |
| Bloqueios de política (SmartScreen, Smart App Control, AppLocker, WDAC) | |
| Decisão: publicar o rascunho (sim/não) | |

## 12. O que este roteiro não cobre

- Uma pasta de dados em um caminho de rede (UNC): nunca foi testada em um compartilhamento real.
- Os relatórios em PDF, a exportação e a importação de CSV, a exportação de validação, a janela
  "Sobre", a ajuda e o modo somente leitura: este roteiro rápido não os exercita; eles estão em
  [manual-test-script.pt-BR.md](manual-test-script.pt-BR.md).
- Computadores com AppLocker, WDAC ou Smart App Control em modo restritivo: só o que for observado no
  computador de teste.
