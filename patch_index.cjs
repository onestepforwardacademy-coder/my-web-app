const fs = require('fs');
let c = fs.readFileSync('/root/my-web-app/index.js', 'utf8');
const old = /if \(state\.awaitingSwapToken\) \{[\s\S]*?return;\s*\}/;
const replacement = `if (state.awaitingSwapToken) {
        state.awaitingSwapToken = false;
        const tokenAddr = text.trim();
        await updateStatusMessage(chatId, "🔍 *Fetching Token Info...*");
        try {
            const r = await fetch("https://api.dexscreener.com/latest/dex/tokens/" + tokenAddr);
            const d = await r.json();
            const p = d.pairs ? d.pairs[0] : null;
            if (!p) {
                await bot.sendMessage(chatId, "❌ Token not found on Dexscreener.");
                return showMenu(chatId, "👑 *LUXE SOLANA WALLET* 👑");
            }
            state.pendingSwapMint = tokenAddr;
            state.awaitingSwapAmount = true;
            const infoText = "💎 *TOKEN FOUND: " + p.baseToken.name + "*\\n" +
                             "💰 *Price:* $" + p.priceUsd + "\\n" +
                             "💧 *Liquidity:* $" + p.liquidity.usd + "\\n\\n" +
                             "💰 *Enter amount of SOL to swap:*";
            const sent = await bot.sendMessage(chatId, infoText, {
                parse_mode: "Markdown",
                reply_markup: { inline_keyboard: [[{ text: "⬅️ BACK", callback_data: "back_home" }]] }
            });
            state.lastPromptId = sent.message_id;
        } catch (e) {
            await bot.sendMessage(chatId, "❌ Error fetching token info.");
        }
        return;
    }`;
fs.writeFileSync('/root/my-web-app/index.js', c.replace(old, replacement));
