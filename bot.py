import os
import uuid
import base64
import asyncio
import requests
import psycopg
from io import BytesIO
from decimal import Decimal, ROUND_DOWN
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
MISTIC_CI = os.getenv("MISTIC_CI")
MISTIC_CS = os.getenv("MISTIC_CS")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = os.getenv("ADMIN_ID") or os.getenv("TELEGRAM_ADMIN_ID")

CREATE_URL = "https://api.misticpay.com/api/transactions/create"
CHECK_URL = "https://api.misticpay.com/api/transactions/check"
BALANCE_URL = "https://api.misticpay.com/api/users/balance"
WITHDRAW_URL = "https://api.misticpay.com/api/transactions/withdraw"

TAXA_CREDITO = Decimal("0.07")

headers = {
    "ci": MISTIC_CI,
    "cs": MISTIC_CS,
    "Content-Type": "application/json"
}

conn = psycopg.connect(DATABASE_URL)
conn.autocommit = True


def dinheiro(valor):
    return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def criar_tabelas():
    with conn.cursor() as cursor:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            telegram_id BIGINT PRIMARY KEY,
            nome TEXT,
            saldo NUMERIC(10,2) DEFAULT 0,
            criado_em TIMESTAMP DEFAULT NOW()
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS transacoes (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT,
            transaction_id TEXT UNIQUE,
            tipo TEXT,
            valor NUMERIC(10,2),
            status TEXT DEFAULT 'PENDENTE',
            criado_em TIMESTAMP DEFAULT NOW()
        )
        """)

        cursor.execute("""
        ALTER TABLE transacoes
        ADD COLUMN IF NOT EXISTS valor_creditado NUMERIC(10,2) DEFAULT 0
        """)


def criar_usuario(user):
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO usuarios (telegram_id, nome)
            VALUES (%s, %s)
            ON CONFLICT (telegram_id) DO UPDATE SET nome = EXCLUDED.nome
        """, (user.id, user.full_name))


def tipo_chave_pix(chave):
    chave_limpa = chave.replace(".", "").replace("-", "").replace("/", "")
    if "@" in chave:
        return "EMAIL"
    if chave_limpa.isdigit() and len(chave_limpa) == 11:
        return "CPF"
    if chave_limpa.isdigit() and len(chave_limpa) == 14:
        return "CNPJ"
    if chave.startswith("+"):
        return "PHONE"
    return "RANDOM"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_usuario(update.effective_user)

    await update.message.reply_text(
        "🔥 Bem-vindo à JubaPay!\n\n"
        "Sua carteira digital inteligente.\n\n"
        "✅ Depósitos via PIX\n"
        "✅ Carteira individual\n"
        "✅ Saldo automático\n"
        "✅ Saques via PIX\n\n"
        "📌 Comandos disponíveis:\n\n"
        "/depositar 5 - Depositar via PIX\n"
        "/pix 5 - Depositar via PIX\n"
        "/saldo - Ver sua carteira\n"
        "/historico - Ver movimentações\n"
        "/perfil - Ver seu perfil\n"
        "/sacar 5 SUA_CHAVE_PIX - Solicitar saque\n\n"
        "💎 JubaPay — sua liberdade financeira dentro do Telegram."
    )


async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_usuario(update.effective_user)

    with conn.cursor() as cursor:
        cursor.execute("SELECT saldo FROM usuarios WHERE telegram_id=%s", (update.effective_user.id,))
        saldo_atual = cursor.fetchone()[0]

    await update.message.reply_text(
        "💰 SUA CARTEIRA JUBAPAY\n\n"
        f"Saldo disponível: R$ {float(saldo_atual):.2f}"
    )


async def saldo_mistic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        r = requests.get(BALANCE_URL, headers={"ci": MISTIC_CI, "cs": MISTIC_CS}, timeout=10)
        data = r.json()
        saldo_valor = data.get("data", {}).get("balance", 0)

        await update.message.reply_text(
            "🏦 SALDO MISTIC PAY\n\n"
            f"R$ {float(saldo_valor):.2f}"
        )
    except Exception:
        await update.message.reply_text("⚠️ Não foi possível consultar o saldo agora.")


async def verificar_pagamento(chat_id, telegram_id, transaction_id, valor, context):
    for _ in range(60):
        await asyncio.sleep(10)

        try:
            r = requests.post(
                CHECK_URL,
                json={"transactionId": transaction_id},
                headers=headers,
                timeout=10
            )

            data = r.json()
            transacao = data.get("transaction", {})
            status = transacao.get("transactionState")

            if status == "COMPLETO":
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT status FROM transacoes WHERE transaction_id=%s",
                        (transaction_id,)
                    )
                    atual = cursor.fetchone()

                    if atual and atual[0] == "COMPLETO":
                        return

                    valor_creditado = dinheiro(valor - (valor * TAXA_CREDITO))

                    cursor.execute("""
                        UPDATE usuarios
                        SET saldo = saldo + %s
                        WHERE telegram_id = %s
                    """, (valor_creditado, telegram_id))

                    cursor.execute("""
                        UPDATE transacoes
                        SET status = 'COMPLETO', valor_creditado = %s
                        WHERE transaction_id = %s
                    """, (valor_creditado, transaction_id))

                    cursor.execute("SELECT saldo FROM usuarios WHERE telegram_id=%s", (telegram_id,))
                    novo_saldo = cursor.fetchone()[0]

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "🎉 DEPÓSITO CONFIRMADO\n\n"
                        f"💰 Valor pago: R$ {float(valor):.2f}\n"
                        f"📉 Taxa aplicada: 7%\n"
                        f"🏦 Creditado na carteira: R$ {float(valor_creditado):.2f}\n\n"
                        f"📦 Saldo atual: R$ {float(novo_saldo):.2f}\n\n"
                        "✅ Transação concluída"
                    )
                )
                return

            if status == "FALHA":
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE transacoes
                        SET status = 'FALHA'
                        WHERE transaction_id = %s
                    """, (transaction_id,))

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ PIX não aprovado.\n\nA transação falhou ou foi recusada."
                )
                return

        except Exception as e:
            print("Erro ao verificar pagamento:", e)


async def depositar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_usuario(update.effective_user)

    if len(context.args) == 0:
        await update.message.reply_text("Use assim:\n/depositar 5")
        return

    try:
        valor = dinheiro(context.args[0].replace(",", "."))
    except Exception:
        await update.message.reply_text("Valor inválido.\n\nExemplo:\n/depositar 5")
        return

    if valor <= 0:
        await update.message.reply_text("O valor precisa ser maior que zero.")
        return

    transaction_id = str(uuid.uuid4())

    payload = {
        "amount": float(valor),
        "payerName": update.effective_user.full_name or "Cliente Telegram",
        "payerDocument": "12345678909",
        "transactionId": transaction_id,
        "description": f"Depósito JubaPay R$ {float(valor):.2f}"
    }

    await update.message.reply_text("⏳ Gerando PIX, aguarde...")

    try:
        r = requests.post(CREATE_URL, json=payload, headers=headers, timeout=20)
        data = r.json()

        if r.status_code not in [200, 201]:
            await update.message.reply_text(
                "⚠️ Não foi possível gerar o PIX agora.\n"
                "Tente novamente em alguns minutos."
            )
            return

        pix_data = data.get("data", {})
        transaction_id = pix_data.get("transactionId", transaction_id)

        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO transacoes (telegram_id, transaction_id, tipo, valor, status)
                VALUES (%s, %s, 'DEPOSITO', %s, 'PENDENTE')
                ON CONFLICT (transaction_id) DO NOTHING
            """, (update.effective_user.id, transaction_id, valor))

        copia_cola = pix_data.get("copyPaste")
        qr_url = pix_data.get("qrcodeUrl")
        qr_base64 = pix_data.get("qrCodeBase64")

        msg = (
            "✅ PIX GERADO COM SUCESSO\n\n"
            f"💰 Valor: R$ {float(valor):.2f}\n\n"
        )

        if copia_cola:
            msg += f"📋 Copia e cola:\n{copia_cola}"

        await update.message.reply_text(msg)

        if qr_url:
            await update.message.reply_photo(photo=qr_url)
        elif qr_base64:
            qr_clean = qr_base64.replace("data:image/png;base64,", "")
            img = BytesIO(base64.b64decode(qr_clean))
            img.name = "pix.png"
            await update.message.reply_photo(photo=img)

        await update.message.reply_text("⏳ Aguardando pagamento...")

        asyncio.create_task(
            verificar_pagamento(
                update.message.chat_id,
                update.effective_user.id,
                transaction_id,
                valor,
                context
            )
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Erro interno:\n{e}")


async def sacar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_usuario(update.effective_user)
    user_id = update.effective_user.id

    if len(context.args) < 2:
        await update.message.reply_text(
            "Use assim:\n/sacar 5 SUA_CHAVE_PIX\n\n"
            "Exemplo:\n/sacar 5 anuichjorge@hotmail.com"
        )
        return

    try:
        valor = dinheiro(context.args[0].replace(",", "."))
        chave_pix = context.args[1]
    except Exception:
        await update.message.reply_text("Valor inválido.\n\nExemplo:\n/sacar 5 sua-chave-pix")
        return

    with conn.cursor() as cursor:
        cursor.execute("SELECT saldo FROM usuarios WHERE telegram_id=%s", (user_id,))
        saldo_atual = cursor.fetchone()[0]

    if saldo_atual < valor:
        await update.message.reply_text(
            "❌ SALDO INSUFICIENTE\n\n"
            f"Seu saldo atual é R$ {float(saldo_atual):.2f}."
        )
        return

    payload = {
        "amount": float(valor),
        "pixKey": chave_pix,
        "pixKeyType": tipo_chave_pix(chave_pix),
        "description": "Saque carteira JubaPay"
    }

    try:
        r = requests.post(WITHDRAW_URL, json=payload, headers=headers, timeout=20)
        data = r.json()

        if r.status_code not in [200, 201]:
            mensagem_api = str(data.get("message", "")).lower()

            if "aguardando aprovação" in mensagem_api or "pending" in str(data).lower():
                await update.message.reply_text(
                    "⏳ SAQUE EM ANÁLISE\n\n"
                    "Seu pedido foi registrado com sucesso.\n"
                    "Aguarde a aprovação do saque."
                )
            elif "saldo insuficiente" in mensagem_api:
                await update.message.reply_text(
                    "❌ SALDO INSUFICIENTE\n\n"
                    "Você não possui saldo suficiente para realizar este saque."
                )
            else:
                await update.message.reply_text(
                    "⚠️ Não foi possível processar o saque.\n"
                    "Tente novamente mais tarde."
                )
            return

        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE usuarios
                SET saldo = saldo - %s
                WHERE telegram_id = %s
            """, (valor, user_id))

            transaction_id = str(data.get("data", {}).get("transactionId", uuid.uuid4()))

            cursor.execute("""
                INSERT INTO transacoes (telegram_id, transaction_id, tipo, valor, status)
                VALUES (%s, %s, 'SAQUE', %s, 'PENDENTE')
            """, (user_id, transaction_id, valor))

            cursor.execute("SELECT saldo FROM usuarios WHERE telegram_id=%s", (user_id,))
            novo_saldo = cursor.fetchone()[0]

        await update.message.reply_text(
            "📤 SAQUE SOLICITADO\n\n"
            f"💰 Valor: R$ {float(valor):.2f}\n"
            f"🔑 Chave PIX: {chave_pix}\n"
            f"💼 Saldo restante: R$ {float(novo_saldo):.2f}\n\n"
            "⏳ Aguarde o processamento."
        )

    except Exception:
        await update.message.reply_text(
            "⚠️ Não foi possível processar o saque agora.\n"
            "Tente novamente mais tarde."
        )


async def historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_usuario(update.effective_user)

    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT tipo, valor, valor_creditado, status, criado_em
            FROM transacoes
            WHERE telegram_id=%s
            ORDER BY criado_em DESC
            LIMIT 10
        """, (update.effective_user.id,))
        linhas = cursor.fetchall()

    if not linhas:
        await update.message.reply_text("📜 Você ainda não possui movimentações.")
        return

    msg = "📜 ÚLTIMAS TRANSAÇÕES\n\n"

    for tipo, valor, valor_creditado, status, criado_em in linhas:
        if tipo == "DEPOSITO":
            msg += f"📥 Depósito | Pago R$ {float(valor):.2f} | Creditado R$ {float(valor_creditado):.2f} | {status}\n"
        else:
            msg += f"📤 Saque | R$ {float(valor):.2f} | {status}\n"

    await update.message.reply_text(msg)


async def perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_usuario(update.effective_user)
    user_id = update.effective_user.id

    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT nome, saldo, criado_em
            FROM usuarios
            WHERE telegram_id=%s
        """, (user_id,))
        usuario = cursor.fetchone()

        cursor.execute("""
            SELECT COALESCE(SUM(valor_creditado), 0)
            FROM transacoes
            WHERE telegram_id=%s AND tipo='DEPOSITO' AND status='COMPLETO'
        """, (user_id,))
        total_depositado = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COALESCE(SUM(valor), 0)
            FROM transacoes
            WHERE telegram_id=%s AND tipo='SAQUE'
        """, (user_id,))
        total_sacado = cursor.fetchone()[0]

    await update.message.reply_text(
        "👤 PERFIL JUBAPAY\n\n"
        f"Nome: {usuario[0]}\n"
        f"ID: {user_id}\n\n"
        f"💰 Saldo: R$ {float(usuario[1]):.2f}\n"
        f"📥 Total depositado: R$ {float(total_depositado):.2f}\n"
        f"📤 Total sacado: R$ {float(total_sacado):.2f}"
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID and str(update.effective_user.id) != str(ADMIN_ID):
        await update.message.reply_text("Acesso não autorizado.")
        return

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM usuarios")
        usuarios = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(saldo), 0) FROM usuarios")
        saldo_total = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COALESCE(SUM(valor_creditado), 0)
            FROM transacoes
            WHERE tipo='DEPOSITO' AND status='COMPLETO'
        """)
        depositos = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COALESCE(SUM(valor), 0)
            FROM transacoes
            WHERE tipo='SAQUE'
        """)
        saques = cursor.fetchone()[0]

    await update.message.reply_text(
        "📊 PAINEL ADMIN JUBAPAY\n\n"
        f"👥 Usuários: {usuarios}\n"
        f"💰 Saldo total nas carteiras: R$ {float(saldo_total):.2f}\n"
        f"📥 Total depositado creditado: R$ {float(depositos):.2f}\n"
        f"📤 Total em saques: R$ {float(saques):.2f}"
    )


async def caixa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID and str(update.effective_user.id) != str(ADMIN_ID):
        await update.message.reply_text("Acesso não autorizado.")
        return

    try:
        r = requests.get(BALANCE_URL, headers={"ci": MISTIC_CI, "cs": MISTIC_CS}, timeout=10)
        data = r.json()
        saldo_mistic_valor = Decimal(str(data.get("data", {}).get("balance", 0)))

        with conn.cursor() as cursor:
            cursor.execute("SELECT COALESCE(SUM(saldo), 0) FROM usuarios")
            saldo_usuarios = Decimal(str(cursor.fetchone()[0]))

        caixa_disponivel = saldo_mistic_valor - saldo_usuarios

        await update.message.reply_text(
            "🏦 CAIXA JUBAPAY\n\n"
            f"Saldo real MisticPay: R$ {float(saldo_mistic_valor):.2f}\n"
            f"Saldo dos usuários: R$ {float(saldo_usuarios):.2f}\n\n"
            f"📈 Caixa disponível estimado: R$ {float(caixa_disponivel):.2f}"
        )

    except Exception:
        await update.message.reply_text("⚠️ Não foi possível consultar o caixa agora.")


criar_tabelas()

app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("depositar", depositar))
app.add_handler(CommandHandler("pix", depositar))
app.add_handler(CommandHandler("saldo", saldo))
app.add_handler(CommandHandler("saldo_mistic", saldo_mistic))
app.add_handler(CommandHandler("sacar", sacar))
app.add_handler(CommandHandler("saque", sacar))
app.add_handler(CommandHandler("historico", historico))
app.add_handler(CommandHandler("perfil", perfil))
app.add_handler(CommandHandler("admin", admin))
app.add_handler(CommandHandler("caixa", caixa))

print("BOT INICIANDO COM CARTEIRAS INDIVIDUAIS.")

app.run_polling()
