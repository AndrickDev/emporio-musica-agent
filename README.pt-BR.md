# Empório da Música — Agente de Atendimento

*English version: [README.md](README.md)*

Case técnico para a vaga de AI Engineer na Artefact.

Agente de atendimento por mensagem de texto para a Empório da Música, loja fictícia de instrumentos
musicais em Campo Grande/MS. O agente conversa em português brasileiro, no tom da loja ("informal, mas
profissional"). Ele consulta catálogo, pedidos, promoções e formas de pagamento antes de afirmar
qualquer fato, e aplica o manual de políticas a dúvidas sobre troca, devolução, frete, pagamento,
garantia e horário.

> **TODO(autor) — remover antes de entregar:** gerar as conversas de exemplo, preencher a seção "Uso
> de assistentes de IA" com o seu workflow e confirmar a interpretação do idioma.

## Como funciona

```
mensagem do cliente
      │
      ▼
 Loop do agente (src/agent.py) ──── chat completions compatível com OpenAI (Gemini grátis por padrão)
      ▲                                  │ function calling
      │ resultados (JSON)                ▼
      └──────────────────────── ferramentas (src/tools.py)
                                  ├─ catálogo / promoções ── SQLite em memória criado de data/*.csv
                                  ├─ formas de pagamento ─── regras §3 / §6.2 em código (src/pricing.py)
                                  ├─ status de pedido ────── exige nº do pedido ou rastreio + e-mail ou telefone
                                  ├─ políticas ───────────── busca por palavras-chave no manual
                                  ├─ dados da loja ───────── endereço, contatos, horário
                                  └─ registro de atendimento ─ repasse para a equipe (arquivo JSONL local)
```

O prompt de sistema define persona e regras, mas **não contém fatos da loja** (preços, telefones,
horários): todo fato chega ao modelo pelo resultado de uma ferramenta. A data e a hora de Campo Grande
são inseridas a cada mensagem, para o agente saber se a loja está aberta e calcular prazos de devolução.

| Ferramenta | Pergunta típica |
|---|---|
| `search_products` | "Quais violões até R$1000?" — ignora acento e hífen, filtra pelo preço que o cliente paga, avisa quando a lista foi cortada |
| `get_product_details` | "Quanto custa o Takamine GD20?" — aceita variações do modelo, pergunta quando é ambíguo, sugere alternativas quando indisponível |
| `list_active_promotions` | "Tem promoção?" — só existem para o agente as promoções com `is_active = 1` |
| `get_payment_options` | "Dá pra parcelar? E no PIX?" — desconto do PIX, faixas de parcelamento, pagamento combinado |
| `get_order_status` | "Cadê meu pedido?" — verificação de identidade, sem dados pessoais no resultado |
| `get_store_policy` | devolução, garantia, frete, regras de pagamento |
| `get_store_info` | endereço, telefone, WhatsApp, e-mail, horário |
| `create_support_ticket` | reclamação, pedido de troca/devolução, atendimento humano |

## Instalação

Requer Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # coloque sua chave em LLM_API_KEY — o .env está no .gitignore
```

A única dependência é o cliente `openai` (mais `tzdata` no Windows). Qualquer endpoint compatível com
OpenAI funciona. O padrão é o plano gratuito do Gemini: crie a chave em
https://aistudio.google.com/app/apikey (sem cobrança). As cotas gratuitas são por modelo e por dia; veja
em https://aistudio.google.com/rate-limit. No plano gratuito, o Google pode usar prompts e respostas para
melhorar seus produtos, por isso só o dataset anonimizado deve ser enviado. O `.env.example` traz também
uma configuração do plano gratuito do Groq.

## Execução

```bash
python main.py                  # nova conversa
python main.py --session ana    # sessão nomeada, histórico em .sessions/ (fora do git)
python main.py --debug          # mostra também o resultado de cada ferramenta
```

No chat: `/sair` encerra, `/limpar` reinicia a conversa.

## Testes e conversas de exemplo

```bash
python tests/test_tools.py      # 30 verificações da camada de ferramentas (sem LLM, sem rede)
python tests/test_agent.py      # 7 verificações do loop do agente com cliente OpenAI simulado
python -m pytest tests/         # os mesmos 37 testes, se tiver pytest
python scripts/generate_examples.py --translate   # roda 5 cenários com o modelo real
```

Os testes cobrem busca (acentos, hífen, preço promocional, corte da lista, ambiguidade, disponibilidade),
promoções, regras de pagamento, privacidade de pedidos (verificação, sem dados pessoais, mesma mensagem
de falha, bloqueio, impossibilidade de varrer pedidos), busca nas políticas e o loop do agente (execução
de ferramentas, limite de rodadas, erro do provedor, data no prompt, sessões). Eles **não** medem a
qualidade das respostas de um modelo real; isso aparece nas conversas de exemplo.

`examples/` guarda as conversas geradas por `scripts/generate_examples.py`. Cada arquivo informa o
modelo, a hora da geração e a data da loja usada (fixada em 23/03/2026, o dia seguinte ao último pedido
do dataset, para as datas dos pedidos fazerem sentido). As respostas do agente não são editadas. A
tradução para o inglês, opcional, é feita pelo mesmo modelo e marcada como tradução automática.

## Decisões técnicas

**Abordagem: function calling com poucas ferramentas.** Os dados da loja são estruturados e as perguntas
se resumem a poucas operações. Com function calling, toda resposta factual vem de uma consulta, e dá para
ver as decisões do agente (cada resposta lista as ferramentas usadas). Um framework ReAct ou vários
agentes acrescentariam complexidade sem mudar o resultado neste escopo. Descartei um agente de SQL: aqui o
modelo só preenche parâmetros de consultas fixas e parametrizadas, nunca escreve SQL, o que evita vazar
dados de clientes ou fazer joins errados.

**Regras de negócio em código, não no prompt.** Preço promocional, desconto do PIX (que não se soma à
promoção, §6.2), faixas de parcelamento (§3.1), estados de disponibilidade e verificação de pedido são
Python simples, com testes. O próprio manual avisa que preço errado pode configurar propaganda enganosa,
e LLMs erram contas.

**Dados: SQLite em memória a partir dos CSVs.** O SQLite vem com o Python: sem serviço e sem dependência
extra. O banco é recriado a cada início, então os CSVs continuam sendo a única fonte da verdade. A visão
`catalog` junta cada produto com sua promoção ativa e preço atual, e todas as ferramentas de produto
usam a mesma regra de preço. Duas funções SQL (`norm`, `compact`) fazem a busca ignorar acento e hífen,
porque o `LOWER()` do SQLite só trata ASCII.

**Políticas: busca por palavras e radicais, sem banco vetorial.** O manual tem 8 páginas, divididas em
trechos do tamanho de uma seção. Um pontuador sem acento e com casamento por prefixo
(devolver/devolução, arrepender/arrependimento) trouxe a seção certa nas perguntas testadas, sem custo e
sem dependência. Se a base de documentos crescer, esse módulo pode ser trocado por embeddings ou busca
híbrida sem mexer no resto do agente.

**Modelo e provedor: configurável, com o Gemini gratuito como padrão.** O agente usa o protocolo de chat
completions da OpenAI, então trocar de provedor é mudar três variáveis de ambiente. Assim o projeto roda
de graça. *TODO(autor): dizer qual modelo foi usado para gerar os exemplos e por quê.*

**Interface: CLI**, com sessões nomeadas opcionais salvas em JSON numa pasta fora do git.

**Idioma.** O README principal está em inglês, como pede o processo seletivo, com esta versão em
português ao lado. Os nomes no código estão em inglês; os comentários e as mensagens de commit mais
recentes estão em português, idioma de trabalho do autor. O agente conversa em português porque
atende os clientes da loja e porque as perguntas de exemplo do próprio case estão em português; cada
conversa de exemplo traz tradução para o inglês. Responder em inglês seria uma mudança de uma linha no
prompt.

**Privacidade (LGPD, manual §9).** A consulta de pedido exige o número do pedido ou o código de rastreio
**e** o e-mail ou telefone usado na compra. Uma falha devolve a mesma mensagem exista o pedido ou não
(não dá para varrer números de pedido), e depois de 3 falhas a consulta fica bloqueada na conversa. A
ferramenta nunca devolve nome, e-mail, telefone, cidade ou id interno do cliente. O registro de
atendimento só referencia pedido verificado na mesma conversa e não guarda contatos. O CSV de clientes
deste repositório está anonimizado (`Cliente NNN`, `clienteNNN@example.com`).

## Suposições

| Tema | Ambiguidade | Decisão |
|---|---|---|
| Idioma | O enunciado está em português; o e-mail do processo pede inglês | README em inglês (com versão em português); agente em português; exemplos traduzidos |
| Parcelamento (§3 / §3.1) | "até 3x: sem valor mínimo (exceto abaixo de R$ 50,00)" | 2–3x exigem parcela ≥ R$ 50; 4–6x ≥ R$ 80; 7–12x ≥ R$ 100 |
| Limites | "acima de R$ 2.000" | Estritamente maior |
| Contatos | §1.2 traz (67) 3341-4444 como telefone/WhatsApp; §7 traz (67) 3321-4500 como canal de WhatsApp | Telefone da §1.2, WhatsApp da §7 |
| E-mail | Escrito com e sem acento no manual | Versão sem acento, da capa |
| Promoções | O manual cita Black Friday em novembro; nenhuma promoção de Black Friday está ativa nos dados | Só valem as promoções ativas nos dados (§7.3) |
| Devolução | O arrependimento vale para compra online e conta do recebimento; os dados não têm o canal nem a data real de entrega | O agente explica a regra com a data estimada, declara a suposição e registra o caso, sem aprovar nem recusar |
| Data da loja | Os pedidos vão até março/2026 | Data real por padrão; `STORE_TODAY` fixa a data (exemplos usam 23/03/2026) |

## Problemas encontrados nos dados

- Os produtos 135, 137, 139, 140, 142 e 144 têm descrições que citam outra marca ou modelo (ex.: *Music
  Man Bass 1X* descrito como Fender Jazz Bass). Isso é detectado automaticamente: a descrição é omitida e
  só nome, preço e especificações são usados.
- O produto 136 está `discontinued`, mas tem 13 unidades em estoque, então não é oferecido. O 130 está
  `coming_soon` com 2 unidades, então ainda não está à venda (os pedidos 3 e 14 o contêm).
- As categorias 6, 7 e 8 (sopros e cordas orquestrais) não têm produtos.
- Os totais dos pedidos 3 e 20 não batem com os preços dos itens; o total registrado é informado como está.

## Limitações conhecidas e próximos passos

- A verificação é "algo que você sabe" (e-mail ou telefone). Em produção, a autenticação viria do próprio
  canal (o número de WhatsApp do cliente) ou de um código de uso único, com limite de tentativas por
  usuário, não por conversa.
- A busca por palavras pode não achar paráfrases muito distantes do texto do manual.
- Os CSVs são uma foto estática; o registro de atendimento vai para um arquivo local, não para um CRM.
- Feriados não são considerados ao dizer se a loja está aberta.
- Frete fora de Campo Grande depende de CEP e peso e não está nos dados.
- O histórico cresce durante a sessão; um passo de resumo limitaria o uso de tokens.
- Com mais tempo: conjunto de avaliação automática (pergunta → ferramenta esperada e conteúdo proibido),
  interface WhatsApp ou web, observabilidade de chamadas, custo e latência.

## Uso de assistentes de IA

Este projeto foi feito com dois assistentes de programação com IA, a meu pedido:

- **Instinct** gerou a primeira versão: estrutura do projeto, acesso a dados, ferramentas, loop do
  agente, CLI, gerador de exemplos, as primeiras conversas de exemplo e o README, além dos 15 primeiros
  commits (autor `AI coding assistant`). Esse histórico foi reescrito antes da publicação (os dados de
  clientes aparecem anonimizados em todos os commits); por isso vários desses commits têm o mesmo
  horário de autoria.
- **Claude (Anthropic)** depois revisou essa versão contra o enunciado e fez as mudanças dos commits com
  autor `Claude (assistente de IA, Anthropic)`: verificação de identidade nos pedidos e remoção de dados
  pessoais dos resultados, busca sem acento e hífen, preço promocional na busca, aviso de lista cortada e
  de nome ambíguo, as ferramentas de pagamento e de registro de atendimento, a data atual no prompt, as
  checagens de qualidade dos dados, os testes ampliados (37, executados naquela sessão), os roteiros de
  exemplo corrigidos e este README bilíngue. O Claude não rodou o agente com um modelo real.

*TODO(autor): descreva a sua parte com as suas palavras — o que você leu e entendeu, o que rodou (testes,
CLI, geração de exemplos, com qual modelo), o que decidiu, o que mudou você mesmo e em quais commits.*

## Estrutura do projeto

```
data/                    dataset do case (CSVs, clientes anonimizados) + manual de políticas (PDF e texto)
src/config.py            provedor, modelo e data da loja via variáveis de ambiente
src/database.py          CSV -> SQLite em memória, visão catalog, funções SQL sem acento
src/pricing.py           regras de pagamento do manual
src/policies.py          divisão e busca no manual de políticas
src/tools.py             esquemas e implementação das ferramentas
src/agent.py             loop do LLM, prompt de sistema, sessões
main.py                  CLI
scripts/generate_examples.py   roda os cenários de exemplo com o modelo real
scripts/sanitize_customers.py  como os dados de clientes foram anonimizados
tests/                   testes das ferramentas e do loop do agente
examples/                conversas com o agente
```
