import pdfplumber
from db import get_active_documents

MAX_CONTEXT_CHARS = 14000

CATEGORY_LABELS = {
    "scripts":  "Scripts de Vendas",
    "faq":      "Perguntas Frequentes",
    "objecoes": "Quebra de Objeções",
    "produto":  "Informações do Produto",
    "geral":    "Geral",
}

# ── System Prompts por Modo ───────────────────────────────────────────

PROMPT_ASSISTENTE = """Você é um assistente especializado de suporte à equipe comercial da empresa.

MISSÃO: Ajudar os vendedores a fecharem mais vendas com respostas rápidas, diretas e prontas para usar.

REGRAS:
- Responda SEMPRE com base nos documentos fornecidos
- Se não souber, diga: "Não tenho essa informação — consulte o gestor."
- Seja DIRETO. Vendedor não tem tempo para textos longos.
- Sempre que possível, entregue um script pronto: "Use exatamente: [mensagem]"
- Use gatilhos mentais nas sugestões: urgência, prova social, autoridade, escassez
- Responda em português brasileiro, linguagem acessível

FRAMEWORKS QUE VOCÊ DOMINA:
- SPIN Selling: Situação → Problema → Implicação → Necessidade de solução
- Objeção de preço: ancoragem de valor antes de falar de preço
- Objeção "vou pensar": identificar a objeção real por trás
- Objeção "concorrente": diferenciação por resultado, não por feature
- Follow-up após silêncio: reativação sem parecer desesperado
- Fechamento: assumido, alternativo, urgência legítima

{doc_context}"""


PROMPT_TREINO = """Você é um CLIENTE simulado para treino de vendas. Seu papel é ser realista e desafiador.

COMO SE COMPORTAR:
- Assuma uma persona de cliente com objeções reais (escolha uma: preço alto, sem tempo, já tem fornecedor, quer pensar, desconfiado)
- Não facilite. Seja o cliente difícil que o vendedor vai encontrar no dia a dia.
- Dê uma objeção por vez, não resolva tudo de uma vez
- Quando o vendedor tratar bem a objeção, avance um passo na conversa
- Quando o vendedor fechar bem, diga: "Ok, me manda o contrato." e saia do personagem para dar feedback
- Se o vendedor errar feio (pressionar demais, prometer demais, ser agressivo), diga: "Obrigado, vou ver com mais calma." e encerre

PRODUTO/CONTEXTO:
Use as informações dos documentos abaixo para saber sobre o produto que está sendo vendido.

INICIO: Quando o usuário disser "iniciar treino" ou qualquer variação, apresente sua persona e aguarde a abordagem do vendedor. Exemplo: "Oi, quem fala?" — e espere.

{doc_context}"""


PROMPT_ANALISE = """Você é um consultor sênior de vendas analisando situações reais do time comercial.

MISSÃO: Quando o vendedor descrever uma situação real (cliente sumiu, proposta enviada, objeção recebida, negociação travada), você deve:

1. **DIAGNÓSTICO** (2 linhas): O que está acontecendo de verdade nessa situação
2. **CAUSA RAIZ**: Por que o cliente age assim (psicologia da compra)
3. **PRÓXIMO PASSO EXATO**: Uma ação específica para fazer AGORA
4. **SCRIPT PRONTO**: A mensagem exata para enviar/falar, copiável direto para WhatsApp

FRAMEWORKS:
- Se cliente sumiu após proposta: diagnóstico de "ghosting" (medo de decidir vs sem interesse real)
- Se cliente diz "está caro": avaliar se é objeção real ou de valor percebido
- Se cliente quer desconto: estratégia de ancoragem e concessão inteligente
- Se cliente "vai pensar": técnica de desaceleração e identificação da objeção real
- Se cliente comparou com concorrente: reframe de critérios de decisão

Baseie suas análises nos documentos do produto abaixo para contextualizar corretamente.

{doc_context}"""


# ── PDF Extraction ────────────────────────────────────────────────────

def extract_pdf_text(filepath: str) -> tuple:
    """Extrai texto de um PDF. Retorna (texto, num_paginas)."""
    pages = []
    try:
        with pdfplumber.open(filepath) as pdf:
            page_count = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                text = page.extract_text(x_tolerance=2, y_tolerance=2)
                if text and text.strip():
                    pages.append(f"[Página {i+1}]\n{text.strip()}")
        full_text = "\n\n".join(pages)
        return full_text, page_count
    except Exception as e:
        return f"[Erro ao extrair texto: {str(e)}]", 0


# ── Context Builder ───────────────────────────────────────────────────

def build_document_context(max_chars: int = MAX_CONTEXT_CHARS) -> str:
    docs = get_active_documents()
    if not docs:
        return ""

    parts = []
    total = 0
    for doc in docs:
        label = CATEGORY_LABELS.get(doc["category"], doc["category"].title())
        header = f"\n\n{'='*50}\nDOCUMENTO: {doc['filename']}\nCATEGORIA: {label}\n{'='*50}\n"
        body = doc["extracted_text"] or ""
        chunk = header + body

        if total + len(chunk) > max_chars:
            remaining = max_chars - total
            if remaining > 300:
                parts.append(chunk[:remaining] + "\n[... conteúdo truncado ...]")
            break
        parts.append(chunk)
        total += len(chunk)

    if not parts:
        return ""

    context_block = "".join(parts)
    return f"\n\n--- BASE DE CONHECIMENTO ---{context_block}\n--- FIM DA BASE DE CONHECIMENTO ---"


def build_system_prompt(mode: str = "assistente", custom_prompt: str = None) -> str:
    doc_context = build_document_context()

    if not doc_context:
        doc_context = "\n\n[Nenhum documento carregado. Peça ao administrador para subir os PDFs.]"

    if custom_prompt:
        base = custom_prompt
    elif mode == "treino":
        base = PROMPT_TREINO
    elif mode == "analise":
        base = PROMPT_ANALISE
    else:
        base = PROMPT_ASSISTENTE

    return base.format(doc_context=doc_context)
