import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Bot JubaPay online!\n\nUse /pix 50 para testar."
    )

async def pix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Use: /pix 50")
        return

    valor = context.args[0]

    await update.message.reply_text(
        f"💰 Gerando PIX de R$ {valor}..."
    )

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("pix", pix))

app.run_polling()
