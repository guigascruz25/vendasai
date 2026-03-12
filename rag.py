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

DEFAULT_SYSTEM_PROMPT = """Você é um assistente especializado de suporte à equipe comercial.

Seu papel é ajudar os vendedores a fechar mais vendas respondendo com base EXCLUSIVAMENTE nos documentos fornecidos abaixo.

Diretrizes:
- Responda de forma direta, prática e orientada a conversão
- Se a pergunta for sobre como lidar com uma objeção, dê a resposta pronta para o vendedor usar
- Se a informação não estiver nos documentos, diga claramente: "Não tenho essa informação nos documentos disponíveis."
- Use linguagem profissional mas acessível em português brasileiro
- Seja conciso — vendedores precisam de respostas rápidas

{doc_context}"""


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


def build_document_context(max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """Monta o bloco de contexto com os documentos ativos."""
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


def build_system_prompt(custom_prompt: str = None) -> str:
    """Monta o system prompt com os documentos embutidos."""
    doc_context = build_document_context()
    base = custom_prompt if custom_prompt else DEFAULT_SYSTEM_PROMPT

    if not doc_context:
        doc_context = "\n\n[Nenhum documento carregado ainda. Peça ao administrador para subir os PDFs.]"

    return base.format(doc_context=doc_context)
