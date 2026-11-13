# Revisão de terminologia — instruções para o comitê

Este documento explica como revisar os termos da interface em português (pt-BR) e em espanhol
(es-ES) usando uma planilha. A revisão é a pergunta Q14 do plano do projeto. Enquanto ela não for
feita, as traduções são **rascunhos** (marcadas como `unfinished` nos catálogos) e o texto em
inglês é a referência de significado.

Quem prepara a planilha e aplica o resultado é a pessoa responsável pelo repositório; o comitê só
precisa preencher o arquivo CSV e devolvê-lo.

## 1. Abrir o arquivo no Excel ou no LibreOffice

O arquivo é um CSV em **UTF-8**, com **ponto e vírgula (`;`)** como separador. Abri-lo com um
duplo clique costuma funcionar no Excel em português, mas o caminho seguro é importar:

**Excel**

1. Abra o Excel e uma pasta de trabalho em branco.
2. Menu **Dados** → **De Texto/CSV** e escolha o arquivo.
3. Em **Origem do arquivo**, escolha **65001: Unicode (UTF-8)**; em **Delimitador**, escolha
   **Ponto e vírgula**.
4. Clique em **Carregar**.

**LibreOffice Calc**

1. **Arquivo** → **Abrir** e escolha o arquivo.
2. Na janela de importação, **Conjunto de caracteres: Unicode (UTF-8)**, **Separado por:
   Ponto e vírgula** (desmarque Vírgula e Tabulação), e deixe **Aspas** como delimitador de texto.
3. Clique em **OK**.

Confira se os acentos aparecem corretamente (por exemplo, "Prontidão"). Se aparecerem símbolos
estranhos, a codificação escolhida não foi UTF-8.

## 2. Salvar de volta

- **Excel:** **Arquivo** → **Salvar como** → tipo **CSV UTF-8 (delimitado por vírgulas) (\*.csv)**.
  Apesar do nome, o Excel em português grava com ponto e vírgula. O Excel avisa que só a planilha
  ativa será salva; aceite.
- **LibreOffice:** **Arquivo** → **Salvar como** → tipo **Texto CSV (.csv)**, marque **Editar
  configurações de filtro**, e escolha **Unicode (UTF-8)**, separador **;** e **Citar todas as
  células de texto** ligado.

Não use o tipo "CSV (separado por vírgulas)" simples do Excel: ele grava em outra codificação e
estraga os acentos. Salve com um **novo nome** (por exemplo, `terminologia-revisada.csv`) para
manter o original.

## 3. O que cada coluna significa

| Coluna | Para que serve | Pode editar? |
| --- | --- | --- |
| `id` | Chave estável da mensagem. É ela que liga a linha ao catálogo. | **Não** |
| `area` | Parte do programa (por exemplo, `personnel`, `budget`, `reports`). | **Não** |
| `context` | Grupo de textos dentro da área. | **Não** |
| `english` | Texto original em inglês. | **Não** |
| `comment` | Comentário de desambiguação: diferencia dois textos iguais usados em lugares diferentes. | **Não** |
| `note` | Nota para quem traduz: explica onde e como o texto aparece. Leia antes de revisar. | **Não** |
| `estado` | `pendente` = a tradução ainda é rascunho; `revisado` = já foi revisada. | **Não** |
| `pt_BR_atual` | Tradução atual para português do Brasil. | **Não** |
| `es_ES_atual` | Tradução atual para espanhol (Espanha). | **Não** |
| `pt_BR_revisado` | **Sua versão** em português. | **Sim** |
| `es_ES_revisado` | **Sua versão** em espanhol. | **Sim** |
| `observacoes` | Dúvidas, justificativas, alternativas. Não é aplicada ao programa. | **Sim** |

Como preencher `pt_BR_revisado` e `es_ES_revisado`:

- **Célula vazia = "não revisei" (ou "sem opinião") — a tradução atual não muda.**
- **Célula preenchida = "esta é a versão revisada".** Se você concorda com a tradução atual,
  **copie-a** para a coluna `_revisado`: é assim que ela é marcada como revisada.
- Se só dominar um dos idiomas, preencha apenas a coluna dele.

## 4. Regras

1. **Não altere** as colunas `id`, `area`, `context`, `english`, `comment`. Linhas com essas
   colunas alteradas são ignoradas na importação. Não apague nem reordene colunas; mudar a ordem
   das linhas não tem problema.
2. **Mantenha os marcadores de posição** `%1`, `%2`, `%L1`, `%n`, exatamente como no texto em
   inglês. Eles são substituídos por nomes, números e datas pelo programa. Pode mudar a posição
   deles na frase, mas não pode apagar, trocar nem inventar um. Linhas com marcadores diferentes
   do original são recusadas e listadas no relatório de importação.
3. **Mantenha o `&`** que aparece antes de uma letra (por exemplo, `&Arquivo`): ele define a tecla
   de atalho do menu. Use uma letra que ainda não seja usada por outro item do mesmo menu. Para
   mostrar um `&` de verdade, o texto usa `&&`.
4. **Mensagens no plural** têm duas formas separadas por ` | ` (espaço, barra vertical, espaço):
   **singular | plural**. Exemplo: `%n dia | %n dias`. Mantenha sempre duas formas e o mesmo
   formato. A forma do singular pode dizer "um dia" em vez de `%n dia`; a do plural deve
   manter o `%n`.
5. **Não use fórmulas** nem formatação de número ou data: as células são texto. Se o Excel
   transformar algo em data ou número, desfaça (Ctrl+Z) e formate a coluna como **Texto**.
6. **Termos novos** devem ser escritos do zero, com o vocabulário do próprio comitê. Não cole
   trechos de documentos internos ou de material de treinamento nas células nem nas
   observações: as traduções entram no código-fonte do programa.
7. **Seja consistente**: o mesmo termo em inglês deve ter a mesma tradução em toda a planilha.
   Use um filtro na coluna `english` para ver todos os usos.

## 5. Termos para revisar primeiro

São os termos que mais aparecem e que mais dependem do vocabulário da instituição. Use o filtro
(ou a busca) nas colunas `english`, `pt_BR_atual` e `es_ES_atual`.

- **Prontidão** (*readiness*): o conceito central do painel. Confirme o equivalente em espanhol
  (por exemplo, "preparación" ou "alistamiento") e se o inglês "readiness" está bem representado.
- **EPI / EPP, níveis A, B e C** (equipamento de proteção individual; em espanhol, EPP): confirme
  a sigla em cada idioma e os nomes dos três níveis de proteção.
- **Habilitação prática** (*practical qualification*): confirme se é esse o termo usado pela
  instituição e o equivalente em espanhol (hoje "habilitación práctica") e em inglês.
- **Baia** (*bay*, um dos tipos de instalação do módulo de infraestrutura): confirme o termo em
  português e escolha o equivalente em espanhol e em inglês.
- **Reciclagem** (*recycling*): confirme o termo em português e escolha o equivalente em
  espanhol e em inglês.
- **Instantâneo / registro** (*snapshot*: o registro dos valores dos indicadores numa data, que
  é guardado para comparação): decida qual palavra usar, de forma única, para não haver
  "instantâneo" numa tela e "registro" em outra.
- **Comando da Aeronáutica** e outros nomes de órgãos e de postos: confirme a grafia oficial e
  como ficam em espanhol e em inglês.

Depois desses, revise as linhas com `estado` = `pendente` por área, começando pelas telas mais
usadas (`shell`, `dashboard`, `personnel`, `infrastructure`, `exercises`, `budget`).

## 6. Como devolver

1. Salve a planilha como CSV UTF-8, com ponto e vírgula, com um novo nome (seção 2).
2. Envie o arquivo à pessoa responsável pelo repositório pelo canal combinado pelo comitê.
   **Não anexe o arquivo a mensagens públicas nem o publique em páginas abertas** sem antes
   verificar que ele não contém informação sensível.
3. A pessoa responsável executa a importação e envia de volta o relatório: quantas linhas foram
   aplicadas e quais foram recusadas (com o `id` e o motivo, por exemplo "marcadores diferentes
   do original"). Corrija as linhas recusadas na planilha e devolva-a de novo; linhas já
   aplicadas não são prejudicadas se forem enviadas outra vez.

Para quem executa a importação (na raiz do repositório):

```text
python scripts/terminology_sheet.py export --out terminologia.csv
python scripts/terminology_sheet.py import --csv terminologia-revisada.csv --mark-finished
python scripts/i18n.py update
```

O primeiro comando gera a planilha para o comitê. O segundo grava as versões revisadas nos
catálogos e, com `--mark-finished`, retira a marca de rascunho (`unfinished`) das traduções
revisadas; sem essa opção, apenas o texto é atualizado. O terceiro atualiza os catálogos como de
costume. Depois, registre no `CHANGELOG.md` quantas mensagens continuam pendentes (Q14).
