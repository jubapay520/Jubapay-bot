import os
import uuid
import base64
import asyncio
import requests
import psycopg
from io import BytesIO
from decimal import Decimal
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
MISTIC_CI = os.getenv("MISTIC_CI")
MISTIC_CS = os.getenv("MISTIC_CS")
DATABASE_URL = os.getenv("DATABASE_URL")

CREATE_URL = "https://api.misticpay.com/api/transactions/create"
CHECK_URL = "https://api.misticpay.com/api/transactions/check"
BALANCE_URL = "https://api.misticpay.com/api/users/balance"
WITHDRAW_URL = "https://api.misticpay.com/api/transactions/withdraw"

headers = {
    "ci": MISTIC_CI,
    "cs": MISTIC_CS,
    "Content-Type": "application/json"
}

conn = psycopg.connect(DATABASE_URL)
conn.autocommit = True
cursor = conn.cursor()

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


def criar_usuario(user):
    cursor.execute("""
        INSERT INTO usuarios (telegram_id, nome)
        VALUES (%s, %s)
        ON CONFLICT (telegram_id) DO NOTHING
    """, (user.id, user.full_name))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_usuario(update.effective_user)

    await update.message.reply_text(
        "🚀 Bem-vindo ao JubaPay!\n\n"
        "Comandos:\n"
        "/depositar 5 - Depositar via PIX\n"
        "/pix 5 - Depositar via PIX\n"
        "/saldo - Ver sua carteira\n"
        "/sacar 5 SUA_CHAVE_PIX - Sacar saldo"
    )


async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_usuario(update.effective_user)
    user_id = update.effective_user.id

    cursor.execute("SELECT saldo FROM usuarios WHERE telegram_id=%s", (user_id,))
    saldo_atual = cursor.fetchone()[0]

    await update.message.reply_text(
        f"💰 SUA CARTEIRA JUBAPAY\n\n"
        f"Saldo disponível: R$ {float(saldo_atual):.2f}"
    )


async def saldo_mistic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        r = requests.get(
            BALANCE_URL,
            headers={"ci": MISTIC_CI, "cs": MISTIC_CS},
            timeout=10
        )
        data = r.json()
        saldo_valor = data.get("data", {}).get("balance", 0)

        await update.message.reply_text(
            f"🏦 SALDO MISTIC PAY\n\nR$ {float(saldo_valor):.2f}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao consultar saldo Mistic:\n{e}")


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
                cursor.execute(
                    "SELECT status FROM transacoes WHERE transaction_id=%s",
                    (transaction_id,)
                )
                atual = cursor.fetchone()

                if atual and atual[0] == "COMPLETO":
                    return

                cursor.execute("""
                    UPDATE usuarios
                    SET saldo = saldo + %s
                    WHERE telegram_id = %s
                """, (valor, telegram_id))

                cursor.execute("""
                    UPDATE transacoes
                    SET status = 'COMPLETO'
                    WHERE transaction_id = %s
                """, (transaction_id,))

                cursor.execute("SELECT saldo FROM usuarios WHERE telegram_id=%s", (telegram_id,))
                novo_saldo = cursor.fetchone()[0]

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "✅ PAGAMENTO APROVADO!\n\n"
                        f"💰 Valor depositado: R$ {float(valor):.2f}\n"
                        f"🧾 ID: {transaction_id}\n\n"
                        f"💼 Novo saldo: R$ {float(novo_saldo):.2f}"
                    )
                )
                return

            if status == "FALHA":
                cursor.execute("""
                    UPDATE transacoes
                    SET status = 'FALHA'
                    WHERE transaction_id = %s
                """, (transaction_id,))

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ PIX falhou ou foi rejeitado.\nID: {transaction_id}"
                )
                return

        except Exception as e:
            print("Erro ao verificar pagamento:", e)


async def depositar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_usuario(update.effective_user)

    if len(context.args) == 0:
        await update.message.reply_text("Use assim: /depositar 5")
        return

    try:
        valor = Decimal(context.args[0].replace(",", "."))
    except Exception:
        await update.message.reply_text("Valor inválido. Exemplo: /depositar 5")
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
        r = requests.post(CREATE_URL, json=payload, headers=headers, timeout=15)
        data = r.json()

        if r.status_code not in [200, 201]:
            await update.message.reply_text(f"❌ Erro ao gerar PIX:\n{data}")
            return

        pix_data = data.get("data", {})
        transaction_id = pix_data.get("transactionId", transaction_id)

        cursor.execute("""
            INSERT INTO transacoes (telegram_id, transaction_id, tipo, valor, status)
            VALUES (%s, %s, 'DEPOSITO', %s, 'PENDENTE')
            ON CONFLICT (transaction_id) DO NOTHING
        """, (update.effective_user.id, transaction_id, valor))

        copia_cola = pix_data.get("copyPaste")
        qr_url = pix_data.get("qrcodeUrl")
        qr_base64 = pix_data.get("qrCodeBase64")

        msg = (
            "✅ PIX gerado com sucesso!\n\n"
            f"💰 Valor: R$ {float(valor):.2f}\n"
            f"🧾 ID: {transaction_id}\n\n"
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
        valor = Decimal(context.args[0].replace(",", "."))
        chave_pix = context.args[1]
    except Exception:
        await update.message.reply_text("Valor inválido. Exemplo: /sacar 5 sua-chave-pix")
        return

    cursor.execute("SELECT saldo FROM usuarios WHERE telegram_id=%s", (user_id,))
    saldo_atual = cursor.fetchone()[0]

    if saldo_atual < valor:
        await update.message.reply_text(
            f"❌ Saldo insuficiente.\n\n"
            f"Seu saldo: R$ {float(saldo_atual):.2f}"
        )
        return

    payload = {
        "amount": float(valor),
        "pixKey": chave_pix,
        "pixKeyType": "EMAIL",
        "description": "Saque carteira JubaPay"
    }

    try:
        r = requests.post(WITHDRAW_URL, json=payload, headers=headers, timeout=15)
        data = r.json()

        if r.status_code not in [200, 201]:
            await update.message.reply_text(f"❌ Erro ao solicitar saque:\n{data}")
            return

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
            "📤 SAQUE SOLICITADO!\n\n"
            f"💰 Valor: R$ {float(valor):.2f}\n"
            f"🔑 Chave PIX: {chave_pix}\n"
            f"💼 Saldo restante: R$ {float(novo_saldo):.2f}\n\n"
            "Aguarde o processamento da Mistic Pay."
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Erro interno no saque:\n{e}")


async def historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    criar_usuario(update.effective_user)
    user_id = update.effective_user.id

    cursor.execute("""
        SELECT tipo, valor, status, criado_em
        FROM transacoes
        WHERE telegram_id=%s
        ORDER BY criado_em DESC
        LIMIT 10
    """, (user_id,))

    linhas = cursor.fetchall()

    if not linhas:
        await update.message.reply_text("Você ainda não tem transações.")
        return

    msg = "📜 ÚLTIMAS TRANSAÇÕES\n\n"

    for tipo, valor, status, criado_em in linhas:
        msg += f"{tipo} | R$ {float(valor):.2f} | {status}\n"

    await update.message.reply_text(msg)


app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("depositar", depositar))
app.add_handler(CommandHandler("pix", depositar))
app.add_handler(CommandHandler("saldo", saldo))
app.add_handler(CommandHandler("saldo_mistic", saldo_mistic))
app.add_handler(CommandHandler("sacar", sacar))
app.add_handler(CommandHandler("saque", sacar))
app.add_handler(CommandHandler("historico", historico))

print("BOT INICIANDO COM CARTEIRAS INDIVIDUAIS...")

app.run_polling()
