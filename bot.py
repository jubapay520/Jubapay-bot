import os
import uuid
import base64
import asyncio
import requests
from io import BytesIO
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
MISTIC_CI = os.getenv("MISTIC_CI")
MISTIC_CS = os.getenv("MISTIC_CS")

CREATE_URL = "https://api.misticpay.com/api/transactions/create"
CHECK_URL = "https://api.misticpay.com/api/transactions/check"
BALANCE_URL = "https://api.misticpay.com/api/users/balance"
WITHDRAW_URL = "https://api.misticpay.com/api/transactions/withdraw"

headers = {
    "ci": MISTIC_CI,
    "cs": MISTIC_CS,
    "Content-Type": "application/json"
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Bot JubaPay online!\n\n"
        "Use /pix 5 para gerar PIX.\n"
        "Use /saldo para ver saldo.\n"
        "Use /saque 10 SUA_CHAVE_PIX para sacar."
    )


async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        r = requests.get(
            BALANCE_URL,
            headers={
                "ci": MISTIC_CI,
                "cs": MISTIC_CS
            },
            timeout=10
        )

        data = r.json()
        saldo_valor = data.get("data", {}).get("balance", 0)

        await update.message.reply_text(
            f"💰 SALDO DISPONÍVEL\n\nR$ {saldo_valor:.2f}"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao consultar saldo:\n{str(e)}")


async def saque(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Use assim:\n/saque 10 SUA_CHAVE_PIX\n\n"
            "Exemplo:\n/saque 10 12345678900"
        )
        return

    try:
        valor = float(context.args[0].replace(",", "."))
        chave_pix = context.args[1]
    except Exception:
        await update.message.reply_text("Valor inválido. Exemplo: /saque 10 12345678900")
        return

    payload = {
        "amount": valor,
        "pixKey": chave_pix,
        "pixKeyType": "CPF",
        "description": "Saque Telegram"
    }

    try:
        r = requests.post(
            WITHDRAW_URL,
            json=payload,
            headers=headers,
            timeout=15
        )

        data = r.json()

        if r.status_code not in [200, 201]:
            await update.message.reply_text(f"❌ Erro ao solicitar saque:\n{data}")
            return

        await update.message.reply_text(
            "📤 SAQUE SOLICITADO!\n\n"
            f"💰 Valor: R$ {valor:.2f}\n"
            f"🔑 Chave PIX: {chave_pix}\n\n"
            f"Resposta:\n{data}"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Erro interno no saque:\n{str(e)}")


async def verificar_pagamento(chat_id, transaction_id, valor, context):
    for _ in range(30):
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
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "✅ PAGAMENTO APROVADO!\n\n"
                        f"💰 Valor: R$ {valor:.2f}\n"
                        f"🧾 ID: {transaction_id}\n\n"
                        "🎉 PIX confirmado com sucesso."
                    )
                )
                return

            if status == "FALHA":
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ PIX falhou ou foi rejeitado.\nID: {transaction_id}"
                )
                return

        except Exception as e:
            print("Erro ao verificar pagamento:", e)


async def pix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Use assim: /pix 5")
        return

    try:
        valor = float(context.args[0].replace(",", "."))
    except Exception:
        await update.message.reply_text("Valor inválido. Exemplo: /pix 5")
        return

    transaction_id = str(uuid.uuid4())

    payload = {
        "amount": valor,
        "payerName": "Cliente Telegram",
        "payerDocument": "12345678909",
        "transactionId": transaction_id,
        "description": f"Pagamento Telegram R$ {valor:.2f}"
    }

    await update.message.reply_text("⏳ Gerando PIX, aguarde...")

    try:
        r = requests.post(
            CREATE_URL,
            json=payload,
            headers=headers,
            timeout=15
        )

        data = r.json()

        if r.status_code not in [200, 201]:
            await update.message.reply_text(f"❌ Erro ao gerar PIX:\n{data}")
            return

        pix_data = data.get("data", {})
        transaction_id = pix_data.get("transactionId", transaction_id)

        copia_cola = pix_data.get("copyPaste")
        qr_url = pix_data.get("qrcodeUrl")
        qr_base64 = pix_data.get("qrCodeBase64")

        msg = (
            "✅ PIX gerado com sucesso!\n\n"
            f"💰 Valor: R$ {valor:.2f}\n"
            f"🧾 ID: {transaction_id}\n\n"
        )

        if copia_cola:
            msg += f"📋 Copia e cola:\n{copia_cola}"
        else:
            msg += "⚠️ PIX criado, mas não encontrei o copia e cola."

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
                transaction_id,
                valor,
                context
            )
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Erro interno:\n{str(e)}")


app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("pix", pix))
app.add_handler(CommandHandler("saldo", saldo))
app.add_handler(CommandHandler("saque", saque))

print("BOT INICIANDO...")

app.run_polling()
