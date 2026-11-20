# Ajuda

## Visão geral
<!-- topic: overview -->

Este programa registra e avalia os dados de prontidão de um comitê: pessoal, infraestrutura, exercícios e orçamento. Todos os dados ficam em um único banco de dados neste computador. O programa não tem acesso à rede.

A janela tem a lista de páginas à esquerda, uma barra de ferramentas com a data de referência, avisos no alto e uma barra de status embaixo. A barra de status mostra as contagens de alertas da data de referência, quando podem ser lidas, e a pasta de dados. Os menus são Arquivo (fazer backup, restaurar, abrir a pasta de dados, sair), Idioma e Ajuda.

No modo somente leitura, um aviso informa isso e toda ação que altera dados fica desativada.

Este guia apenas explica como o programa funciona. Não contém conteúdo clínico nem procedimental.

## Data de referência
<!-- topic: as_of -->

Todos os números das páginas são calculados para a data de referência mostrada na barra de ferramentas. Ao iniciar, ela é a data de hoje e permanece fixa até você alterá-la, mesmo depois da meia-noite.

Escolha outra data no campo de data (ele tem um calendário) para ver a situação naquele dia, por exemplo para consultar o passado. O botão Hoje volta à data atual.

Os indicadores, os alertas, a situação das habilitações de EPI e dos ativos e a execução orçamentária seguem a data de referência. Alterar a data de referência nunca altera os dados armazenados.

## Painel
<!-- topic: dashboard -->

O Painel mostra um cartão para cada indicador, agrupado por módulo: o valor, a unidade, a situação e os limites em vigor. A situação é sempre escrita em texto, junto com uma forma e uma cor, para poder ser lida sem depender da cor. "Sem meta" significa que nenhuma meta foi definida para o indicador. "Sem dados" significa que não há dados a partir dos quais calculá-lo. O programa não combina os indicadores em uma nota geral.

A página também mostra o número de alertas por gravidade e alguns gráficos. Cada gráfico tem a opção "Mostrar como tabela", que mostra os mesmos números em uma tabela.

"Registrar instantâneo" guarda as leituras da data de referência (veja Instantâneos). Ele altera dados, por isso fica desativado no modo somente leitura.

## Pessoal
<!-- topic: personnel -->

A página Pessoal lista o pessoal com filtros, mostra a situação de cada pessoa por nível de habilitação de EPI na data de referência e conta as pessoas por nível. A habilitação de EPI é a habilitação prática em EPI para vestir e retirar o conjunto de proteção de um nível, com data de validade. Selecione uma pessoa para ver as habilitações de EPI, os registros de treinamento e os títulos acadêmicos.

As pessoas são identificadas por um código interno e um rótulo curto opcional. Não digite números de documentos de identidade nem outros dados pessoais: o programa recusa um identificador que se pareça com um número de documento de identidade.

É possível adicionar, editar, desativar e excluir pessoas, e adicionar, editar e excluir habilitações de EPI, registros de treinamento e títulos. "Definir sem renovação" marca que não se espera renovação de uma habilitação, e "Remover sem renovação" desfaz a marca. "Pseudonimizar pessoa" troca o identificador e o texto livre por códigos aleatórios e não pode ser desfeito. Excluir uma pessoa também exclui suas habilitações de EPI, registros de treinamento e títulos. Excluir e pseudonimizar pedem confirmação antes.

A lista de cursos de treinamento fica em Configurações.

## Infraestrutura
<!-- topic: infrastructure -->

A página Infraestrutura lista os ativos por tipo e etiqueta com sua situação na data de referência, a última manutenção e a próxima data prevista. Indicações escritas em texto mostram manutenção atrasada, manutenção próxima do prazo e ativos cujo cronograma de manutenção é desconhecido. A página também mostra a disponibilidade por tipo e o histórico do ativo selecionado.

É possível adicionar, editar, aposentar e excluir ativos, mudar a situação de um ativo, registrar manutenção e editar ou excluir entradas do histórico.

Os tipos de ativo e a regra de disponibilidade, que decide se unidades degradadas contam como disponíveis, ficam em Configurações.

## Antídotos e descontaminantes
<!-- topic: antidotes -->

A página Antídotos e descontaminantes mostra o estoque dos tipos de item antídoto e descontaminante, por lote, na data de referência. Ela guarda apenas dados de gestão: quantidades, lotes, validades, preços e movimentações. Não há campos para doses, indicações ou protocolos, e os códigos de lote e as observações não devem conter informações clínicas.

Um filtro de tipo acima das abas limita a página a um tipo de item. A página tem três abas:

- Lotes e movimentações: um resumo de cada tipo de item, os lotes com sua quantidade, situação e dias até o vencimento, e as movimentações datadas do lote selecionado (entradas, saídas, descartes, perdas e ajustes). Um lote é criado com sua primeira entrada, e a quantidade em qualquer data é a soma das movimentações até essa data. O saldo de um lote nunca pode ficar negativo.
- Aprazamento de vencimentos: os lotes que ainda têm estoque, agrupados por período de vencimento: vencidos, um período para cada mês do horizonte (6, 12 ou 24 meses), mais tarde e sem data de validade.
- Alertas: os alertas de estoque desses tipos de item na data de referência. "Abrir registro" seleciona o lote na primeira aba, ou define o filtro de tipo para um alerta sobre um tipo de item.

Adicionar, editar e excluir lotes e movimentações altera dados, por isso fica desativado no modo somente leitura. O prazo de aviso de vencimento e o estoque mínimo de cada tipo ficam em Configurações. O Painel tem um atalho para esta página.

## Exercícios
<!-- topic: exercises -->

A página Exercícios lista as edições de exercícios, que podem ser filtradas por tipo, e, abaixo delas, os resultados de avaliação da edição selecionada.

Uma edição tem um código, um tipo, uma data de início e uma data de término, e pode ter um número de participantes. Esse número é apenas uma contagem; nunca digite nomes.

Um resultado é o valor de uma métrica de avaliação em uma edição, e o valor deve estar dentro da escala da métrica. É possível adicionar, editar e excluir edições e resultados. As métricas de avaliação ficam em Configurações.

## Orçamento
<!-- topic: budget -->

A página Orçamento mostra, para um ano fiscal, um resumo por fonte de recursos e moeda: o valor alocado, o valor executado até a data de referência e a taxa de execução. As moedas aparecem em linhas separadas e nunca são somadas.

Abaixo do resumo ficam as entradas do ano e, para a entrada selecionada, suas linhas de execução datadas. É possível adicionar, editar e excluir entradas e execuções.

As fontes de recursos, a moeda padrão e a opção de proporcionalidade ficam em Configurações.

## Alertas
<!-- topic: alerts -->

A página Alertas lista os alertas da data de referência: a gravidade (crítica, de aviso ou informativa) em texto e ícone, o módulo, o assunto, a data de vencimento e uma mensagem. A lista pode ser filtrada por módulo e por gravidade.

Dê um clique duplo em um alerta, pressione Enter sobre ele ou use "Abrir registro" para ir à página do registro a que ele se refere.

Os alertas nunca são armazenados; eles são calculados a cada vez a partir dos dados e da data de referência. A página apenas lê dados, por isso também funciona no modo somente leitura.

A barra de status mostra as contagens de alertas. Ao iniciar, um aviso pode resumir os alertas de aviso e críticos, com um botão que abre esta página. Quantos dias antes do vencimento de uma habilitação de EPI ou de uma manutenção um alerta é gerado é definido em Configurações.

## Relatórios
<!-- topic: reports -->

A página Relatórios oferece:

- "Criar relatório..." grava o relatório PDF da data de referência, interno ou anonimizado. O relatório anonimizado contém apenas contagens, e contagens abaixo de um limite são suprimidas; o limite é definido em Configurações. Toda página de todo relatório traz o aviso de versão preliminar, e um relatório feito a partir do banco de demonstração é marcado como fictício.
- "Exportar arquivos CSV..." grava os dados dos módulos em arquivos CSV, um arquivo por tipo de dado, em uma pasta que você escolhe.
- "Exportação de validação..." grava os arquivos para a validação dos indicadores, montados a partir dos instantâneos e das edições de exercícios. Ela pode registrar instantâneos retroativos para edições sem instantâneo anterior e informa quantos.
- "Importar arquivo CSV..." e "Gravar modelos..." (veja Importação).
- A lista de instantâneos, chamados de "registros" nessa página (veja Instantâneos).

O relatório, a exportação CSV e a exportação de validação também funcionam no modo somente leitura.

Os arquivos que você exporta são arquivos comuns. Eles contêm dados internos e não são protegidos pelo programa: guarde-os onde somente as pessoas autorizadas possam lê-los.

## Importação
<!-- topic: import -->

"Importar arquivo CSV..." na página Relatórios lê um arquivo CSV de um tipo de dado, por exemplo para registrar dados do passado. "Gravar modelos..." grava arquivos vazios, apenas com a linha de cabeçalho, em uma pasta que você escolhe; preencha-os ou edite uma exportação.

O arquivo deve ser UTF-8, e o separador é ponto e vírgula ou vírgula. Importe um tipo de dado por vez e importe primeiro as listas a que os outros registros se referem: as listas (cursos, tipos de ativo, métricas e fontes de recursos), depois o pessoal, as habilitações de EPI, registros de treinamento e títulos, os ativos, seus eventos de situação e de manutenção, as edições de exercícios com seus países e resultados, as entradas de orçamento e, por fim, as execuções orçamentárias.

Um arquivo é importado por inteiro ou não é importado. Se alguma linha tiver problema, nada é gravado e os problemas são informados. A janela de importação permite verificar um arquivo antes. A importação apenas adiciona registros: um registro existente nunca é alterado nem mesclado. A importação fica desativada no modo somente leitura.

## Instantâneos
<!-- topic: snapshots -->

Um instantâneo guarda as leituras dos indicadores e a configuração em vigor em uma data, para que o que se sabia naquele momento possa ser visto depois. É possível registrar um com "Registrar instantâneo" no Painel ou com "Gravar registro" na página Relatórios, que chama os instantâneos de "registros". Para uma data passada, o programa pede confirmação antes.

Os instantâneos nunca são alterados nem excluídos. "Retirar registro..." pede um motivo e marca o instantâneo como retirado: ele continua armazenado e fica oculto, a menos que você marque "Mostrar registros retirados".

Ao iniciar, o programa pode registrar um instantâneo por mês por conta própria. Ele não faz isso no modo somente leitura, com dados de demonstração nem quando o relógio do computador parece incorreto. A seção Instantâneos das Configurações contém as opções.

Registrar e retirar alteram dados, por isso ficam desativados no modo somente leitura.

## Backup e restauração
<!-- topic: backup -->

Os dados são um único arquivo SQLite na pasta de dados, que a barra de status mostra. O programa faz uma cópia simples dele uma vez por dia e uma cópia antes de cada atualização do banco de dados, na pasta de backups. Essas cópias são tão sensíveis quanto o banco de dados e ficam no mesmo disco. Faça backups criptografados manualmente e guarde-os em mídia separada.

### Fazer backup...
<!-- topic: backup_make -->

Arquivo, "Fazer backup..." pergunta o arquivo a gravar e depois pede uma senha duas vezes. A senha precisa ter pelo menos 12 caracteres e não pode ser uma palavra comum. O programa grava um arquivo de backup criptografado (.cbrnbak). A senha nunca é armazenada e não pode ser recuperada: sem ela o arquivo não pode ser aberto.

Fazer backup também funciona no modo somente leitura. Um aviso lembra você quando o último backup criptografado é mais antigo que o número de dias configurado ou quando nunca foi feito um.

### Restaurar...
<!-- topic: backup_restore -->

Arquivo, "Restaurar..." substitui TODOS os dados atuais pelo conteúdo de um arquivo de backup. Ele pede que você confirme e depois pede a senha. Antes de copiar, o programa faz uma cópia de segurança dos dados atuais e, se a restauração falhar, devolve os dados como estavam. Um backup do banco de demonstração não pode ser restaurado sobre um banco real, nem o contrário.

Restaurar fica desativado no modo somente leitura. Após uma restauração bem-sucedida, todas as páginas mostram os dados restaurados.

### Abrir pasta de dados
<!-- topic: backup_folder -->

Arquivo, "Abrir pasta de dados" mostra a pasta de dados no Explorador de Arquivos do Windows. Ele só abre uma pasta local existente, nunca um local de rede.

## Configurações
<!-- topic: settings -->

A página Configurações tem uma aba para cada grupo de configurações e uma caixa para cada seção:

- Geral: o idioma, um rótulo de operador opcional registrado em cada alteração e os nomes da instituição e da unidade.
- Alertas: quantos dias antes de um vencimento ou de uma data prevista um alerta é gerado.
- Metas: as metas dos indicadores, que podem ser adicionadas, editadas, ativadas ou desativadas e excluídas. Enquanto uma meta não for definida, o indicador mostra "Sem meta".
- Pessoal, Infraestrutura, Exercícios e Orçamento: as listas e as regras de cada módulo, como descrito em suas páginas.
- Backup, Relatórios e Instantâneos: as configurações de backups, de relatórios e de instantâneos.

Alguns valores são provisórios e ainda precisam ser confirmados pelo comitê. Eles trazem a marca "Valor provisório - a confirmar" e um botão Confirmar.

## Privacidade
<!-- topic: privacy -->

- Os dados ficam neste computador, na pasta de dados. Por padrão ela é `%LOCALAPPDATA%\cbrn-readiness-dashboard`, e a barra de status a mostra. O programa não tem código de rede: nenhuma verificação de atualizações, nenhuma telemetria e nenhum envio de dados.
- O pessoal é identificado por um código interno. O programa não guarda números de documentos de identidade, datas de nascimento, dados de contato nem dados de saúde.
- O registro de eventos (log) contém apenas códigos de eventos, nunca o conteúdo dos registros.
- O programa não consegue verificar se o disco deste computador está criptografado. A documentação exige criptografia de disco completo, por exemplo o BitLocker. Arquivos que você exporta ou copia para mídia removível não são protegidos pelo programa.
- Um aviso alerta quando a pasta de dados está em um compartilhamento de rede ou dentro de uma pasta sincronizada pelo OneDrive.
- "Sensível" é apenas um rótulo de trabalho para dados que ficam neste computador; não é uma classificação formal. Não digite dados reais até que as questões em aberto Q19, Q4, Q11 e Q13 sejam respondidas. Até lá, use apenas dados de demonstração, que trazem um aviso DEMO permanente.

## Situação preliminar
<!-- topic: preliminary -->

O aviso "Versão preliminar — indicadores não validados institucionalmente." aparece sempre no alto da janela. Ele também está em todas as páginas de todo relatório PDF e na janela Sobre.

Ele significa que os indicadores e seus limites ainda não foram validados pela instituição. Valores marcados como "Valor provisório - a confirmar" são provisórios. Trate todo número como preliminar.
