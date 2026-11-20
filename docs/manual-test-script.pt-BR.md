# Roteiro de teste manual para o comitê - versão 1.1.0

**Status da execução: NÃO EXECUTADO.** Este roteiro foi escrito a partir do que o código e a
documentação descrevem. Nenhuma pessoa o executou ainda. Nenhum resultado abaixo foi observado: cada
"resultado esperado" é o que o programa deve fazer segundo o código e os documentos, e é isso que o
teste deve confirmar ou desmentir.

**Versão preliminar - indicadores não validados institucionalmente.**

A versão 1.1.0 está em preparação no repositório (sem tag, não publicada); a última versão publicada
é a 1.0.2. Se você testar a 1.0.2, a janela "Sobre" e o relatório mostram 1.0.2 no lugar de 1.1.0.

Este roteiro é para o comitê de defesa QBRN do hospital. Ele percorre, com os **dados de
demonstração**, cada página do programa, os alertas, a troca de idioma, o backup em mídia removível e
a restauração, a geração de relatórios, a exportação e a importação de CSV (com os modelos) e o modo
somente leitura. O roteiro rápido de instalação, com perfil limpo do Windows, é outro documento:
[smoke-test.pt-BR.md](smoke-test.pt-BR.md). A ordem recomendada é executar primeiro aquele e depois
este.

Os nomes de menus, botões e mensagens abaixo são os do português do programa, que ainda é um
rascunho de tradução (a terminologia aguarda a revisão da pergunta Q14): a redação na tela pode
diferir levemente. Diferenças de redação são **achados a anotar**, não falhas do teste. O programa
nunca envia nada para fora do computador; os relatórios, as exportações e os backups só são gravados
nos arquivos e pastas que você escolhe.

## 0. Antes de começar

- Para preparar o computador (conta local sem direitos de administrador, download, checksum,
  extração e limpeza), siga o [guia prático](guia-teste-manual.pt-BR.md).
- O programa já extraído e iniciável (veja [install.pt-BR.md](install.pt-BR.md)), ou um clone do
  repositório com `uv run cbrn-dashboard` no lugar de `.\cbrn-dashboard.exe`.
- Uma pasta de trabalho descartável, por exemplo `C:\Temp\cbrn-teste`, e **uma mídia removível** (por
  exemplo, um pen drive) para o teste de backup.
- Uma frase secreta inventada para o teste, com pelo menos 12 caracteres e que não seja uma palavra
  comum. Não a escreva na folha de resultado.
- **Não insira dados reais.** Este roteiro usa apenas os dados fictícios do modo de demonstração
  (identificadores que começam com `DEMO`). Os dados reais só devem ser inseridos depois que a
  instituição responder às perguntas Q19, Q4, Q11 e Q13 (veja [data-protection.md](data-protection.md)).
- As situações dos dados de demonstração são as **do dia em que o banco de demonstração foi criado**
  (veja [demo-walkthrough.md](demo-walkthrough.md)). Execute o roteiro no mesmo dia da criação e
  **não altere o relógio do computador**. Em um banco criado em outro dia, as situações envelhecem e
  podem diferir do que está escrito aqui.
- Ao terminar, preencha a seção 16 e registre o resultado em CHANGELOG.md.

## 1. Iniciar o modo de demonstração

1. Abra o PowerShell na pasta do programa e execute:

   ```text
   .\cbrn-dashboard.exe --demo --data-dir C:\Temp\cbrn-teste
   ```

   - Resultado esperado: abre-se a janela principal em português do Brasil. Uma faixa permanente
     "DEMO — dados fictícios" está visível, junto com a faixa "Versão preliminar — indicadores não
     validados institucionalmente.". O aviso de proteção de dados não aparece no modo de demonstração.
     O banco de demonstração é um arquivo separado, `demo\demo.sqlite3`, dentro de `C:\Temp\cbrn-teste`.
2. Observe a navegação ("Navegação").
   - Resultado esperado: as oito páginas existem, nesta ordem: **Painel**, **Pessoal**,
     **Infraestrutura**, **Exercícios**, **Orçamento**, **Alertas**, **Relatórios** e
     **Configurações**.
3. Feche o programa e abra-o de novo com o mesmo comando, no mesmo dia.
   - Resultado esperado: o banco é reaberto sem gerar nada de novo e sem a pergunta sobre recriar os
     dados.

## 2. Página Painel

1. Abra **Painel**.
   - Resultado esperado: há um bloco para cada leitura de indicador, a contagem de alertas por
     gravidade e os gráficos. O banco de demonstração tem metas ilustrativas apenas para algumas
     leituras; as demais aparecem como "Sem meta". As metas de demonstração não são padrões de nenhum
     tipo.
2. Confira os estados descritos em [demo-walkthrough.md](demo-walkthrough.md) (Adequado = OK,
   Atenção = Warning, Crítico = Critical):
   - `PERS_CERT_VALID`: nível A Adequado, nível B Atenção, nível C Crítico.
   - `PERS_CERT_EXPIRING`, nível A: Atenção.
   - `INFRA_MAINT_OVERDUE` para leito (bed): Crítico.
   - `EX_DAYS_SINCE_LAST` para OTHER: Crítico.
   - `BUD_EXEC_RATE` para USD e COMAER: Adequado. Para BRL e DIRSA: Crítico, **exceto** em um banco de
     demonstração criado antes de 13 de fevereiro, em que aparece Adequado (exceção descrita no
     walkthrough).
   - `EX_LAST_PARTICIPANTS` para EXBRAMED e `BUD_EXEC_RATE` para USD e `DEMO-SRC-A`: "Sem dados".
   - Leituras como `PERS_DEGREE`: "Sem meta".
3. Mude a "Data de referência" na barra de ferramentas para uma data anterior e depois use "Hoje"
   (ou Ctrl+T).
   - Resultado esperado: os valores são recalculados para a data escolhida (com os registros como são
     conhecidos hoje) e voltam ao normal com "Hoje".
4. Use "Mostrar como tabela" em um gráfico.
   - Resultado esperado: os mesmos valores aparecem em forma de tabela.

## 3. Página Pessoal

1. Abra **Pessoal**.
   - Resultado esperado: 24 pessoas fictícias, com identificadores que começam com `DEMO`.
2. Confira os casos fixos descritos no walkthrough:
   - `DEMO-P001`: habilitações de EPI de nível A e B longas, uma especialização e um mestrado
     concluídos.
   - `DEMO-P002`: habilitação de EPI de nível A que vence em 30 dias (dentro da janela de aviso).
   - `DEMO-P003`: habilitação de EPI de nível A vencida há 45 dias.
   - `DEMO-P004`: habilitação de nível A válida, marcada como "Sem renovação" desde 10 dias atrás; não
     gera alerta de vencimento.
   - `DEMO-P005`: desativada há 60 dias; não conta nos indicadores.
   - `DEMO-P006`: cadeia de renovação no nível B (uma habilitação antiga vencida e uma nova válida,
     que conta uma vez).
3. Selecione uma pessoa e observe o detalhe ("Detalhes da pessoa selecionada"), com as habilitações
   de EPI, o treinamento e as titulações. Use os filtros "Somente ativos", "Precisa de reciclagem" e
   "Todos os níveis".
   - Resultado esperado: as listas mudam conforme o filtro; `DEMO-P003` aparece entre as pessoas que
     precisam de reciclagem.
4. Use "Adicionar pessoa" com o código fictício `TESTE-001` e salve; depois "Desativar pessoa".
   - Resultado esperado: o registro é criado e depois desativado, e a pessoa deixa de contar. A
     página usa a expressão "habilitação de EPI".
5. Os cursos são `DEMO-C1`, `DEMO-C2` e `DEMO-C3` (Configurações > Pessoal, seção 10).

## 4. Página Infraestrutura

1. Abra **Infraestrutura**.
   - Resultado esperado: 20 ativos fictícios, dos quatro tipos predefinidos e do tipo definido pelo
     usuário `DEMO-TYPE`.
2. Confira os casos fixos descritos no walkthrough:
   - `DEMO-A001` (leito): manutenção vencida há 20 dias (em atraso).
   - `DEMO-A002` (baia): degradado desde 15 dias atrás, com manutenção prevista em 10 dias.
   - `DEMO-A003` (equipamento de pressão negativa e filtragem): fora de serviço desde 10 dias atrás,
     sem intervalo e sem próximo vencimento registrado: agenda de manutenção desconhecida.
   - `DEMO-A004` (tenda de descontaminação): intervalo 0 significa sem manutenção programada; sem
     alerta.
   - `DEMO-A008`: aposentado há 30 dias; o histórico permanece, mas ele sai dos indicadores.
   - `DEMO-A009`: entra em serviço em 20 dias.
3. Selecione um ativo e observe o "Histórico do ativo selecionado" (mudanças de situação e
   manutenção).
   - Resultado esperado: o histórico lista os registros do ativo. Na página, "Disponível" significa
     operacional; a ocupação não é acompanhada.
4. Entrada de dados. Use "Adicionar ativo": um leito com código `TESTE-L01`, em serviço desde uma
   data passada. Se o formulário pedir outros campos, use valores fictícios.
   - Resultado esperado: o ativo aparece na lista. Se a tela recusar um valor, anote a mensagem
     exata; ela deve explicar o problema e não alterar nada.

## 5. Página Exercícios

1. Abra **Exercícios**.
   - Resultado esperado: nove edições fictícias, `DEMO-EX-01` a `DEMO-EX-09`, dos três tipos
     (CBRAMED, EXBRAMED e outro), com participantes, países e resultados para as duas métricas
     `DEMO-M1` (quanto maior, melhor) e `DEMO-M2` (quanto menor, melhor).
2. Selecione `DEMO-EX-06` e `DEMO-EX-09`.
   - Resultado esperado: `DEMO-EX-06` é a última edição EXBRAMED encerrada e não tem total de
     participantes. `DEMO-EX-09` começa no futuro e não tem resultados.
3. Entrada de dados. Use "Adicionar edição": uma edição CBRAMED fictícia, com datas de início e fim
   passadas.
   - Resultado esperado: a edição aparece na lista.

## 6. Página Orçamento

1. Abra **Orçamento**.
   - Resultado esperado: entradas do exercício fiscal corrente e dos três anteriores, para as duas
     fontes predefinidas e a fonte definida pelo usuário `DEMO-SRC-A`. As fontes predefinidas são
     **DIRSA** e **Comando da Aeronáutica** (COMAER). A fonte COMAER tem entradas em BRL e em USD, que
     nunca são somadas.
2. Confira as entradas: `DEMO - DIRSA annual allocation`, `DEMO - COMAER allocation`,
   `DEMO - COMAER foreign purchases`, `DEMO - equipment` e `DEMO - training`.
   - Resultado esperado: cada entrada tem linhas de execução com data; no ano corrente, uma linha tem
     data posterior a hoje e ainda não conta. `DEMO - pending allocation` (USD, `DEMO-SRC-A`) tem
     execuções, mas nenhum valor alocado, e sua taxa de execução aparece como "Sem dados".
3. Veja o "Resumo por fonte e moeda".
   - Resultado esperado: os valores estão separados por fonte e por moeda, sem conversão.
4. Entrada de dados. Use "Adicionar entrada": exercício do ano corrente, uma fonte de recursos, moeda
   BRL e um valor alocado fictício. Depois use "Adicionar execução" com uma data passada e um valor
   menor que o alocado.
   - Resultado esperado: a entrada e a execução aparecem, com a taxa de execução calculada.

## 7. Página Alertas

1. Abra **Alertas**.
   - Resultado esperado: a lista traz as colunas Gravidade, Módulo, Assunto, Vencimento e Mensagem,
     ordenada por gravidade e depois por data de vencimento.
2. Confira que, no dia da criação, os dados de demonstração produzem estes alertas (podem existir
   outros, de pessoas e ativos de preenchimento):
   - crítico: habilitação de EPI vencida de `DEMO-P003`, nível A;
   - aviso: habilitação de EPI a vencer de `DEMO-P002`, nível A;
   - crítico: manutenção em atraso de `DEMO-A001`;
   - aviso: manutenção próxima do vencimento de `DEMO-A002`;
   - informação: agenda de manutenção desconhecida de `DEMO-A003`;
   - crítico: indicador `PERS_CERT_VALID`, nível C, fora da meta;
   - aviso: indicador `PERS_CERT_VALID`, nível B, fora da meta.
3. Confirme que `DEMO-P004` e `DEMO-A004` **não** geram alerta.
4. Use os filtros "Todos os módulos" e "Todas as gravidades", escolhendo um módulo e uma gravidade.
   - Resultado esperado: a lista mostra só os alertas do filtro.
5. Selecione um alerta e use "Abrir registro".
   - Resultado esperado: o programa abre a página do registro do alerta selecionado.
6. Observe a barra de status e a faixa de alertas da janela principal.
   - Resultado esperado: a contagem de alertas por gravidade corresponde à da página Alertas, e a
     opção "Abrir alertas" leva a ela.

## 8. Página Relatórios: relatório em PDF

A página **Relatórios** tem quatro partes: o relatório em PDF, a exportação de dados, a importação de
dados e os registros de prontidão (instantâneos). Esta seção trata do relatório em PDF.

1. Em "Relatório PDF", use "Criar relatório...". Escolha **Relatório interno**, o idioma Português e,
   em "Arquivo de saída" / "Escolher arquivo...", um arquivo `.pdf` na pasta de trabalho. Deixe
   marcada a opção de gravar um registro das leituras e use "Criar relatório".
   - Resultado esperado: aparece "O relatório interno foi gravado em ..." e o PDF existe. O programa
     avisa que o relatório interno lista os identificadores do pessoal e deve ser tratado como dado
     interno.
2. Abra o PDF.
   - Resultado esperado: título "Relatório de Prontidão QBRN" e "Relatório interno"; a marca "DEMO -
     DADOS FICTÍCIOS"; a data de referência, a versão do aplicativo (1.1.0) e o aviso de versão
     preliminar em todas as páginas; seções de principais números, indicadores, alertas abertos e
     gráficos; os identificadores do pessoal (`DEMO-P...`) aparecem no relatório interno. Os nomes da
     instituição e da unidade e o aviso de manuseio só aparecem se tiverem sido preenchidos em
     Configurações; no banco de demonstração novo estão vazios.
3. Repita com **Relatório anonimizado** (arquivo diferente).
   - Resultado esperado: aparece "O relatório anonimizado foi gravado em ...". O PDF é o "Relatório
     agregado (anonimizado)": não traz identificadores, rótulos nem observações do pessoal, e as
     contagens de pessoal abaixo do limite de contagem pequena (zero incluído) aparecem como
     `< limite`, com a nota de supressão. O **relatório anonimizado é de uso interno**: o programa
     nunca o envia a ninguém, e qualquer divulgação externa é decisão da cadeia de comando.
4. Escolha o relatório interno e dê ao arquivo um nome que pertença ao outro tipo de relatório.
   - Resultado esperado: o programa avisa que o nome do arquivo pertence a outro tipo de relatório e
     pede para alterar o nome ou o relatório.
5. Em "Registros de prontidão", observe a lista.
   - Resultado esperado: os registros retroativos das edições `DEMO-EX-01` a `DEMO-EX-08` (oito, no
     banco de demonstração); `DEMO-EX-09`, que começa no futuro, não tem registro. Os registros dos
     passos 1 e 3, se foram gravados, aparecem com a origem "Com um relatório".

## 9. Página Relatórios: exportação de CSV e exportação de validação

1. Em "Exportação de dados", use "Exportar arquivos CSV...", escolha uma pasta vazia da pasta de
   trabalho.
   - Resultado esperado: o programa avisa que os arquivos contêm dados internos (pessoal, ativos,
     exercícios e orçamento) e, ao continuar, grava um arquivo CSV por entidade. Como o banco é de
     demonstração, **todos os nomes de arquivo começam com `DEMO-`**.
2. Abra um arquivo em um editor de texto.
   - Resultado esperado: o separador é ponto e vírgula, as datas são `AAAA-MM-DD`, e a primeira linha
     traz os códigos das colunas, descritos em [import-templates.md](import-templates.md).
3. Use "Exportação de validação...", escolha outra pasta vazia, marque a gravação de uma leitura
   retroativa para as edições sem registro e confirme.
   - Resultado esperado: a exportação é gravada ("A exportação de validação foi gravada em ...").
     Cada edição iniciada recebe as leituras do seu próprio registro retroativo; `DEMO-EX-09` recebe o
     código de motivo `NO_PRIOR_SNAPSHOT`. Os nomes de arquivo começam com `DEMO-`. Estes arquivos são
     dados internos.
4. Repita a exportação de validação marcando "Ocultar contagens pequenas de pessoal como no relatório
   anonimizado".
   - Resultado esperado: contagens abaixo do limite configurado aparecem como `< limite`; os arquivos
     continuam sendo dados internos.

## 10. Página Configurações

1. Abra **Configurações**.
   - Resultado esperado: uma aba por grupo de configurações (Configurações gerais, Alertas, Metas e as
     seções dos módulos, do backup, dos relatórios e dos instantâneos), cada uma com uma caixa por
     seção.
2. Em "Configurações gerais", observe idioma, identificação do operador, nome da instituição e nome da
   unidade.
   - Resultado esperado: os nomes da instituição e da unidade estão **vazios** por padrão. Eles só
     são preenchidos localmente, nesta página, e nunca vêm do código.
3. Em "Metas", observe a tabela de metas dos indicadores.
   - Resultado esperado: no banco de demonstração, ela lista as metas ilustrativas da seção Painel.
     Uma meta pode ser adicionada, editada, ativada ou desativada e excluída. A meta da taxa de
     execução orçamentária é um valor de fim de exercício, e a nota da página diz que ela é ajustada
     proporcionalmente ao exercício decorrido.
4. Em "Alertas", observe as janelas de aviso (em dias) de habilitações de EPI e de manutenção.
5. Procure um valor marcado "Valor provisório - a confirmar" com o botão "Confirmar".
   - Resultado esperado: valores ainda provisórios mostram a marca e o botão; confirmar muda o estado
     apenas desta instalação.
6. Nas seções de módulos, confira "Cursos" (`DEMO-C1` a `DEMO-C3`), "Tipos de ativo", "Métricas de
   avaliação" e "Fontes de recursos" (DIRSA e Comando da Aeronáutica entre as predefinidas).
   - Resultado esperado: as fontes predefinidas não podem ser excluídas nem ter o código alterado.

## 11. Importação de CSV e modelos

Esta seção grava dados no banco de **demonstração**; as alterações se perdem se os dados de
demonstração forem recriados.

1. Em "Importação de dados", use "Gravar modelos...", escolha uma pasta vazia da pasta de trabalho.
   - Resultado esperado: a pasta recebe um arquivo `<entidade>-template.csv` por entidade (por exemplo,
     `staff_member`), cada um só com a linha de cabeçalho. Se já existirem arquivos, o programa
     pergunta antes de substituí-los.
2. Abra o modelo de `training_course` em um editor de texto e acrescente, abaixo do cabeçalho
   (`code;label_pt_br;label_en_us;label_es_es;active`), a linha fictícia:

   ```text
   007;Curso DEMO sete;Demo course seven;;1
   ```

   Salve como UTF-8.
3. Use "Importar arquivo CSV...", escolha o tipo de dados dos cursos de treinamento
   (`training_course`) e o arquivo do passo 2. Verifique o arquivo **antes** de importar.
   - Resultado esperado: "Nenhum problema encontrado: 1 linhas podem ser importadas." e nada foi
     gravado ainda.
4. Confirme a importação.
   - Resultado esperado: o programa pergunta se deseja importar 1 linha e, ao confirmar, informa que a
     linha foi importada. O curso `007` aparece em Configurações > "Cursos".
5. Importe o mesmo arquivo de novo.
   - Resultado esperado: o arquivo é recusado e nada é importado: "O item já existe; por isso a linha
     foi recusada." (importar só acrescenta linhas; nunca altera uma existente).
6. Crie uma cópia do arquivo com a linha `008;Curso DEMO oito;Demo course eight;;talvez` e verifique-a.
   - Resultado esperado: o programa lista o problema encontrado (a linha 2, a coluna `active`: "O
     valor sim/não não é válido.") e informa que nada é importado até que o arquivo seja corrigido.
7. Salve o arquivo do passo 6 como "ANSI" (codificação do Windows) com um acento no nome do curso e
   verifique-o.
   - Resultado esperado: "O arquivo não é UTF-8 válido. Salve-o como UTF-8 e tente novamente."

## 12. Troca de idioma

1. No menu "Idioma", escolha English (United States), ou use Ctrl+Shift+2.
   - Resultado esperado: a janela inteira muda para inglês **sem reiniciar** (menus, navegação,
     páginas, faixa preliminar: "Preliminary version - indicators not institutionally validated.").
2. Escolha Español (España), ou use Ctrl+Shift+3.
   - Resultado esperado: a janela muda para espanhol, também sem reiniciar.
3. Volte para Português (Brasil) pelo menu ou com Ctrl+Shift+1.
4. Escolha English, feche o programa e abra-o de novo com o mesmo comando do passo 1.1.
   - Resultado esperado: o programa abre em inglês (a escolha foi guardada nas preferências). Volte
     para Português ao terminar.
5. Em cada idioma, abra as oito páginas e a ajuda.
   - Resultado esperado: nenhum texto em outro idioma no meio da tela e nenhum texto cortado. A
     tradução é um rascunho: textos faltantes ou termos estranhos são **achados a anotar** (a
     terminologia está pendente de revisão, Q14).

## 13. Backup em mídia removível e restauração

1. Menu "Arquivo" > "Fazer backup...", ou Ctrl+B. Escolha o arquivo de destino na **mídia removível**
   (o nome sugerido começa com `DEMO-` e termina em `.cbrnbak`).
   - Resultado esperado: o programa não avisa sobre o local, por ser mídia removível. Se você escolher,
     em outra tentativa, a pasta de dados, uma unidade de rede ou uma pasta sincronizada com a
     nuvem, o programa avisa e pergunta se deseja continuar.
2. Informe a frase secreta duas vezes.
   - Resultado esperado: frases diferentes, com menos de 12 caracteres, com poucos caracteres
     diferentes ou fáceis de adivinhar são recusadas com uma explicação. Com uma frase válida, aparece
     "O backup criptografado foi gravado em ..." e o arquivo `.cbrnbak` existe na mídia, e o programa
     lembra de guardar outra cópia em mídia separada.
3. Em Pessoal, adicione a pessoa fictícia `TESTE-002`.
4. Menu "Arquivo" > "Restaurar...", ou Ctrl+Shift+R. Escolha o arquivo do passo 2 e informe uma frase
   secreta **errada**.
   - Resultado esperado: o programa pede a confirmação de que TODOS os dados atuais serão
     substituídos; depois, com a frase errada, mostra "A frase secreta está incorreta. Nada foi
     alterado." e `TESTE-002` continua na lista.
5. Repita a restauração com a frase correta.
   - Resultado esperado: "O backup foi restaurado. Os dados anteriores foram mantidos como ...".
     `TESTE-002` **não** está mais na lista, e os demais dados voltam como estavam no passo 2. Uma
     cópia de segurança dos dados anteriores existe ao lado do banco de dados.
6. Troca entre demonstração e dados reais. Feche o programa e abra-o **sem** `--demo` (em uma pasta
   de dados diferente, por exemplo `--data-dir C:\Temp\cbrn-teste-real`, para não tocar nos dados
   de demonstração). Em "Arquivo" > "Restaurar...", escolha o arquivo `.cbrnbak` do passo 2 (feito a
   partir do banco de demonstração) e informe a frase correta.
   - Resultado esperado: o programa recusa: "Dados de demonstração e dados reais não podem ser
     trocados. Nada foi alterado." Feche o programa.
7. Menu "Arquivo" > "Abrir pasta de dados", ou Ctrl+Shift+O.
   - Resultado esperado: o Explorador de Arquivos abre a pasta de dados.
8. Remova a mídia removível com segurança e guarde o arquivo `.cbrnbak` apenas pelo tempo do teste.

## 14. Ajuda e Sobre

1. Menu "Ajuda" > "Conteúdo da ajuda" (ou F1).
   - Resultado esperado: abre-se a ajuda, com uma lista de tópicos e o texto do tópico escolhido.
2. Menu "Ajuda" > "Sobre".
   - Resultado esperado: a janela mostra "Versão 1.1.0", a licença GNU GPL versão 3 ou posterior, a
     ausência de garantia, a pasta de licenças e a lista de componentes de terceiros.

## 15. Modo somente leitura

O programa abre o banco somente para leitura quando a pasta de dados ou o arquivo do banco não podem
ser gravados e já existe um banco (veja [data-protection.md](data-protection.md) e a seção 10.4 de
[install.pt-BR.md](install.pt-BR.md)). Para provocar isso com segurança, use dados de demonstração
em uma pasta descartável:

1. Feche o programa. Em um PowerShell, execute:

   ```text
   .\cbrn-dashboard.exe --demo --data-dir C:\Temp\cbrn-somente-leitura
   ```

   Feche o programa em seguida, para que o banco de demonstração exista, e marque o arquivo do
   banco como somente leitura:

   ```text
   attrib +R C:\Temp\cbrn-somente-leitura\demo\demo.sqlite3
   ```

   Se o programa continuar gravando, impeça também a gravação na pasta (Propriedades > Segurança) e
   anote o fato.
2. Abra de novo com o mesmo comando do passo 1.
   - Resultado esperado: abre-se o banco de demonstração com uma faixa de aviso do modo somente
     leitura ("Modo somente leitura: não é possível gravar no banco de dados, portanto nada pode ser
     alterado."). Nenhuma pergunta sobre recriar os dados de demonstração é feita.
3. Percorra as páginas Pessoal, Infraestrutura, Exercícios e Orçamento.
   - Resultado esperado: as listas aparecem, mas toda ação que altera dados ("Adicionar ...",
     "Editar ...", "Excluir ...") está desativada, e nada é gravado.
4. Na página **Relatórios**, verifique cada parte.
   - Resultado esperado: "Criar relatório...", "Exportar arquivos CSV..." e "Exportação de
     validação..." continuam disponíveis; a importação de CSV, "Gravar registro" e "Retirar
     registro..." estão desativados.
5. Menu "Arquivo".
   - Resultado esperado: "Fazer backup..." continua disponível e "Restaurar..." está desativado.
6. Observe a pasta `C:\Temp\cbrn-somente-leitura`.
   - Resultado esperado: nenhum arquivo novo foi gravado nela (o registro de execução e as
     preferências ficam na memória; nenhum backup automático nem instantâneo é feito).
7. Feche o programa, desfaça a marca (`attrib -R C:\Temp\cbrn-somente-leitura\demo\demo.sqlite3`) e
   abra de novo.
   - Resultado esperado: o programa volta ao modo normal, sem a faixa.

## 16. Registro do resultado

Preencha a folha abaixo após a execução. A folha em si não deve conter dados reais nem frases
secretas, e é guardada **fora** do repositório. O **resultado** é registrado em
[CHANGELOG.md](../CHANGELOG.md), na entrada da versão testada (a 1.1.0 está em preparação; a
última publicada é a 1.0.2): o status deste teste manual para o
lançamento (data, versão testada, resultado e decisão de publicar o rascunho), sem o conteúdo das
respostas às perguntas em aberto. Depois do registro, a linha "Status da execução" no início deste
documento passa de "NÃO EXECUTADO" para "EXECUTADO em AAAA-MM-DD, resultado: ...".

| Campo | Valor |
|---|---|
| Status da execução | NÃO EXECUTADO |
| Versão testada (janela "Sobre") | |
| Data da execução | |
| Pessoa que executou | |
| Windows (edição e versão) | |
| Painel (seção 2): resultado | |
| Pessoal (seção 3): resultado | |
| Infraestrutura (seção 4): resultado | |
| Exercícios (seção 5): resultado | |
| Orçamento (seção 6): resultado | |
| Alertas (seção 7): resultado | |
| Relatórios, PDF (seção 8): resultado | |
| Relatórios, exportação (seção 9): resultado | |
| Configurações (seção 10): resultado | |
| Importação de CSV e modelos (seção 11): resultado | |
| Troca de idioma (seção 12): resultado | |
| Backup e restauração (seção 13): resultado | |
| Ajuda e Sobre (seção 14): resultado | |
| Modo somente leitura (seção 15): resultado | |
| Passos que falharam (número e mensagem exata) | |
| Achados de terminologia (Q14) | |
| Decisão: publicar o rascunho (sim/não) | |

## 17. O que este roteiro não cobre

- Dados reais: nenhum passo usa dados reais, e este roteiro não substitui a decisão sobre a
  classificação formal dos dados (Q19) nem as respostas a Q4, Q11 e Q13.
- Uma pasta de dados em um caminho de rede (UNC): nunca foi testada em um compartilhamento real.
- O perfil limpo do Windows, o download e as somas de verificação: estão em
  [smoke-test.pt-BR.md](smoke-test.pt-BR.md).
- A validação institucional dos indicadores: as metas de demonstração são ilustrativas, e as metas
  reais são inseridas pelo comitê em Configurações.
