import os
import uuid
import json
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
MISTIC_CI = os.getenv("MISTIC_CI")
MISTIC_CS = os.getenv("MISTIC_CS")

MISTIC_URL = "https://api.misticpay.com/api/transactions/create"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Bot JubaPay online!\n\n"
        "Use /pix 5 para gerar um PIX."
    )


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

    headers = {
        "ci": MISTIC_CI,
        "cs": MISTIC_CS,
        "Content-Type": "application/json"
    }

    await update.message.reply_text("⏳ Gerando PIX, aguarde...")

    try:
        response = requests.post(
            MISTIC_URL,
            json=payload,
            headers=headers,
            timeout=8
        )

        texto_resposta = response.text

        try:
            data = response.json()
        except Exception:
            await update.message.reply_text(
                f"❌ A Mistic Pay não retornou JSON.\n\n"
                f"Status: {response.status_code}\n"
                f"Resposta: {texto_resposta[:700]}"
            )
            return

        if response.status_code not in [200, 201]:
            await update.message.reply_text(
                f"❌ Erro ao gerar PIX.\n\n"
                f"Status: {response.status_code}\n"
                f"Resposta:\n{json.dumps(data, ensure_ascii=False)[:900]}"
            )
            return

        pix_data = data.get("data", {})

        copia_cola = pix_data.get("copyPaste")
        qr_url = pix_data.get("qrcodeUrl")
        qr_base64 = pix_data.get("qrCodeBase64")
        transaction_code = pix_data.get("transactionId")

        msg = (
            "✅ PIX gerado com sucesso!\n\n"
            f"💰 Valor: R$ {valor:.2f}\n"
            f"🧾 ID: {transaction_code or transaction_id}\n\n"
        )

        if copia_cola:
            msg += f"📋 Copia e cola:\n`{copia_cola}`"
        else:
            msg += "⚠️ PIX criado, mas não encontrei o campo copyPaste na resposta."

        await update.message.reply_text(msg, parse_mode="Markdown")

        if qr_url:
            await update.message.reply_photo(photo=qr_url)
        elif qr_base64:
            await update.message.reply_text("QR Code veio em base64. Vamos ajustar imagem no próximo passo.")

    except requests.exceptions.Timeout:
        await update.message.reply_text(
            "❌ A Mistic Pay demorou para responder.\n"
            "Tente novamente em alguns segundos."
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Erro interno:\n{str(e)}")


app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("pix", pix))

print("BOT INICIANDO...")

app.run_polling()
