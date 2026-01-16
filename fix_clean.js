const fs = require("fs");
let content = fs.readFileSync("index.js", "utf8");

// Find the message handler ending
const searchPattern = /await showMenu\(chatId, "👑 \*LUXE SOLANA WALLET\* 👑"\);\s*\}\);/;

const handlers = `
    // SEARCH TOKEN handler
    if (state.awaitingSearch) {
        state.awaitingSearch = false;
        const tokenAddr = text.trim();
        if (tokenAddr.length < 30) {
            await updateStatusMessage(chatId, "Invalid token address.", 5000);
            return showMenu(chatId, "LUXE SOLANA WALLET");
        }
        await updateStatusMessage(chatId, "Searching token...");
        const pyProc = spawnPython("search_token.py", [tokenAddr]);
        let output = "";
        pyProc.stdout.on("data", (d) => { output += d.toString(); });
        pyProc.stderr.on("data", (d) => { output += d.toString(); });
        pyProc.on("close", async () => {
            const resultMsg = await bot.sendMessage(chatId, "<pre>" + (output.trim() || "No data found") + "</pre>", {
                parse_mode: "HTML",
                reply_markup: { inline_keyboard: [[{ text: "BACK", callback_data: "back_home" }]] }
            });
            setTimeout(() => deleteMessageSafe(chatId, resultMsg.message_id), 120000);
        });
        return;
    }

    // ANALYSE TOKEN handler
    if (state.awaitingAnalysis) {
        state.awaitingAnalysis = false;
        const tokenAddr = text.trim();
        if (tokenAddr.length < 30) {
            await updateStatusMessage(chatId, "Invalid token address.", 5000);
            return showMenu(chatId, "LUXE SOLANA WALLET");
        }
        await updateStatusMessage(chatId, "Analysing token...");
        const pyProc = spawnPython("analysis_fast.py", [tokenAddr]);
        let output = "";
        pyProc.stdout.on("data", (d) => { output += d.toString(); });
        pyProc.stderr.on("data", (d) => { output += d.toString(); });
        pyProc.on("close", async () => {
            const resultMsg = await bot.sendMessage(chatId, "<pre>" + (output.trim() || "Analysis failed") + "</pre>", {
                parse_mode: "HTML",
                reply_markup: { inline_keyboard: [[{ text: "BACK", callback_data: "back_home" }]] }
            });
            setTimeout(() => deleteMessageSafe(chatId, resultMsg.message_id), 120000);
        });
        return;
    }

    // VERIFY RUG handler
    if (state.awaitingVerifyRug) {
        state.awaitingVerifyRug = false;
        const tokenAddr = text.trim();
        if (tokenAddr.length < 30) {
            await updateStatusMessage(chatId, "Invalid token address.", 5000);
            return showMenu(chatId, "LUXE SOLANA WALLET");
        }
        await updateStatusMessage(chatId, "Checking rug status...");
        const pyProc = spawnPython("verify_rug_fast.py", [tokenAddr]);
        let output = "";
        pyProc.stdout.on("data", (d) => { output += d.toString(); });
        pyProc.stderr.on("data", (d) => { output += d.toString(); });
        pyProc.on("close", async () => {
            const resultMsg = await bot.sendMessage(chatId, "<pre>" + (output.trim() || "Check failed") + "</pre>", {
                parse_mode: "HTML",
                reply_markup: { inline_keyboard: [[{ text: "BACK", callback_data: "back_home" }]] }
            });
            setTimeout(() => deleteMessageSafe(chatId, resultMsg.message_id), 120000);
        });
        return;
    }

    // SWAP TOKEN handler
    if (state.awaitingSwapToken) {
        state.awaitingSwapToken = false;
        const tokenAddr = text.trim();
        if (tokenAddr.length < 30) {
            await updateStatusMessage(chatId, "Invalid token address.", 5000);
            return showMenu(chatId, "LUXE SOLANA WALLET");
        }
        state.pendingSwapToken = tokenAddr;
        state.awaitingSwapAmount = true;
        const sent = await bot.sendMessage(chatId, "Enter amount (e.g., 0.01 SOL or $5 USD):", { 
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "BACK", callback_data: "back_home" }]] }
        });
        state.lastPromptId = sent.message_id;
        return;
    }

    // SWAP AMOUNT handler
    if (state.awaitingSwapAmount) {
        state.awaitingSwapAmount = false;
        let inputText = text.trim().toUpperCase();
        const isUsd = inputText.includes("USD") || inputText.includes("$");
        const numericValue = parseFloat(inputText.replace(/[^0-9.]/g, ""));
        
        if (isNaN(numericValue) || numericValue <= 0) {
            await updateStatusMessage(chatId, "Invalid amount.", 5000);
            return showMenu(chatId, "LUXE SOLANA WALLET");
        }
        
        let amountSol;
        if (isUsd) {
            await fetchLiveSolPrice();
            amountSol = numericValue / SOL_TO_USD_RATE;
            await updateStatusMessage(chatId, "Converting $" + numericValue + " to " + amountSol.toFixed(4) + " SOL...");
        } else {
            amountSol = numericValue;
        }
        
        const tokenAddr = state.pendingSwapToken;
        state.pendingSwapToken = null;
        
        await updateStatusMessage(chatId, "Fetching token info...");
        
        const pyProc = spawnPython("swap.py", ["info", tokenAddr]);
        let output = "";
        pyProc.stdout.on("data", (d) => { output += d.toString(); });
        pyProc.stderr.on("data", (d) => { output += d.toString(); });
        pyProc.on("close", async () => {
            let tokenInfo = null;
            try { tokenInfo = JSON.parse(output.trim()); } catch (e) {}
            
            state.pendingSwap = { token: tokenAddr, amount: amountSol, tokenInfo: tokenInfo };
            
            let confirmText = "<b>CONFIRM SWAP</b>\\n\\n";
            confirmText += "<b>Token:</b> " + (tokenInfo?.name || "Unknown") + " (" + (tokenInfo?.symbol || "???") + ")\\n";
            confirmText += "<b>Address:</b> <code>" + tokenAddr.slice(0,20) + "...</code>\\n";
            confirmText += "<b>Amount:</b> " + amountSol.toFixed(4) + " SOL\\n\\n";
            
            if (tokenInfo && !tokenInfo.error) {
                confirmText += "<b>Price:</b> $" + tokenInfo.price_usd + "\\n";
                confirmText += "<b>Liquidity:</b> $" + Number(tokenInfo.liquidity || 0).toLocaleString() + "\\n";
                confirmText += "<b>24h Volume:</b> $" + Number(tokenInfo.volume_24h || 0).toLocaleString() + "\\n";
                confirmText += "<b>24h Change:</b> " + (tokenInfo.change_24h || 0) + "%\\n";
            }
            
            confirmText += "\\nProceed with swap?";
            
            await bot.sendMessage(chatId, confirmText, {
                parse_mode: "HTML",
                reply_markup: { inline_keyboard: [
                    [{ text: "CONFIRM SWAP", callback_data: "confirm_swap" }],
                    [{ text: "CANCEL", callback_data: "cancel_swap" }]
                ]}
            });
        });
        return;
    }

    await showMenu(chatId, "LUXE SOLANA WALLET");
});`;

content = content.replace(searchPattern, handlers);
fs.writeFileSync("index.js", content);
console.log("Handlers added");
