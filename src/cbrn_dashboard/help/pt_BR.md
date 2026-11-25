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

### Estoque (lotes)
<!-- topic: infrastructure_stock -->

A página tem duas abas. "Equipamentos e instalações (unidades)" guarda os ativos descritos acima. "Estoque (lotes)" registra o que é mantido em estoque, por lote em vez de unidade por unidade: antídotos, descontaminantes, detectores, equipamentos de proteção e outros itens. Um lote não tem situação operacional nem manutenção. Um item que precisa de estoque e também de acompanhamento unidade por unidade é registrado duas vezes, uma em cada aba. O estoque guarda apenas dados de gestão: não há campos para doses, indicações ou protocolos, e os códigos de lote e as observações não devem conter informações clínicas.

Lotes. Um lote pertence a um tipo de item (17 tipos já vêm com o programa, e você pode adicionar os seus em Configurações) e tem um código de lote, único dentro do tipo, uma data de validade, um preço unitário com sua moeda e observações. A validade, o preço e as observações são opcionais, exceto que os lotes de antídotos e de descontaminantes precisam de data de validade. As quantidades são unidades inteiras. Um lote é criado junto com sua primeira entrada: a data, a quantidade (mínimo 1) e uma referência. "Adicionar lote", "Editar lote" e "Excluir lote" atuam sobre o lote selecionado; excluir um lote também exclui suas movimentações e pede confirmação antes.

Movimentações. Cada movimentação tem uma data, um tipo, uma quantidade maior que zero, uma referência e uma observação. Os tipos são Entrada (recebimento), Saída (consumo), Descarte, Perda, Ajuste (acréscimo) e Ajuste (redução). Uma entrada e um acréscimo somam ao lote; os demais tipos retiram dele. Um ajuste precisa de uma observação. "Registrar movimentação" acrescenta uma movimentação ao lote selecionado, e as movimentações do lote selecionado são listadas com o saldo após cada uma. A última movimentação de um lote não pode ser excluída: encerre um lote com um descarte ou uma perda.

Quantidade em uma data. A quantidade de um lote nunca é armazenada. Ela é calculada como a soma das movimentações datadas até a data de referência, inclusive, por isso mudar a data de referência mostra o estoque daquele dia. O saldo de um lote nunca pode ficar negativo em nenhuma data: o programa recusa uma movimentação nova, editada ou excluída, e uma linha importada, que deixaria o lote abaixo de zero em alguma data, mesmo que seja retroativa. Uma movimentação não pode ter data posterior a hoje.

Situação. Todo lote mostra uma situação, escrita em texto com ícone e cor:

- Ainda não recebido: nenhuma movimentação tem data até a data de referência.
- Esgotado: não há nada em estoque. Lotes esgotados nunca geram alerta e ficam ocultos, a menos que você marque "Mostrar lotes esgotados".
- Vencido: a validade é anterior à data de referência e o lote ainda tem estoque.
- A vencer: o lote vence dentro do prazo de aviso a partir da data de referência.
- Válido: o lote não tem data de validade, ou a validade ainda não passou. Um lote ainda é válido no próprio dia da validade.

A aba também mostra um resumo de cada tipo de item: a quantidade válida, a quantidade vencida ainda em estoque, a quantidade a vencer, o estoque mínimo, se o tipo está abaixo dele e o valor do estoque válido. Os valores aparecem por moeda e nunca são somados entre moedas.

Filtro de tipo. O filtro Tipo acima das abas lista "Todos os tipos", os tipos de ativo e os tipos de item de estoque. Um tipo de ativo mostra a primeira aba, e um tipo de item de estoque mostra esta aba apenas com os lotes desse tipo. "Todos os tipos" não filtra nada e mantém a aba em que você está. Trocar de aba manualmente nunca muda o filtro.

Configurações. O estoque mínimo de cada tipo de item é definido na seção "Tipos de item de estoque" das Configurações, e o prazo de aviso antes de um vencimento é definido nas configurações de Alertas.

Alertas. Um lote vencido que ainda tem estoque é crítico, um lote a vencer é um aviso, e um tipo de item cuja quantidade válida está abaixo do mínimo é crítico. Um tipo sem mínimo nunca está abaixo dele. O Painel também mostra indicadores do estoque válido, dos lotes a vencer, dos lotes vencidos em estoque e dos itens abaixo do estoque mínimo.

Adicionar, editar e excluir lotes e movimentações altera dados, por isso fica desativado no modo somente leitura, enquanto as tabelas continuam legíveis.

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

Três tipos de alerta vêm do estoque: um lote vencido que ainda tem estoque (crítico), um lote que vence dentro do prazo de aviso (aviso) e um tipo de item cuja quantidade válida está abaixo do estoque mínimo (crítico). "Abrir registro" vai para a aba de estoque da Infraestrutura ou, para esses tipos de item, para a página Antídotos e descontaminantes. Lotes esgotados nunca geram alerta.

## Relatórios
<!-- topic: reports -->

A página Relatórios oferece:

- "Criar relatório..." grava o relatório PDF da data de referência, interno ou anonimizado. O relatório anonimizado contém apenas contagens, e contagens abaixo de um limite são suprimidas; o limite é definido em Configurações. Um relatório feito a partir do banco de demonstração é marcado como fictício.
- "Exportar arquivos CSV..." grava os dados dos módulos em arquivos CSV, um arquivo por tipo de dado, em uma pasta que você escolhe.
- "Exportação de validação..." grava os arquivos para a validação dos indicadores, montados a partir dos instantâneos e das edições de exercícios. Ela pode registrar instantâneos retroativos para edições sem instantâneo anterior e informa quantos.
- "Importar arquivo CSV..." e "Gravar modelos..." (veja Importação).
- A lista de instantâneos, chamados de "registros" nessa página (veja Instantâneos).

O relatório, a exportação CSV e a exportação de validação também funcionam no modo somente leitura.

Os arquivos que você exporta são arquivos comuns. Eles contêm dados internos e não são protegidos pelo programa: guarde-os onde somente as pessoas autorizadas possam lê-los.

## Importação
<!-- topic: import -->

"Importar arquivo CSV..." na página Relatórios lê um arquivo CSV de um tipo de dado, por exemplo para registrar dados do passado. "Gravar modelos..." grava arquivos vazios, apenas com a linha de cabeçalho, em uma pasta que você escolhe; preencha-os ou edite uma exportação.

O arquivo deve ser UTF-8, e o separador é ponto e vírgula ou vírgula. Importe um tipo de dado por vez e importe primeiro as listas a que os outros registros se referem: as listas (cursos, tipos de ativo, métricas, fontes de recursos e tipos de item de estoque), depois o pessoal, as habilitações de EPI, registros de treinamento e títulos, os ativos, seus eventos de situação e de manutenção, as edições de exercícios com seus países e resultados, as entradas de orçamento, as execuções orçamentárias, depois os lotes de estoque e, por fim, as movimentações de estoque. Um arquivo de lotes cria os lotes sem nenhuma quantidade; a quantidade vem das movimentações, por isso importe-as em seguida. As movimentações de estoque seguem as mesmas regras da tela: uma linha que deixaria o saldo de um lote negativo, ou que tenha data posterior a hoje, é recusada. Tipos de item de estoque padrão nunca são importados.

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
- Alertas: quantos dias antes de um vencimento ou de uma data prevista um alerta é gerado. Isso inclui o campo "Lotes de estoque: antecedência do alerta de vencimento (dias)", o prazo de aviso antes do vencimento de um lote de estoque (90 dias por padrão).
- Metas: as metas dos indicadores, que podem ser adicionadas, editadas, ativadas ou desativadas e excluídas. Enquanto uma meta não for definida, o indicador mostra "Sem meta".
- Pessoal, Infraestrutura, Exercícios e Orçamento: as listas e as regras de cada módulo, como descrito em suas páginas.
- Infraestrutura também tem a seção "Tipos de item de estoque": os 17 tipos de item padrão e os seus próprios. Para cada tipo é possível definir o estoque mínimo, que fica vazio (sem mínimo) até você defini-lo, e deixar o tipo ativo ou inativo; um tipo padrão não pode ser excluído, e a categoria de um tipo não muda depois que ele tem lotes. O estoque mínimo é guardado apenas neste computador.
- Backup, Relatórios e Instantâneos: as configurações de backups, de relatórios e de instantâneos.

## Privacidade
<!-- topic: privacy -->

- Os dados ficam neste computador, na pasta de dados. Por padrão ela é `%LOCALAPPDATA%\cbrn-readiness-dashboard`, e a barra de status a mostra. O programa não tem código de rede: nenhuma verificação de atualizações, nenhuma telemetria e nenhum envio de dados.
- O pessoal é identificado por um código interno. O programa não guarda números de documentos de identidade, datas de nascimento, dados de contato nem dados de saúde.
- O registro de eventos (log) contém apenas códigos de eventos, nunca o conteúdo dos registros.
- O programa não consegue verificar se o disco deste computador está criptografado. A documentação exige criptografia de disco completo, por exemplo o BitLocker. Arquivos que você exporta ou copia para mídia removível não são protegidos pelo programa.
- Um aviso alerta quando a pasta de dados está em um compartilhamento de rede ou dentro de uma pasta sincronizada pelo OneDrive.
- "Sensível" é apenas um rótulo de trabalho para dados que ficam neste computador; não é uma classificação formal. Os dados de demonstração trazem um aviso DEMO permanente.
