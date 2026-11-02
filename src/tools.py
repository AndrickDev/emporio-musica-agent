"""Ferramentas que o agente pode chamar (formato de function calling da OpenAI).

Toda resposta sobre preço, estoque, pedido, promoção, pagamento, política ou
dados da loja precisa vir de uma destas ferramentas; o LLM não responde de
memória. Isso segue a regra do próprio manual (§7.1): nunca informar preço,
estoque ou prazo sem consultar o sistema.

Princípios:
- As regras de negócio ficam em código (preço promocional, PIX, parcelas,
  disponibilidade), não no LLM.
- Erros voltam como dados ({"found": False, ...}) para o modelo poder explicar
  ao cliente, em vez de quebrar a conversa.
- Pedidos são protegidos (LGPD, manual §9): só são mostrados com número do
  pedido (ou código de rastreio) + e-mail ou telefone do cadastro. A falha tem
  sempre a mesma mensagem (não revela se o pedido existe) e, depois de
  MAX_FAILED_VERIFICATIONS falhas, a consulta fica bloqueada na conversa.
  Nome, e-mail, telefone, cidade e customer_id NUNCA saem da ferramenta.
"""
import json
import re
import uuid
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

from . import config
from .database import compact, load_db, norm
from .policies import search_policies
from .pricing import payment_options

_DB = load_db()

MAX_RESULTS = 10
MAX_FAILED_VERIFICATIONS = 3
TICKETS_FILE = Path(__file__).resolve().parent.parent / "runtime" / "tickets.jsonl"

# Marcas presentes no catálogo. Usadas só para detectar descrições que citam
# outra marca (ex.: "Music Man Bass 1X" descrito como "Fender Jazz Bass").
KNOWN_BRANDS = (
    "yamaha", "tagima", "giannini", "rozini", "shelby", "crafter", "martin", "taylor",
    "takamine", "kala", "ohana", "kalani", "fender", "gibson", "ibanez", "prs",
    "music man", "pearl", "tama", "roland", "korg", "nord",
)

ORDER_STATUS_MEANING = {
    "pending": "Pedido recebido; pagamento ainda não confirmado.",
    "confirmed": "Pagamento confirmado; pedido em preparação, ainda não foi despachado.",
    "shipped": "Pedido despachado, em trânsito.",
    "delivered": "Pedido entregue.",
    "cancelled": "Pedido cancelado.",
}

VERIFICATION_FAILED = (
    "Não foi possível verificar um pedido com esses dados. Peça ao cliente para "
    "conferir o número do pedido (ou código de rastreio) e o e-mail ou telefone "
    "usados na compra."
)

CATEGORY_NAMES = [r["name"] for r in _DB.execute("SELECT name FROM categories")]


# --------------------------------------------------------------------- schemas
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Busca no catálogo de instrumentos por texto, categoria e/ou faixa de preço. "
                "Use para perguntas sobre produtos, preços ou disponibilidade. Os preços já "
                "consideram promoções ativas. Informe ao cliente se a lista foi cortada (truncated)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Palavras que devem aparecer no nome/descrição, ex.: 'nylon', 'Takamine', '7 cordas'.",
                    },
                    "category": {"type": "string", "enum": CATEGORY_NAMES},
                    "min_price": {"type": "number", "description": "Preço atual mínimo em R$."},
                    "max_price": {"type": "number", "description": "Preço atual máximo em R$."},
                    "in_stock_only": {
                        "type": "boolean",
                        "description": "Se true, só produtos com estoque. Padrão: true.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_details",
            "description": (
                "Detalhes de um produto: preço (com promoção ativa, se houver), disponibilidade, "
                "especificações e alternativas quando indisponível. Se o nome for ambíguo, "
                "devolve candidatos para você perguntar ao cliente qual é."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer", "description": "Id exato, se conhecido."},
                    "product_name": {"type": "string", "description": "Nome ou modelo, ex.: 'Takamine GD20'."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_active_promotions",
            "description": "Promoções ativas agora, com preço original, percentual e preço promocional. Qualquer outra campanha NÃO está ativa.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_payment_options",
            "description": (
                "Calcula valor no PIX, débito, boleto e máximo de parcelas sem juros no cartão para "
                "um produto (preferível) ou um valor, aplicando as regras do manual. Use sempre que "
                "falar de forma de pagamento, desconto no PIX ou parcelamento."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer"},
                    "amount_brl": {"type": "number", "description": "Valor em R$ (se não for um produto só)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": (
                "Consulta um pedido. EXIGE o número do pedido ou o código de rastreio E o e-mail "
                "ou telefone usado na compra, ambos informados pelo cliente nesta conversa. "
                "Se faltar algum, peça ao cliente antes de chamar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer", "description": "Número do pedido."},
                    "tracking_code": {"type": "string", "description": "Código de rastreio, formato BRxxxxxxxxxBR."},
                    "customer_email": {"type": "string", "description": "E-mail usado na compra."},
                    "customer_phone": {"type": "string", "description": "Telefone usado na compra."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_store_policy",
            "description": (
                "Consulta o manual de políticas da loja (troca, devolução, frete, pagamento, "
                "garantia, horários, regras de atendimento). Use sempre que a resposta depender "
                "de uma regra da loja. Escreva a pergunta em português."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "O que procurar no manual."},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_store_info",
            "description": "Dados gerais da loja: endereço, telefone, WhatsApp, e-mail e horário de funcionamento.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_support_ticket",
            "description": (
                "Registra um atendimento para a equipe humana: reclamação, pedido de troca/devolução, "
                "garantia, ou quando o cliente pede um atendente ou a dúvida não está nos dados nem no "
                "manual. Não coloque e-mail nem telefone no resumo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_type": {
                        "type": "string",
                        "enum": ["reclamacao", "troca_ou_devolucao", "garantia", "atendimento_humano", "outro"],
                    },
                    "summary": {"type": "string", "description": "Resumo do caso, sem dados pessoais."},
                    "order_id": {"type": "integer", "description": "Só se o pedido já foi verificado nesta conversa."},
                },
                "required": ["ticket_type", "summary"],
            },
        },
    },
]


# ------------------------------------------------------------- funções de apoio
def _brands_in(text: str) -> set:
    padded = f" {norm(text)} "
    return {b for b in KNOWN_BRANDS if re.search(rf"[\s,.(]{re.escape(b)}[\s,.)]", padded)}


def description_conflicts(name: str, description: str) -> bool:
    """True se a descrição cita uma marca diferente da marca do nome."""
    name_brands, desc_brands = _brands_in(name), _brands_in(description or "")
    return bool(name_brands) and bool(desc_brands - name_brands)


def availability(status: str, stock: int) -> str:
    """Estado de venda derivado de status + estoque (status vence o estoque)."""
    if status == "discontinued":
        return "descontinuado"
    if status == "coming_soon":
        return "em_breve"
    return "em_estoque" if stock > 0 else "sem_estoque"


def _summary(row) -> dict:
    """Resumo de um produto vindo da visão catalog."""
    on_promo = row["discount_percent"] is not None
    return {
        "product_id": row["product_id"],
        "name": row["name"],
        "category": row["category"],
        "price_brl": row["current_price"],
        "original_price_brl": row["list_price"] if on_promo else None,
        "discount_percent": row["discount_percent"],
        "promotion": row["promo_name"],
        "availability": availability(row["status"], row["stock_quantity"]),
        "stock_quantity": row["stock_quantity"],
    }


def _phone_matches(given: str, stored: str) -> bool:
    """Aceita '(67) 90000-0001', '67900000001', '+55 67 90000-0001' ou só '90000-0001'."""
    g, s = re.sub(r"\D", "", given or ""), re.sub(r"\D", "", stored or "")
    if g.startswith("55") and len(g) == 13:
        g = g[2:]
    return len(g) >= 8 and (g == s or (len(g) == 9 and s.endswith(g)))


def today() -> date:
    """Data de hoje na loja (pode ser fixada com STORE_TODAY para demonstrações)."""
    return config.store_now().date()


# ------------------------------------------------------------------ ferramentas
class StoreTools:
    """Ferramentas de uma conversa. Guarda o estado da verificação de pedidos,
    para que o bloqueio por tentativas valha por conversa."""

    def __init__(self, tickets_file: Path = TICKETS_FILE):
        self.failed_verifications = 0
        self.verified_orders: set = set()
        self.tickets_file = tickets_file
        self._functions = {
            "search_products": self.search_products,
            "get_product_details": self.get_product_details,
            "list_active_promotions": self.list_active_promotions,
            "get_payment_options": self.get_payment_options,
            "get_order_status": self.get_order_status,
            "get_store_policy": self.get_store_policy,
            "get_store_info": self.get_store_info,
            "create_support_ticket": self.create_support_ticket,
        }

    def call(self, name: str, arguments: dict) -> str:
        fn = self._functions.get(name)
        if fn is None:
            return json.dumps({"error": f"Ferramenta desconhecida: {name}"}, ensure_ascii=False)
        try:
            result = fn(**(arguments or {}))
        except Exception as exc:  # devolve a falha ao modelo em vez de derrubar a conversa
            result = {"error": f"{type(exc).__name__}: {exc}"}
        return json.dumps(result, ensure_ascii=False)

    # ---- catálogo
    def search_products(self, query=None, category=None, min_price=None, max_price=None,
                        in_stock_only=True):
        sql = "SELECT * FROM catalog WHERE status = 'active'"
        params: list = []
        if query:
            for word in str(query).split():
                if len(compact(word)) < 2:
                    continue
                # Casa com ou sem acento, e com ou sem hífen/espaço em códigos de modelo.
                sql += (" AND (norm(name || ' ' || category || ' ' || description) LIKE ?"
                        " OR compact(name) LIKE ?)")
                params += [f"%{norm(word)}%", f"%{compact(word)}%"]
        if category:
            if norm(category) not in {norm(c) for c in CATEGORY_NAMES}:
                # Falha explícita: lista vazia seria lida como "não temos".
                return {"error": f"Categoria desconhecida: {category}", "valid_categories": CATEGORY_NAMES}
            sql += " AND norm(category) = ?"
            params.append(norm(category))
        if min_price is not None:
            sql += " AND current_price >= ?"
            params.append(float(min_price))
        if max_price is not None:
            sql += " AND current_price <= ?"  # filtra pelo preço que o cliente paga
            params.append(float(max_price))
        if in_stock_only:
            sql += " AND stock_quantity > 0"
        sql += " ORDER BY current_price"
        rows = _DB.execute(sql, params).fetchall()
        return {
            "total_found": len(rows),
            "truncated": len(rows) > MAX_RESULTS,
            "products": [_summary(r) for r in rows[:MAX_RESULTS]],
            "note": (f"Mostrando os {MAX_RESULTS} mais baratos de {len(rows)}; refine a busca para ver os demais."
                     if len(rows) > MAX_RESULTS else None),
        }

    def _find_by_name(self, product_name: str):
        """Retorna (produto único, candidatos ambíguos)."""
        words = [compact(w) for w in str(product_name).split() if compact(w)]
        rows = _DB.execute("SELECT * FROM catalog").fetchall()
        matches = [r for r in rows if all(w in compact(r["name"]) for w in words)]
        if len(matches) == 1:
            return matches[0], []
        if len(matches) > 1:
            return None, matches
        # Nenhum nome contém todas as palavras: tenta semelhança (erros de digitação).
        target = norm(product_name)
        best = max(rows, key=lambda r: SequenceMatcher(None, target, norm(r["name"])).ratio())
        if SequenceMatcher(None, target, norm(best["name"])).ratio() >= 0.6:
            return best, []
        return None, []

    def get_product_details(self, product_id=None, product_name=None):
        row, candidates = None, []
        if product_id is not None:
            row = _DB.execute("SELECT * FROM catalog WHERE product_id = ?", (int(product_id),)).fetchone()
        elif product_name:
            row, candidates = self._find_by_name(product_name)
        if candidates:
            return {
                "found": False,
                "ambiguous": True,
                "message": f"{len(candidates)} produtos correspondem a '{product_name}'. Pergunte ao cliente qual deles.",
                "candidates": [_summary(r) for r in candidates[:MAX_RESULTS]],
            }
        if row is None:
            return {"found": False, "message": "Produto não encontrado no catálogo."}

        product = _summary(row)
        try:
            product["specs"] = json.loads(row["specs"] or "{}")
        except json.JSONDecodeError:
            product["specs"] = {}
        if description_conflicts(row["name"], row["description"]):
            product["description"] = None
            product["data_note"] = ("Descrição omitida: o texto cadastrado cita outra marca/modelo e "
                                    "contradiz o nome. Use só nome, preço e especificações.")
        else:
            product["description"] = row["description"]
        if product["availability"] != "em_estoque":
            alts = _DB.execute(
                "SELECT * FROM catalog WHERE category_id = ? AND status = 'active' AND stock_quantity > 0 "
                "ORDER BY ABS(current_price - ?) LIMIT 3",
                (row["category_id"], row["current_price"]),
            ).fetchall()
            product["similar_available"] = [_summary(a) for a in alts]
        return {"found": True, "product": product}

    def list_active_promotions(self):
        rows = _DB.execute(
            "SELECT * FROM catalog WHERE discount_percent IS NOT NULL AND status = 'active' "
            "ORDER BY discount_percent DESC"
        ).fetchall()
        return {
            "count": len(rows),
            "promotions": [_summary(r) for r in rows],
            "note": "Só estas promoções estão ativas. Qualquer outra campanha (ex.: Black Friday) não está ativa no sistema.",
        }

    def get_payment_options(self, product_id=None, amount_brl=None):
        if product_id is not None:
            row = _DB.execute("SELECT * FROM catalog WHERE product_id = ?", (int(product_id),)).fetchone()
            if row is None:
                return {"error": "Produto não encontrado."}
            on_promo = row["discount_percent"] is not None
            result = payment_options(row["list_price"], row["current_price"] if on_promo else None)
            result["product"] = _summary(row)
            return result
        if amount_brl is not None:
            result = payment_options(float(amount_brl))
            result["note"] = ("Calculado para um valor avulso, considerado preço de tabela. Se algum item "
                              "estiver em promoção, o desconto do PIX não se aplica a ele.")
            return result
        return {"error": "Informe product_id ou amount_brl."}

    # ---- pedidos
    def get_order_status(self, order_id=None, tracking_code=None, customer_email=None, customer_phone=None):
        if self.failed_verifications >= MAX_FAILED_VERIFICATIONS:
            return {"found": False, "message": "Consulta de pedidos bloqueada nesta conversa após várias "
                    "tentativas sem sucesso. Encaminhe o cliente ao atendimento humano."}
        if order_id is None and not tracking_code:
            return {"found": False, "message": "Peça o número do pedido ou o código de rastreio."}
        if not (customer_email or customer_phone):
            return {"found": False, "message": "Para proteger os dados do cliente, peça também o e-mail "
                    "ou telefone usado na compra."}

        sql = ("SELECT o.*, c.email AS _email, c.phone AS _phone FROM orders o "
               "JOIN customers c ON c.customer_id = o.customer_id WHERE ")
        if order_id is not None:
            sql, params = sql + "o.order_id = ?", (str(order_id),)
        else:
            sql, params = sql + "UPPER(o.tracking_code) = ?", (str(tracking_code).strip().upper(),)
        row = _DB.execute(sql, params).fetchone()

        verified = row is not None and bool(
            (customer_email and norm(customer_email).strip() == norm(row["_email"]))
            or (customer_phone and _phone_matches(customer_phone, row["_phone"]))
        )
        if not verified:
            # Mesma mensagem exista o pedido ou não: não dá para "descobrir" pedidos.
            self.failed_verifications += 1
            return {"found": False, "message": VERIFICATION_FAILED,
                    "attempts_left": MAX_FAILED_VERIFICATIONS - self.failed_verifications}

        self.verified_orders.add(int(row["order_id"]))
        items = [dict(r) for r in _DB.execute(
            "SELECT p.name, CAST(oi.quantity AS INTEGER) AS quantity FROM order_items oi "
            "JOIN products p ON p.product_id = oi.product_id WHERE oi.order_id = ?",
            (row["order_id"],),
        )]
        now = today()
        order_date = date.fromisoformat(row["order_date"])
        estimated = date.fromisoformat(row["estimated_delivery"]) if row["estimated_delivery"] else None
        # Só campos do pedido: nada de nome, e-mail, telefone, cidade ou customer_id.
        return {
            "found": True,
            "order": {
                "order_id": int(row["order_id"]),
                "status": row["status"],
                "status_meaning": ORDER_STATUS_MEANING.get(row["status"], row["status"]),
                "order_date": row["order_date"],
                "items": items,
                "total_brl": float(row["total_brl"]),
                "payment_method": row["payment_method"],
                "tracking_code": row["tracking_code"] or None,
                "estimated_delivery": row["estimated_delivery"] or None,
                "notes": row["notes"] or None,
                "today": now.isoformat(),
                "days_since_order": (now - order_date).days,
                "days_since_estimated_delivery": (now - estimated).days if estimated else None,
                "data_limitations": ("O sistema guarda a data ESTIMADA de entrega, não a data real, e não "
                                     "registra se a compra foi online ou na loja física."),
            },
        }

    # ---- políticas e dados da loja
    def get_store_policy(self, question):
        excerpts = search_policies(question or "", top_k=3)
        if not excerpts:
            return {"found": False, "message": "Nenhum trecho do manual corresponde à pergunta. Não invente; "
                    "ofereça encaminhar à equipe."}
        return {"found": True, "excerpts": excerpts}

    def get_store_info(self):
        # Dados copiados do manual (§1.2, §2 e §7). O manual traz dois números:
        # (67) 3341-4444 como telefone/WhatsApp na §1.2 e (67) 3321-4500 como canal
        # de WhatsApp na §7. Usamos a §7 para WhatsApp e a §1.2 para telefone
        # (suposição documentada no README).
        return {
            "store": "Empório da Música",
            "tagline": "Sua música começa aqui.",
            "address": "Rua 14 de Maio, 3200 - Centro, Campo Grande - MS, CEP 79202-333",
            "phone": "(67) 3341-4444",
            "whatsapp": "(67) 3321-4500",
            "email": "contato@emporiodamusica.com.br",
            "opening_hours": {
                "monday_to_friday": "09:00 - 18:00",
                "saturday": "09:00 - 13:00",
                "sunday_and_holidays": "closed",
            },
            "note": "A loja vende apenas instrumentos musicais, sem acessórios.",
        }

    def create_support_ticket(self, ticket_type, summary, order_id=None):
        if order_id is not None and int(order_id) not in self.verified_orders:
            return {"error": "O pedido precisa ser verificado com get_order_status antes de entrar no registro."}
        ticket = {
            "ticket_id": f"EM-{uuid.uuid4().hex[:8].upper()}",
            "type": ticket_type,
            "summary": str(summary)[:1000],
            "order_id": order_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.tickets_file.parent.mkdir(parents=True, exist_ok=True)
        with self.tickets_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ticket, ensure_ascii=False) + "\n")
        return {
            "ticket_id": ticket["ticket_id"],
            "status": "registrado para a equipe",
            "response_time": ("até 24 horas úteis (manual §7.3)" if ticket_type == "reclamacao"
                              else "a equipe entra em contato; o manual não define prazo para este caso"),
        }


# Compatibilidade: chamada avulsa sem estado de conversa (usada em testes rápidos).
_DEFAULT = StoreTools()


def call_tool(name: str, arguments: dict) -> str:
    return _DEFAULT.call(name, arguments)
