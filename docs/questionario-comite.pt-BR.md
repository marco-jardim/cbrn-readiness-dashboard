# Questionário para o comitê de defesa QBRN (CDQBRN/HFAG)

**Versão preliminar - indicadores não validados institucionalmente.**

## Para que serve este questionário

O CBRN Readiness Dashboard é um aplicativo para Windows, que funciona sem rede, para acompanhar a
prontidão do hospital diante de incidentes químicos, biológicos, radiológicos e nucleares: pessoal
habilitado, leitos, baias e equipamentos, exercícios, orçamento, alertas e relatórios. A versão atual
(1.0.2) é **preliminar**: ela ainda não foi validada pela instituição.

Muitas decisões do aplicativo dependem de respostas do comitê. Enquanto uma pergunta não é
respondida, o aplicativo usa uma **resposta de trabalho** provisória, descrita em cada pergunta no
campo "Como o aplicativo funciona hoje". Nenhuma pergunta impede o uso do aplicativo com dados de
demonstração.

**Atenção: nenhum dado real pode ser inserido no aplicativo até que as perguntas Q19, Q4, Q11 e Q13
(seção 1) sejam respondidas.** Até lá, use só os dados fictícios do modo de demonstração
(`--demo`). Veja também [data-protection.md](data-protection.md) (em inglês).

### Onde as respostas ficam

- As respostas são registradas em um **documento privado, fora do repositório**. Este arquivo é só o
  questionário: não escreva nele o conteúdo das respostas.
- O repositório guarda apenas o **status** de cada pergunta (em aberto, respondida e aplicada
  localmente, ou respondida e implementada em uma tarefa), nunca o conteúdo da resposta
  (tarefa T10.5 do plano, [PLAN.md](../PLAN.md), seção 12).
- Os valores que dependem de cada instalação (metas dos indicadores, nomes da instituição e da
  unidade, aviso de manuseio do relatório interno) são digitados só em **Configurações**, no próprio
  computador, e nunca vão para o repositório.

### Como preencher

Cada pergunta traz: o texto da pergunta; **Como o aplicativo funciona hoje** (a resposta de trabalho
até que haja resposta); **Quem responde**; e um espaço para a resposta. Se preferir, preencha só o
campo "Decisão registrada em" e guarde o conteúdo da resposta no documento privado.

Os códigos entre parênteses (por exemplo, P01, A02) são as hipóteses e os valores provisórios da
seção 3.5 do [PLAN.md](../PLAN.md). As perguntas Q18 e Q20 a Q24 são técnicas ou do responsável pelo
projeto e **não** fazem parte deste questionário: o responsável pelo projeto cuida delas.

---

## 1. Perguntas que bloqueiam dados reais

### Q19 - Classificação formal

**Pergunta.** Algum destes dados está formalmente classificado ou tem acesso restrito, pela lei de
acesso à informação (Lei 12.527/2011, arts. 23 a 28) ou por normas militares? Pela leitura do plano
(não é parecer jurídico), a classificação é feita por decisão formal da autoridade competente
(Lei 12.527/2011, art. 28; Decreto 7.845/2012, art. 19). O Decreto 7.845/2012 exige, para informação
classificada, recursos criptográficos baseados em algoritmo de Estado e equipamento isolado
(arts. 31, 39 e 40). Pela leitura do plano, também não é parecer jurídico: se os dados forem
classificados, este projeto (banco SQLite sem criptografia, backups automáticos sem criptografia,
criptografia comercial, binário não assinado vindo de repositório público) não serve, e dados reais
não devem ser inseridos.

**Como o aplicativo funciona hoje.** Só dados de demonstração são usados. "Sensível", neste projeto,
é um rótulo de trabalho, não uma classificação.

**Quem responde.** O comitê, com os assessores de segurança da informação e jurídico da instituição.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

### Q4 - Dados do pessoal e categorias

**Pergunta.** Quais dados pessoais o aplicativo pode guardar, segundo a leitura da instituição sobre a
LGPD? O plano propõe um código interno por pessoa e um rótulo curto opcional, sem CPF ou outros
números de documento, sem data de nascimento, sem dados de contato e sem dados de saúde. Deve-se
registrar uma categoria profissional e, se sim, quais categorias? A ação "pseudonimizar pessoa"
(o identificador é trocado por um código aleatório, os textos livres são apagados ou trocados por
códigos aleatórios e o histórico é mantido) é uma resposta aceitável a um pedido de eliminação de
dados? Quem sai e depois volta pode ser cadastrado como um registro novo (A14)? *Leitura do plano,
não parecer jurídico:* a exclusão da defesa nacional (LGPD, art. 4º, III) exige finalidade exclusiva
e provavelmente não cobre dados de gestão de pessoal; e um código interno é pseudonimização, de modo
que o dado continua sendo pessoal (art. 13, §4º).

**Como o aplicativo funciona hoje.** Só existem o código interno, um rótulo opcional e uma lista de
categorias livre e vazia. Nenhum dado real é inserido.

**Quem responde.** O comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

### Q11 - Segurança da informação

**Pergunta.** Quais normas da instituição se aplicam a estes dados? Em especial: é exigida a
criptografia do próprio arquivo do banco de dados, além da criptografia de disco completo da estação
de trabalho? Onde os backups podem ser guardados? Existe uma política de frases secretas? Exige-se
Argon2id, em vez de scrypt, para a chave do backup? Depois de quantos dias deve aparecer o lembrete
de um backup criptografado antigo (P09)?

**Como o aplicativo funciona hoje.** Proteção pelo sistema operacional, redução ao mínimo dos dados,
backups manuais criptografados e frase secreta com no mínimo 12 caracteres (P05); lembrete depois de
30 dias (P09). Nenhum dado real é inserido.

**Quem responde.** O comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

### Q13 - Implantação

**Pergunta.** Como o aplicativo será instalado nos computadores do hospital? Um executável não
assinado, entregue em um zip com uma pasta, é aceitável? Um arquivo `.exe` único é obrigatório?
Espera-se assinatura de código? Que tipo de perfil do Windows é usado (itinerante, obrigatório, não
persistente/VDI)? Um perfil obrigatório ou não persistente descarta `%LOCALAPPDATA%` quando o usuário
encerra a sessão. AppLocker, WDAC ou Smart App Control estão em vigor e em quais pastas é permitido
executar programas?

**Como o aplicativo funciona hoje.** Um zip com uma pasta, sem assinatura, com checksums, uma lista de
verificação arquivo por arquivo e uma atestação de proveniência da compilação. Nenhum dado real é
inserido.

**Quem responde.** O comitê, com quem administra esses computadores.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

---

## 2. Indicadores e regras

### Q1 - Indicadores e metas

**Pergunta.** A lista proposta de indicadores está certa, inclusive o indicador proposto pelo projeto
`EX_DAYS_SINCE_LAST` (dias desde o último exercício)? Quais indicadores formam o "padrão esperado de
prontidão" (L82) e quais valores de aviso e de situação crítica valem para cada um? Por exemplo,
um número mínimo de pessoas com habilitação prática válida em EPI nível A?

**Como o aplicativo funciona hoje.** Nenhuma meta é definida (P03). Todo indicador aparece como
"Sem meta" e não gera alerta de indicador.

**Quem responde.** O comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

### Q2 - Habilitação em EPI e reciclagem

**Pergunta.** O aplicativo registra a **habilitação prática em EPI nível A/B/C (treino de vestir e
retirar)**. Cada nível (A, B, C) tem prazo de validade fixo e qual é ele? Uma habilitação de um nível
vale também para outros níveis e, se sim, para quais? O que torna necessária a reciclagem: só o
vencimento, ou também o tempo decorrido ou o número de horas? Quantos dias antes do vencimento os
alertas devem começar?

Também em aberto: o aplicativo deve registrar os **ensaios de vedação de respiradores** (*fit test*:
modelo, tamanho e data; validade de 12 meses, segundo a OSHA 29 CFR 1910.134(f)(2) e o PPR da
Portaria MTP 672/2021) e a **liberação médica para uso de respirador**? Registrá-los exigiria novas
tarefas de desenvolvimento.

**Como o aplicativo funciona hoje.** Os níveis são contados de forma independente (A02), a data de
validade é digitada em cada habilitação (A03, A04), reciclagem significa vencida ou a vencer, e a
janela de aviso é de 90 dias (P01). Ensaios de vedação e liberação médica não são registrados.

**Quem responde.** O comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

### Q3 - Capacitações e titulações

**Pergunta.** Quais tipos de capacitação devem ser registrados, isto é, o que entra na lista de
cursos? As titulações em andamento devem ser registradas junto com as concluídas?

**Como o aplicativo funciona hoje.** A lista de cursos está vazia e pode ser editada (A09). As
titulações têm situação "concluída" ou "em andamento" (A10).

**Quem responde.** O comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

### Q5 - Leitos e baias

**Pergunta.** "Leitos e baias disponíveis" (L76) significa unidades instaladas e em condição de
funcionar, ou unidades livres em um dado momento? Quais categorias de situação são necessárias e a
situação "degradado" conta como disponível? Um equipamento que sai de serviço e volta é cadastrado
como registro novo (A14)?

**Como o aplicativo funciona hoje.** "Disponível" significa em serviço e operacional (A01, A05);
"degradado" conta como indisponível. A ocupação (quantos estão livres) não é acompanhada: isso exigiria
novas tarefas.

**Quem responde.** O comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

### Q6 - Equipamentos e manutenção

**Pergunta.** Os "equipamentos de pressão negativa e filtragem" devem ser uma categoria só ou várias?
Qual é o intervalo de manutenção de cada tipo e com quantos dias de antecedência os alertas de
manutenção devem começar?

**Como o aplicativo funciona hoje.** Existe um tipo embutido, com o texto do apêndice (A06). Os
intervalos não estão definidos ("agenda desconhecida") e a janela de aviso é de 30 dias (P02).

**Quem responde.** O comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

### Q7 - Exercícios

**Pergunta.** Quais resultados agregados de avaliação ("resultados agregados de avaliação", L78)
devem ser registrados: nomes das métricas, escalas e unidades? Além das edições do CBRAMED e do
EXBRAMED, outros cursos ou exercícios devem ser registrados? Basta o total de participantes, ou são
necessários detalhamentos? Algum código de país fora do ISO 3166-1 alfa-2 é necessário (o CLDR tem
mais códigos, como `XK`)?

**Como o aplicativo funciona hoje.** A lista de métricas está vazia e é definida pelo usuário (A07). Os
tipos são CBRAMED, EXBRAMED e outro (A13). Só o total de participantes é registrado; o detalhamento
ficaria para uma etapa futura.

**Quem responde.** O comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

### Q8 - Orçamento

**Pergunta.** Quais etapas da execução orçamentária devem ser acompanhadas? Em quais moedas são
registrados os valores do Comando da Aeronáutica (COMAER) e da DIRSA, e é necessária conversão? O
exercício financeiro é o ano civil? Há outras fontes de recursos? A meta de execução deve ser
distribuída proporcionalmente ao longo do exercício (padrão de trabalho, P08)? BRL, USD e EUR bastam
como moedas?

**Como o aplicativo funciona hoje.** São acompanhados um valor alocado e linhas de execução com data
(A08). As fontes de recursos já cadastradas são o Comando da Aeronáutica (COMAER) e a DIRSA. O item
do Fundo Fiduciário (*Trust Fund*) da OPCW é a contribuição do Brasil, e **não** uma receita do
hospital. A moeda padrão é BRL; moedas nunca são misturadas nem convertidas. O exercício é o ano civil
e a meta de execução é distribuída linearmente (P08). Mais etapas ou conversão de moeda exigiriam novas
tarefas.

**Quem responde.** O comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

### Q9 - Leitura da prontidão e validade preditiva (L87)

**Pergunta.** Deseja-se uma única nota composta de prontidão e, se sim, com qual fórmula e quais
pesos? Como o desempenho realmente observado no próximo EXBRAMED será medido e registrado? Com que
frequência o aplicativo deve gravar retratos do estado dos indicadores (*snapshots*)?

**Como o aplicativo funciona hoje.** Nenhuma nota composta é calculada. A "leitura" é o conjunto de
todos os valores dos indicadores em um retrato. Os retratos são gravados uma vez por mês e a cada
relatório (P04). Uma nota composta ficaria para uma etapa futura.

**Quem responde.** A pessoa autora da tese, com o comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

---

## 3. Relatórios, usuários e implantação

### Q10 - Relatórios

**Pergunta.** O que deve conter o relatório interno (para o comitê, a DIRSA e o Comando da
Aeronáutica) e o relatório agregado e anonimizado (a tese, L69, cita o Secretariado Técnico da OPCW
como possível destinatário)? Em quais idiomas? Abaixo de qual número os totais de pessoal devem ser
ocultados no relatório anonimizado? PDF e CSV bastam, ou é preciso XLSX? Que regra de divulgação o
destinatário aplica a relatórios anonimizados sucessivos, já que a diferença entre dois relatórios
pode revelar um número ocultado? O aviso de manuseio do relatório interno é necessário e o que ele
diz (definido localmente, nunca no repositório)?

**Como o aplicativo funciona hoje.** São gerados os dois relatórios em PDF, no idioma escolhido na
interface. No relatório anonimizado, contagens derivadas do pessoal abaixo de 5 (zero inclusive) são
ocultadas, com ocultação secundária (A11); o risco de comparar dois relatórios é um risco residual
documentado. **O relatório anonimizado é de uso interno**: o aplicativo nunca envia nada para fora, e
qualquer divulgação externa é uma decisão da cadeia de comando. O aviso de manuseio fica vazio (P10).
Há também limitações conhecidas: o relatório anonimizado imprime como foram digitados os códigos
informados pelo operador (fonte de recursos, tipo de ativo e edição) e o código da fonte embutida
`DIRSA`, como nome próprio; e uma relação não declarada (pessoal ativo menos pessoal válido por nível)
pode revelar um número ocultado de vencidos. XLSX ficaria para uma etapa futura.

**Quem responde.** O comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

### Q12 - Usuários e histórico

**Pergunta.** Uma pessoa por instalação mantém os dados, ou várias pessoas precisam editar os mesmos
dados? O histórico de alterações pode registrar o nome do operador e por quanto tempo deve ser
guardado? Se várias pessoas se revezam em um computador, elas dividirão uma conta do Windows ou usarão
uma pasta local restrita ao comitê por meio de `--data-dir` (contas do Windows separadas têm bancos de
dados separados)? Por quanto tempo podem ser guardados backups que contêm valores apagados ou
pseudonimizados?

**Como o aplicativo funciona hoje.** Um único operador local, um rótulo de operador opcional e o
histórico de alterações guardado sem prazo (valores de texto livre com dado pessoal não entram no
histórico) (A12). O uso compartilhado por várias pessoas ao mesmo tempo, e uma ferramenta de retenção
ou de apagamento, ficariam para uma etapa futura.

**Quem responde.** O comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

### Q15 - Aviso de versão preliminar

**Pergunta.** O que deve dizer o aviso "versão preliminar, não validada institucionalmente" e onde ele
deve aparecer na interface e nos relatórios?

**Como o aplicativo funciona hoje.** O texto provisório ("Versão preliminar - indicadores não validados
institucionalmente.") aparece na faixa da interface, em todas as páginas de PDF, na janela "Sobre", nas
notas de primeira execução e nas notas da versão (P07).

**Quem responde.** A pessoa autora da tese, com o comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

### Q16 - Dados retroativos, 2022 a 2025 (L87)

**Pergunta.** Em que forma estes registros existem (planilhas, documentos, tabelas), para que os modelos
de importação de CSV sigam a estrutura deles? Só a estrutura é necessária, nunca os dados.

**Como o aplicativo funciona hoje.** Os modelos seguem o modelo de dados do plano (seção 5.2) e os
registros ainda podem ser digitados à mão.

**Quem responde.** O comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

### Q17 - Cabeçalho dos relatórios

**Pergunta.** Quais nomes de instituição e de unidade devem aparecer no cabeçalho dos relatórios? Eles
são definidos localmente em Configurações e nunca ficam no repositório.

**Como o aplicativo funciona hoje.** Os nomes ficam vazios e o cabeçalho mostra só o título do
relatório, a data de referência e a versão do aplicativo.

**Quem responde.** O comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

---

## 4. Terminologia

### Q14 - Revisão da terminologia

**Pergunta.** O comitê pode revisar os termos da interface em pt-BR, en-US e es-ES - por exemplo, os
nomes dos níveis de EPI, "baia", "reciclagem" e os equivalentes em espanhol e em inglês de
"prontidão"? A lista de termos para revisar está em
[revisao-terminologia.pt-BR.md](revisao-terminologia.pt-BR.md).

**Como o aplicativo funciona hoje.** São usadas traduções provisórias (rascunhos, marcadas como
`unfinished`) e a situação da revisão consta como pendente no registro de alterações.

**Quem responde.** O comitê.

**Resposta:**

_______________________________________________________________________________

_______________________________________________________________________________

Decisão registrada em: ____ / ____ / ________  por: ______________________________

---

## Perguntas que não fazem parte deste questionário

As perguntas Q18 e Q20 a Q24 do plano tratam da rastreabilidade dos requisitos, das licenças de
terceiros, da primeira publicação e da configuração do repositório. São assuntos técnicos e do
responsável pelo projeto, que cuida delas; o comitê não precisa respondê-las.
