import TelegramBot from "node-telegram-bot-api";
import fs from "fs";
import bs58 from "bs58";
import { spawn } from "child_process";
import { Connection, clusterApiUrl, Keypair, PublicKey } from "@solana/web3.js";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function spawnPython(script, args = []) {
    const scriptPath = path.join(__dirname, script);
    return spawn("python3", [scriptPath, ...args], { cwd: __dirname });
}

const BOT_TOKEN = "8545374073:AAEb9WXMF_ZgmcogXCz4R2m6Ek1CJSGLp0A";
const NETWORK = "mainnet-beta";
const RPC_URL = clusterApiUrl(NETWORK);
const SOL_TO_USD_RATE = 133.93; 
const REFRESH_INTERVAL_MS = 1000; 

const userState = {};
const userPythonProcess = {};            
const userTrades = {};            
const userTargetHits = {};
const userStopLossHits = {};      
const liveMonitorIntervals = {}; 
let activeInvestQueue = []; 

const connection = new Connection(RPC_URL, {
    commitment: "confirmed",
    confirmTransactionInitialTimeout: 60000,
    wsEndpoint: RPC_URL.replace("https", "wss")
});

const bot = new TelegramBot(BOT_TOKEN, { 
    polling: {
        interval: 300,
        autoStart: true,
        params: { allowed_updates: ["message", "callback_query"] }
    } 
});

async function deleteMessageSafe(chatId, messageId) {
    if (!messageId) return; 
    try { await bot.deleteMessage(chatId, messageId); } catch (e) {}
}

async function updateStatusMessage(chatId, text, autoDeleteMs = null) {
    const state = userState[chatId];
    if (state.lastStatusMsgId) await deleteMessageSafe(chatId, state.lastStatusMsgId);
    if (state.lastPromptId) await deleteMessageSafe(chatId, state.lastPromptId);
    try {
        const sent = await bot.sendMessage(chatId, text, { parse_mode: "Markdown" });
        state.lastStatusMsgId = sent.message_id;
        state.lastPromptId = null; 
        if (autoDeleteMs) setTimeout(() => deleteMessageSafe(chatId, sent.message_id), autoDeleteMs);
    } catch (e) {}
}

async function showTradesList(chatId, page = 0) {
    let trades = userTrades[chatId] || [];
    const hits = userTargetHits[chatId] || [];
    const losses = userStopLossHits[chatId] || [];
    const soldAddresses = new Set([...hits.map(h => h.address), ...losses.map(l => l.address)]);
    trades = trades.filter(t => !soldAddresses.has(t.address));

    if (trades.length === 0) {
        const noneMsg = await bot.sendMessage(chatId, "ðŸ“Š No active trades found.", {
            reply_markup: { inline_keyboard: [[{ text: "â¬…ï¸ BACK", callback_data: "back_home" }]] }
        });
        setTimeout(() => deleteMessageSafe(chatId, noneMsg.message_id), 5000);
        return;
    }

    const CHUNK_SIZE = 10;
    const totalPages = Math.ceil(trades.length / CHUNK_SIZE);
    const start = page * CHUNK_SIZE;
    const chunk = trades.slice(start, start + CHUNK_SIZE);

    let text = `ðŸ“Š *ACTIVE TRADES (Page ${page + 1}/${totalPages})*\nTotal active pairs: ${trades.length}\n\n`;
    chunk.forEach((t, idx) => {
        text += `ðŸ”¹ *Trade #${start + idx + 1}*\n` +
                `Token: \`${t.address}\`\n` +
                `Amount: ${t.amount} SOL | Aim: ${t.target}x\n` +
                `Entered: ${t.stamp}\n\n`;
    });

    const kb = [];
    const navRow = [];
    if (page > 0) navRow.push({ text: "â¬…ï¸ PREVIOUS", callback_data: `trades_page_${page - 1}` });
    if (page < totalPages - 1) navRow.push({ text: "NEXT âž¡ï¸", callback_data: `trades_page_${page + 1}` });
    if (navRow.length > 0) kb.push(navRow);
    kb.push([{ text: "ðŸ”™ BACK TO MENU", callback_data: "back_home" }]);

    const state = userState[chatId];
    if (state.lastListPageId) await deleteMessageSafe(chatId, state.lastListPageId);
    const sent = await bot.sendMessage(chatId, text, { parse_mode: "Markdown", reply_markup: { inline_keyboard: kb } });
    state.lastListPageId = sent.message_id;
}

async function showHitsList(chatId, page = 0) {
    const hits = userTargetHits[chatId] || [];
    if (hits.length === 0) {
        const noneMsg = await bot.sendMessage(chatId, "ðŸŽ¯ No targets hit yet.", {
            reply_markup: { inline_keyboard: [[{ text: "â¬…ï¸ BACK", callback_data: "back_home" }]] }
        });
        setTimeout(() => deleteMessageSafe(chatId, noneMsg.message_id), 5000);
        return;
    }

    const CHUNK_SIZE = 15;
    const totalPages = Math.ceil(hits.length / CHUNK_SIZE);
    const start = page * CHUNK_SIZE;
    const chunk = hits.slice(start, start + CHUNK_SIZE);

    let text = `ðŸŽ¯ *TARGET HIT HISTORY (Page ${page + 1}/${totalPages})*\nTotal hits: ${hits.length}\n\n`;
    chunk.forEach((h, idx) => {
        text += `âœ… *SUCCESS #${start + idx + 1}*\n` +
                `Address: \`${h.address}\`\n` +
                `Target: ${h.target}x | Time: ${h.time}\n\n`;
    });

    const kb = [];
    const navRow = [];
    if (page > 0) navRow.push({ text: "â¬…ï¸ PREVIOUS", callback_data: `hits_page_${page - 1}` });
    if (page < totalPages - 1) navRow.push({ text: "NEXT âž¡ï¸", callback_data: `hits_page_${page + 1}` });
    if (navRow.length > 0) kb.push(navRow);
    kb.push([{ text: "ðŸ”™ BACK TO MENU", callback_data: "back_home" }]);

    const state = userState[chatId];
    if (state.lastListPageId) await deleteMessageSafe(chatId, state.lastListPageId);
    const sent = await bot.sendMessage(chatId, text, { parse_mode: "Markdown", reply_markup: { inline_keyboard: kb } });
    state.lastListPageId = sent.message_id;
}

async function showStopLossList(chatId, page = 0) {
    const losses = userStopLossHits[chatId] || [];
    if (losses.length === 0) {
        const noneMsg = await bot.sendMessage(chatId, "ðŸ“‰ No stop losses triggered yet.", {
            reply_markup: { inline_keyboard: [[{ text: "â¬…ï¸ BACK", callback_data: "back_home" }]] }
        });
        setTimeout(() => deleteMessageSafe(chatId, noneMsg.message_id), 5000);
        return;
    }

    const CHUNK_SIZE = 15;
    const totalPages = Math.ceil(losses.length / CHUNK_SIZE);
    const start = page * CHUNK_SIZE;
    const chunk = losses.slice(start, start + CHUNK_SIZE);

    let text = `ðŸ“‰ *STOP LOSS HISTORY (Page ${page + 1}/${totalPages})*\nTotal stop losses: ${losses.length}\n\n`;
    chunk.forEach((l, idx) => {
        text += `ðŸš¨ *EXIT #${start + idx + 1}*\n` +
                `Address: \`${l.address}\`\n` +
                `Amount: ${l.amount} SOL | Time: ${l.time}\n\n`;
    });

    const kb = [];
    const navRow = [];
    if (page > 0) navRow.push({ text: "â¬…ï¸ PREVIOUS", callback_data: `losses_page_${page - 1}` });
    if (page < totalPages - 1) navRow.push({ text: "NEXT âž¡ï¸", callback_data: `losses_page_${page + 1}` });
    if (navRow.length > 0) kb.push(navRow);
    kb.push([{ text: "ðŸ”™ BACK TO MENU", callback_data: "back_home" }]);

    const state = userState[chatId];
    if (state.lastListPageId) await deleteMessageSafe(chatId, state.lastListPageId);
    const sent = await bot.sendMessage(chatId, text, { parse_mode: "Markdown", reply_markup: { inline_keyboard: kb } });
    state.lastListPageId = sent.message_id;
}

async function showSellBackList(chatId, page = 0) {
    const trades = userTrades[chatId] || [];
    if (trades.length === 0) {
        const noneMsg = await bot.sendMessage(chatId, "ðŸ“Š No active trades found.", {
            reply_markup: { inline_keyboard: [[{ text: "â¬…ï¸ BACK", callback_data: "back_home" }]] }
        });
        setTimeout(() => deleteMessageSafe(chatId, noneMsg.message_id), 5000);
        return;
    }

    const CHUNK_SIZE = 100;
    const totalPages = Math.ceil(trades.length / CHUNK_SIZE);
    const start = page * CHUNK_SIZE;
    const chunk = trades.slice(start, start + CHUNK_SIZE);

    const btns = chunk.map((t, idx) => ([{ 
        text: `ðŸ’° SELL [${start + idx + 1}] ${t.address.slice(0, 12)}...`, 
        callback_data: `conf_sell_${start + idx}` 
    }]));

    const kb = [...btns];
    const navRow = [];
    if (page > 0) navRow.push({ text: "â¬…ï¸ PREVIOUS", callback_data: `sellback_page_${page - 1}` });
    if (page < totalPages - 1) navRow.push({ text: "NEXT âž¡ï¸", callback_data: `sellback_page_${page + 1}` });
    if (navRow.length > 0) kb.push(navRow);
    kb.push([{ text: "ðŸ”™ BACK TO MENU", callback_data: "back_home" }]);

    const pageText = totalPages > 1 ? ` (Page ${page + 1}/${totalPages})` : "";
    const state = userState[chatId];
    if (state.lastListPageId) await deleteMessageSafe(chatId, state.lastListPageId);
    const sent = await bot.sendMessage(chatId, `ðŸ’° *SELECT TOKEN TO SELL BACK*${pageText}\nTotal active pairs: ${trades.length}`, { 
        parse_mode: "Markdown", 
        reply_markup: { inline_keyboard: kb } 
    });
    state.lastListPageId = sent.message_id;
}

const solFromLamports = (l) => Number((l / 1e9).toFixed(6));
const solDisplay = (s) => s.toFixed(6);
const usdDisplay = (s) => (s * SOL_TO_USD_RATE).toFixed(2);
const shortAddress = (a) => a?.length > 12 ? a.slice(0, 6) + "..." + a.slice(-6) : a;
const getTimestamp = () => new Date().toLocaleTimeString();

async function runLiveMonitor(chatId) {
    if (liveMonitorIntervals[chatId]) clearInterval(liveMonitorIntervals[chatId]);
    liveMonitorIntervals[chatId] = setInterval(async () => {
        const state = userState[chatId];
        if (!state || !state.connected || !state.walletAddress || !state.lastMenuMsgId) {
            clearInterval(liveMonitorIntervals[chatId]);
            return;
        }
        try {
            const pubKey = new PublicKey(state.walletAddress);
            const balanceLamports = await connection.getBalance(pubKey);
            const solNum = solFromLamports(balanceLamports);
            const solText = `${solDisplay(solNum)} SOL`;
            const usdText = `$${usdDisplay(solNum)}`;
            const combined = `${solText} | ${usdText}`;
            if (state.lastBalanceText !== combined) {
                state.lastBalanceText = combined;
                const body = "ðŸ‘‘ *LUXE SOLANA WALLET* ðŸ‘‘\n\nðŸŸ¢ *Connected* â€” `" + state.walletAddress + "`\n\nðŸŸ¡ *Live Balance:* " + combined + "\nðŸ•’ _Updated: " + getTimestamp() + "_";
                await bot.editMessageText(body, {
                    chat_id: chatId,
                    message_id: state.lastMenuMsgId,
                    parse_mode: "Markdown",
                    reply_markup: premiumMenu({ connected: true, balanceText: combined, chatId })
                }).catch(() => {});
            }
        } catch (error) {}
    }, REFRESH_INTERVAL_MS);
}

function premiumMenu({ connected = false, balanceText = null, chatId = null } = {}) {
    const PAD_WIDTH = 48;
    const state = userState[chatId] || {};
    const isUserInQueue = activeInvestQueue.includes(chatId);

    const labels = {
        connect: (connected ? "ðŸŸ¢    CONNECTED (WALLET ACTIVE)    " : "ðŸ”‘    CONNECT YOUR WALLET    ").padEnd(PAD_WIDTH, " "),
        balance: (balanceText ? "ðŸŸ¡    BALANCE â€” " + balanceText + "    " : "ðŸŸ¡    BALANCE    ").padEnd(PAD_WIDTH, " "),
        invest: (isUserInQueue ? "ðŸŸ¥    STOP INVESTMENT BOT    " : "ðŸ›¡ï¸    START INVESTMENT BOT    ").padEnd(PAD_WIDTH, " "),
        trades: "ðŸ“Š    TRADES    ".padEnd(PAD_WIDTH, " "),
        sell: "ðŸ’°    SELL BACK    ".padEnd(PAD_WIDTH, " "),
        panic: "ðŸ“‰    PANIC SELL ALL    ".padEnd(PAD_WIDTH, " "),
        transfer: "ðŸ’¸    TRANSFER SOL    ".padEnd(PAD_WIDTH, " "),
        swap: "ðŸ”„    SWAP NOW    ".padEnd(PAD_WIDTH, " "),
        analyse: "ðŸ”Ž    ANALYSE TOKEN    ".padEnd(PAD_WIDTH, " "),
        search: "ðŸ”Ž    SEARCH TOKEN    ".padEnd(PAD_WIDTH, " "),
        verify: "ðŸ›¡ï¸    VERIFY DEV RUG    ".padEnd(PAD_WIDTH, " ")
    };

    const lastHit = userTargetHits[chatId]?.length > 0 ? userTargetHits[chatId][userTargetHits[chatId].length - 1].address : null;
    const targetHitLabel = (lastHit ? "ðŸŽ¯    HIT: " + shortAddress(lastHit) : "ðŸŽ¯    TARGET HIT    ").padEnd(PAD_WIDTH, " ");

    const lastStopLoss = userStopLossHits[chatId]?.length > 0 ? userStopLossHits[chatId][userStopLossHits[chatId].length - 1].address : null;
    const stopLossLabel = (lastStopLoss ? "ðŸ“‰    LOSS: " + shortAddress(lastStopLoss) : "ðŸ“‰    STOP LOSS HIT    ").padEnd(PAD_WIDTH, " ");

    const targetMultiplierLabel = (state.targetMultiplier ? "ðŸŽ¯    TARGET SET TO " + state.targetMultiplier + "x    " : "ðŸŽ¯    SET TARGET    ").padEnd(PAD_WIDTH, " ");
    const buyAmountLabel = (state.buyAmount ? "ðŸ’°    AMOUNT SET TO " + state.buyAmount + " SOL    " : "ðŸ’°    SET AMOUNT    ").padEnd(PAD_WIDTH, " ");

    const keyboard = [
        [{ text: labels.connect, callback_data: "connect_wallet" }],
        [{ text: labels.balance, callback_data: "balance" }],
        [{ text: labels.transfer, callback_data: "transfer_sol" }],
        [{ text: labels.swap, callback_data: "swap_now" }],
        [{ text: labels.invest, callback_data: "invest" }],
        [{ text: labels.trades, callback_data: "trades" }],
        [{ text: labels.sell, callback_data: "sell_back_list" }],
        [{ text: labels.panic, callback_data: "panic_sell" }], 
        [{ text: labels.analyse, callback_data: "analyse_token" }],
        [{ text: labels.search, callback_data: "search_token" }],
        [{ text: labels.verify, callback_data: "verify_rug" }],
        [{ text: targetHitLabel, callback_data: "target_hit" }],
        [{ text: stopLossLabel, callback_data: "stop_loss_hit" }],
        [{ text: targetMultiplierLabel, callback_data: "set_target" }],
        [{ text: buyAmountLabel, callback_data: "set_amount" }]
    ];

    if (connected) keyboard.push([{ text: "âŒ    DISCONNECT WALLET    ".padEnd(PAD_WIDTH, " "), callback_data: "disconnect" }]);
    return { inline_keyboard: keyboard };
}

async function clearChatExceptCurrent(chatId) {
    if (!userState[chatId]) return;
    const state = userState[chatId];
    if (state.lastStatusMsgId) { await deleteMessageSafe(chatId, state.lastStatusMsgId); state.lastStatusMsgId = null; }
    if (state.lastPromptId) { await deleteMessageSafe(chatId, state.lastPromptId); state.lastPromptId = null; }
    if (state.lastMenuMsgId) { 
        await deleteMessageSafe(chatId, state.lastMenuMsgId); 
        state.lastMenuMsgId = null; 
    }
}

async function showMenu(chatId, bodyText) {
    if (!userState[chatId]) userState[chatId] = { connected: false };
    const state = userState[chatId];
    await clearChatExceptCurrent(chatId);

    const opts = {
        parse_mode: "Markdown",
        reply_markup: premiumMenu({ connected: state.connected, balanceText: state.lastBalanceText, chatId })
    };
    
    try {
        const sent = await bot.sendMessage(chatId, bodyText, opts);
        state.lastMenuMsgId = sent.message_id;
    } catch (e) {}
    if (state.connected) runLiveMonitor(chatId);
}

async function showResult(chatId, text) {
    const state = userState[chatId];
    await clearChatExceptCurrent(chatId);

    const sent = await bot.sendMessage(chatId, text, {
        parse_mode: "Markdown",
        reply_markup: { inline_keyboard: [[{ text: "ðŸ”™ BACK TO MENU", callback_data: "back_home" }]] }
    });
    state.lastPromptId = sent.message_id;
}

bot.onText(/\/start/, async (msg) => {
    const chatId = msg.chat.id;
    await deleteMessageSafe(chatId, msg.message_id);
    if (!userState[chatId]) {
        userState[chatId] = { connected: false, walletAddress: null, keypair: null, lastMenuMsgId: null, lastPromptId: null, lastStatusMsgId: null, lastBalanceText: null, targetMultiplier: null, buyAmount: null };
        userTrades[chatId] = [];
        userTargetHits[chatId] = [];
        userStopLossHits[chatId] = [];
    }
    showMenu(chatId, "ðŸ‘‘ *LUXE SOLANA WALLET* ðŸ‘‘\n\nYour premium gateway to Solana & Pump.fun.\n\nSelect an option below to begin:");
});

bot.on("callback_query", async (query) => {
    const chatId = query.message.chat.id;
    const data = query.data;
    if (!userState[chatId]) userState[chatId] = { connected: false };
    const state = userState[chatId];

    if (query.message && query.message.message_id) {
        await deleteMessageSafe(chatId, query.message.message_id);
        if (state.lastMenuMsgId === query.message.message_id) state.lastMenuMsgId = null;
        if (state.lastPromptId === query.message.message_id) state.lastPromptId = null;
    }
    await clearChatExceptCurrent(chatId);

    if (data === "sell_back_list") {
        const trades = userTrades[chatId] || [];
        if (trades.length === 0) {
            const noneMsg = await bot.sendMessage(chatId, "ðŸ“Š No active trades found.", { 
                reply_markup: { inline_keyboard: [[{ text: "â¬…ï¸ BACK", callback_data: "back_home" }]] } 
            });
            state.lastPromptId = noneMsg.message_id; 
            setTimeout(() => deleteMessageSafe(chatId, noneMsg.message_id), 5000);
            return;
        }

        const CHUNK_SIZE = 10;
        const totalChunks = Math.ceil(trades.length / CHUNK_SIZE);
        
        for (let i = 0; i < trades.length; i += CHUNK_SIZE) {
            const chunk = trades.slice(i, i + CHUNK_SIZE);
            const btns = chunk.map((t, idx) => ([{ 
                text: `ðŸ’° SELL [${i + idx + 1}] ${t.address.slice(0, 12)}...`, 
                callback_data: `conf_sell_${i + idx}` 
            }]));
            
            const isLast = (i + CHUNK_SIZE) >= trades.length;
            if (isLast) {
                btns.push([{ text: "â¬…ï¸ BACK", callback_data: "back_home" }]);
            }

            const pageText = totalChunks > 1 ? ` (Page ${Math.floor(i / CHUNK_SIZE) + 1}/${totalChunks})` : "";
            const sent = await bot.sendMessage(chatId, `ðŸ’° *SELECT TOKEN TO SELL BACK*${pageText}\nTotal active pairs: ${trades.length}`, { 
                parse_mode: "Markdown", 
                reply_markup: { inline_keyboard: btns } 
            });
            state.lastPromptId = sent.message_id;
        }
        return;
    }

    if (data.startsWith("conf_sell_")) {
        const idx = data.split("_")[2];
        const trade = userTrades[chatId][idx];
        const confirmKb = { inline_keyboard: [[{ text: "âœ… CONFIRM SELL", callback_data: `exec_sell_${idx}` }], [{ text: "âŒ CANCEL", callback_data: "sell_back_list" }]] };
        return bot.sendMessage(chatId, `âš ï¸ *CONFIRM SELL*\n\nToken: \`${trade.address}\`\nExecute Sell Back?`, { parse_mode: "Markdown", reply_markup: confirmKb });
    }

    if (data.startsWith("exec_sell_")) {
        const idx = data.split("_")[2];
        const trade = userTrades[chatId][idx];
        const secret = bs58.encode(Array.from(state.keypair.secretKey));

        await updateStatusMessage(chatId, "ðŸš€ *EXECUTING SELL BACK...*");

        const signatures = [];
        const proc = spawnPython("execute_sell.py", [secret, trade.address]);

        proc.stdout.on("data", (d) => { 
            const output = d.toString();
            const sigMatch = output.match(/(?:Signature|TX|Hash):\s*([A-Za-z0-9]{32,88})/i);
            if (sigMatch) signatures.push(sigMatch[1]);
        });

        proc.on("close", async () => {
            userTrades[chatId].splice(idx, 1);
            let report = "âœ… *SELL COMPLETE*";
            if (signatures.length > 0) {
                report += `\n\nðŸ”— [View Transaction](https://solscan.io/tx/${signatures[0]})`;
            }

            const resMsg = await bot.sendMessage(chatId, report, { 
                parse_mode: "Markdown", 
                disable_web_page_preview: true 
            });

            setTimeout(() => deleteMessageSafe(chatId, resMsg.message_id), 10000);
            showMenu(chatId, "ðŸ‘‘ *LUXE SOLANA WALLET* ðŸ‘‘");
        });
        return;
    }

    if (data === "panic_sell") {
        const trades = userTrades[chatId] || [];
        if (trades.length === 0) {
            const noneMsg = await bot.sendMessage(chatId, "âŒ No active trades found.");
            setTimeout(() => deleteMessageSafe(chatId, noneMsg.message_id), 5000);
            return showMenu(chatId, "ðŸ‘‘ *LUXE SOLANA WALLET* ðŸ‘‘");
        }

        await updateStatusMessage(chatId, `ðŸš¨ *PANIC SELL INITIATED* ðŸš¨\nSelling ${trades.length} tokens...`);

        const pk = bs58.encode(Array.from(state.keypair.secretKey));
        const signatures = [];
        let completed = 0;

        for (let i = 0; i < trades.length; i++) {
            const tokenAddr = trades[i].address;
            if (i > 0) await new Promise(r => setTimeout(r, 1000)); 

            const proc = spawnPython("execute_sell.py", [pk, tokenAddr]);

            proc.stdout.on("data", (data) => {
                const output = data.toString();
                const sigMatch = output.match(/(?:Signature|TX|Hash):\s*([A-Za-z0-9]{32,88})/i);
                if (sigMatch) signatures.push({ addr: tokenAddr, sig: sigMatch[1] });
            });

            proc.on("close", async () => {
                completed++;
                if (completed === trades.length) {
                    let report = "âœ… *PANIC SELL COMPLETE*\n\n";
                    if (signatures.length > 0) {
                        signatures.forEach((s, idx) => {
                            report += `ðŸ”¹ \`${s.addr.slice(0, 6)}...\` -> [View TX](https://solscan.io/tx/${s.sig})\n`;
                        });
                    }
                    const resMsg = await bot.sendMessage(chatId, report, { parse_mode: "Markdown", disable_web_page_preview: true });
                    setTimeout(() => deleteMessageSafe(chatId, resMsg.message_id), 15000);
                    userTrades[chatId] = [];
                    return showMenu(chatId, "ðŸ‘‘ *LUXE SOLANA WALLET* ðŸ‘‘");
                }
            });
        }
        return;
    }

    if (data === "invest") {
        if (!state.connected || !state.keypair) {
            await updateStatusMessage(chatId, "âŒ Please connect your wallet first.", 5000);
            return;
        }

        if (!activeInvestQueue.includes(chatId)) {
            activeInvestQueue.push(chatId);
            if (!state.targetMultiplier) state.targetMultiplier = 2.0;
            if (!state.buyAmount) state.buyAmount = 0.001;

            // Update active users file for Python bot
            const activeUsers = activeInvestQueue.map(id => ({
                chatId: id,
                secret: bs58.encode(Array.from(userState[id].keypair.secretKey)),
                buyAmount: userState[id].buyAmount || 0.001,
                target: userState[id].targetMultiplier || 2.0
            }));
            fs.writeFileSync(path.join(__dirname, "active_users.json"), JSON.stringify(activeUsers, null, 2));

            const secretBase58 = bs58.encode(Array.from(state.keypair.secretKey));
            const pyProc = spawn("python3", [path.join(__dirname, "bot.py"), secretBase58, String(state.targetMultiplier), String(state.buyAmount)], { 
                cwd: __dirname,
                env: { ...process.env, PYTHONUNBUFFERED: "1" } 
            });
            userPythonProcess[chatId] = pyProc;

            pyProc.stdout.on("data", async (d) => {
                const str = d.toString();
                console.log(`[Bot Output]: ${str}`);

                // Improved Buy Detection
                const buyMatch = str.match(/(?:BUYING|OPPORTUNITY BOUGHT)\s*[:\s]*([A-Za-z0-9]{32,44})/i);
                if (buyMatch) {
                    const addr = buyMatch[1].trim();
                    if (!userTrades[chatId]) userTrades[chatId] = [];
                    if (!userTrades[chatId].some(t => t.address === addr)) {
                        userTrades[chatId].push({ 
                            address: addr, 
                            amount: state.buyAmount || 0.001, 
                            target: state.targetMultiplier || 2.0, 
                            stamp: getTimestamp() 
                        });
                        await updateStatusMessage(chatId, `ðŸš€ *OPPORTUNITY BOUGHT*\nAddr: \`${addr}\``, 15000);
                    }
                }

                if (str.includes("EMERGENCY EXIT TRIGGERED") || (str.includes("SELLING") && str.includes("EMERGENCY EXIT"))) {
                    const match = str.match(/(?:EMERGENCY EXIT TRIGGERED:|SELLING)\s*([A-Za-z0-9]{32,44})/);
                    const addr = match ? match[1] : "Unknown";
                    if (addr !== "Unknown") {
                        if (!userStopLossHits[chatId]) userStopLossHits[chatId] = [];
                        userStopLossHits[chatId].push({ address: addr, amount: state.buyAmount || "Unknown", time: getTimestamp() });
                    }
                }

                if (str.includes("TARGET HIT") || (str.includes("SELLING") && str.includes("TARGET HIT"))) {
                    const match = str.match(/(?:TARGET HIT:|SELLING)\s*([A-Za-z0-9]{32,44})/);
                    const addr = match ? match[1] : "Unknown";
                    if (addr !== "Unknown") {
                        if (!userTargetHits[chatId]) userTargetHits[chatId] = [];
                        userTargetHits[chatId].push({ address: addr, target: state.targetMultiplier || "Unknown", time: getTimestamp() });
                    }
                }

                if (str.toLowerCase().includes("started") || str.toLowerCase().includes("scanning")) {
                    await updateStatusMessage(chatId, "ðŸ” *Bot is now scanning for tokens...*", 5000);
                }
            });

            await updateStatusMessage(chatId, "â–¶ï¸ Bot Started. Investment Queue Active.", 5000);
        } else {
            activeInvestQueue = activeInvestQueue.filter(id => id !== chatId);
            
            // Update active users file
            const activeUsers = activeInvestQueue.map(id => ({
                chatId: id,
                secret: bs58.encode(Array.from(userState[id].keypair.secretKey)),
                buyAmount: userState[id].buyAmount || 0.001,
                target: userState[id].targetMultiplier || 2.0
            }));
            fs.writeFileSync(path.join(__dirname, "active_users.json"), JSON.stringify(activeUsers, null, 2));

            if (userPythonProcess[chatId]) {
                userPythonProcess[chatId].kill("SIGTERM");
                delete userPythonProcess[chatId];
            }
            await updateStatusMessage(chatId, "ðŸ›‘ Bot Stopped. Removed from Queue.", 5000);
        }
        await showMenu(chatId, "ðŸ‘‘ *LUXE SOLANA WALLET* ðŸ‘‘");
        return;
    }

    if (data.startsWith("trades_page_")) {
        const page = parseInt(data.split("_")[2]);
        return showTradesList(chatId, page);
    }
    if (data.startsWith("hits_page_")) {
        const page = parseInt(data.split("_")[2]);
        return showHitsList(chatId, page);
    }
    if (data.startsWith("losses_page_")) {
        const page = parseInt(data.split("_")[2]);
        return showStopLossList(chatId, page);
    }
    if (data.startsWith("sellback_page_")) {
        const page = parseInt(data.split("_")[2]);
        return showSellBackList(chatId, page);
    }

    if (data === "trades") {
        return showTradesList(chatId, 0);
    }
    if (data === "target_hit") {
        return showHitsList(chatId, 0);
    }
    if (data === "stop_loss_hit") {
        return showStopLossList(chatId, 0);
    }

    if (data === "set_target") {
        await clearChatExceptCurrent(chatId);
        state.awaitingTarget = true;
        const sent = await bot.sendMessage(chatId, "ðŸŽ¯ *Enter target multiplier* (e.g., 2 for 2x):", { parse_mode: "Markdown", reply_markup: { inline_keyboard: [[{ text: "ðŸ”™ BACK", callback_data: "back_home" }]] } });
        state.lastPromptId = sent.message_id;
        return;
    }

    if (data === "set_amount") {
        await clearChatExceptCurrent(chatId);
        state.awaitingAmount = true;
        const sent = await bot.sendMessage(chatId, "ðŸ’° *Enter buy amount in SOL* (e.g., 0.1):", { parse_mode: "Markdown", reply_markup: { inline_keyboard: [[{ text: "ðŸ”™ BACK", callback_data: "back_home" }]] } });
        state.lastPromptId = sent.message_id;
        return;
    }

    if (data === "back_home" || data === "refresh") {
        await showMenu(chatId, "ðŸ‘‘ *LUXE SOLANA WALLET* ðŸ‘‘");
    } else {
        if (state.lastMenuMsgId) {
            await deleteMessageSafe(chatId, state.lastMenuMsgId);
            state.lastMenuMsgId = null;
        }

        if (data === "connect_wallet") {
            const sent = await bot.sendMessage(chatId, "ðŸ”‘ *Please enter your Solana Private Key (or Mnemonic):*", { parse_mode: "Markdown", reply_markup: { inline_keyboard: [[{ text: "âŒ CANCEL", callback_data: "back_home" }]] } });
            state.lastPromptId = sent.message_id;
            state.awaitingKey = true;
        } else if (data === "search_token") {
            const sent = await bot.sendMessage(chatId, "ðŸ”Ž *Enter keyword or Address to SEARCH:*", { parse_mode: "Markdown", reply_markup: { inline_keyboard: [[{ text: "ðŸ”™ BACK", callback_data: "back_home" }]] } });
            state.lastPromptId = sent.message_id;
            state.awaitingSearchInput = true;
        } else if (data === "verify_rug") {
            const sent = await bot.sendMessage(chatId, "ðŸ›¡ï¸ *Enter Token Address to VERIFY DEV RUG:*", { parse_mode: "Markdown", reply_markup: { inline_keyboard: [[{ text: "ðŸ”™ BACK", callback_data: "back_home" }]] } });
            state.lastPromptId = sent.message_id;
            state.awaitingVerifyInput = true;
        } else if (data === "transfer_sol") {
            if (!state.connected) return updateStatusMessage(chatId, "âŒ Connect wallet first.", 5000);
            const sent = await bot.sendMessage(chatId, "ðŸ’¸ *Enter Destination Wallet Address:*", { parse_mode: "Markdown", reply_markup: { inline_keyboard: [[{ text: "ðŸ”™ BACK", callback_data: "back_home" }]] } });
            state.lastPromptId = sent.message_id;
            state.awaitingTransferAddress = true;
        } else if (data === "analyse_token") {
            const sent = await bot.sendMessage(chatId, "ðŸ”Ž *Enter Token Address to ANALYSE:*", { parse_mode: "Markdown", reply_markup: { inline_keyboard: [[{ text: "ðŸ”™ BACK", callback_data: "back_home" }]] } });
            state.lastPromptId = sent.message_id;
            state.awaitingAnalyseInput = true;
        } else if (data === "swap_now") {
            if (!state.connected) return updateStatusMessage(chatId, "âŒ Connect wallet first.", 5000);
            const sent = await bot.sendMessage(chatId, "ðŸ”„ *Enter Token Address to SWAP NOW:*", { parse_mode: "Markdown", reply_markup: { inline_keyboard: [[{ text: "ðŸ”™ BACK", callback_data: "back_home" }]] } });
            state.lastPromptId = sent.message_id;
            state.awaitingSwapAddress = true;
        } else if (data === "disconnect") {
            state.connected = false; state.walletAddress = null; state.keypair = null;
            if (liveMonitorIntervals[chatId]) clearInterval(liveMonitorIntervals[chatId]);
            await showMenu(chatId, "ðŸ‘‘ *LUXE SOLANA WALLET* ðŸ‘‘\n\nWallet disconnected.");
        } else if (data.startsWith("confirm_swap_")) {
            const parts = data.split("_");
            const token = parts[2];
            const amount = parts[3];
            await updateStatusMessage(chatId, "ðŸš€ Executing Swap for " + amount + " SOL...");
            const secret = bs58.encode(Array.from(state.keypair.secretKey));
            const proc = spawnPython("swap.py", [secret, token, amount]);
            let output = "";
            proc.stdout.on("data", (d) => output += d.toString());
            proc.on("close", async () => {
                await showResult(chatId, "âœ… *Swap Process Finished*\n\n" + (output || "Success"));
            });
        }
    }
    
    bot.answerCallbackQuery(query.id).catch(() => {});
});

bot.on("message", async (msg) => {
    if (!msg.text || msg.text.startsWith("/")) return;
    const chatId = msg.chat.id;
    const text = msg.text.trim();
    if (!userState[chatId]) userState[chatId] = { connected: false };
    const state = userState[chatId];

    await deleteMessageSafe(chatId, msg.message_id);

    if (state.awaitingKey) {
        state.awaitingKey = false;
        if (text.split(" ").length >= 12) {
            await updateStatusMessage(chatId, "â³ Syncing with Trust Wallet...");
            const pySync = spawnPython("wallet_sync.py", [text]);
            let pyOutput = "";
            pySync.stdout.on("data", (d) => pyOutput += d.toString());
            pySync.on("close", async () => {
                const lines = pyOutput.split("\n");
                const addr = lines.find(l => l.includes("ADDR") || l.includes("ADDRESS"))?.split(":")[1]?.trim();
                const secret = lines.find(l => l.includes("PKEY") || l.includes("SECRET"))?.split(":")[1]?.trim();
                if (addr && secret) {
                    state.connected = true; state.walletAddress = addr;
                    state.keypair = Keypair.fromSecretKey(new Uint8Array(bs58.decode(secret)));
                    await showMenu(chatId, "âœ… *WALLET SYNCED*\n\nAddress: `" + addr + "`");
                } else {
                    await updateStatusMessage(chatId, "âŒ Sync Failed. Check your mnemonic.", 5000);
                    await showMenu(chatId, "ðŸ‘‘ *LUXE SOLANA WALLET* ðŸ‘‘");
                }
            });
        } else {
            try {
                const decoded = bs58.decode(text);
                const kp = Keypair.fromSecretKey(new Uint8Array(decoded));
                state.keypair = kp;
                state.walletAddress = kp.publicKey.toBase58();
                state.connected = true;
                await showMenu(chatId, "âœ… *WALLET CONNECTED*\n\nAddress: `" + state.walletAddress + "`");
            } catch (e) {
                const sent = await bot.sendMessage(chatId, "âŒ *Invalid Key.* Please try again:", { parse_mode: "Markdown", reply_markup: { inline_keyboard: [[{ text: "âŒ CANCEL", callback_data: "back_home" }]] } });
                state.lastPromptId = sent.message_id;
                state.awaitingKey = true;
            }
        }
    } else if (state.awaitingTarget) {
        state.awaitingTarget = false;
        const val = parseFloat(text);
        if (!isNaN(val) && val > 0) {
            state.targetMultiplier = val;
            await updateStatusMessage(chatId, `ðŸŽ¯ Target set to ${val}x`, 5000);
        } else {
            await updateStatusMessage(chatId, "âŒ Invalid multiplier.", 5000);
        }
        await showMenu(chatId, "ðŸ‘‘ *LUXE SOLANA WALLET* ðŸ‘‘");
    } else if (state.awaitingAmount) {
        state.awaitingAmount = false;
        const val = parseFloat(text);
        if (!isNaN(val) && val > 0) {
            state.buyAmount = val;
            await updateStatusMessage(chatId, `ðŸ’° Amount set to ${val} SOL`, 5000);
        } else {
            await updateStatusMessage(chatId, "âŒ Invalid amount.", 5000);
        }
        await showMenu(chatId, "ðŸ‘‘ *LUXE SOLANA WALLET* ðŸ‘‘");
    } else if (state.awaitingSearchInput) {
        state.awaitingSearchInput = false;
        if (state.lastPromptId) await deleteMessageSafe(chatId, state.lastPromptId);
        await updateStatusMessage(chatId, "ðŸ”Ž Searching for " + text + "...");
        const proc = spawnPython("search_token.py", [text]);
        let output = "";
        proc.stdout.on("data", (d) => output += d.toString());
        proc.on("close", async () => {
            await showResult(chatId, "ðŸ”Ž *Search Result:*\n\n" + (output || "No data found"));
        });
    } else if (state.awaitingVerifyInput) {
        state.awaitingVerifyInput = false;
        if (state.lastPromptId) await deleteMessageSafe(chatId, state.lastPromptId);
        await updateStatusMessage(chatId, "ðŸ›¡ï¸ Checking " + text + "...");
        const proc = spawnPython("verify_rug.py", [text]);
        let output = "";
        proc.stdout.on("data", (d) => output += d.toString());
        proc.on("close", async () => {
            await showResult(chatId, "ðŸ›¡ï¸ *Rug Check Result:*\n\n" + (output || "Analysis failed"));
        });
    } else if (state.awaitingAnalyseInput) {
        state.awaitingAnalyseInput = false;
        if (state.lastPromptId) await deleteMessageSafe(chatId, state.lastPromptId);
        await updateStatusMessage(chatId, "ðŸ”Ž Analysing " + text + "...");
        const proc = spawnPython("analysis.py", [text]);
        let output = "";
        proc.stdout.on("data", (d) => output += d.toString());
        proc.on("close", async () => {
            await showResult(chatId, "ðŸ”Ž *Analysis Result:*\n\n" + (output || "Analysis failed"));
        });
    } else if (state.awaitingTransferAddress) {
        state.awaitingTransferAddress = false;
        state.pendingTransferTo = text;
        state.awaitingTransferAmount = true;
        if (state.lastPromptId) await deleteMessageSafe(chatId, state.lastPromptId);
        const sent = await bot.sendMessage(chatId, "ðŸ’° *Enter amount of SOL to transfer:*", { parse_mode: "Markdown", reply_markup: { inline_keyboard: [[{ text: "ðŸ”™ BACK", callback_data: "back_home" }]] } });
        state.lastPromptId = sent.message_id;
    } else if (state.awaitingTransferAmount) {
        state.awaitingTransferAmount = false;
        await updateStatusMessage(chatId, "ðŸ’¸ Transferring " + text + " SOL...");
        const secret = bs58.encode(Array.from(state.keypair.secretKey));
        const proc = spawnPython("transfer.py", [secret, state.pendingTransferTo, text]);
        let output = "";
        proc.stdout.on("data", (d) => output += d.toString());
        proc.on("close", async () => {
            await showResult(chatId, "ðŸ“¤ *Transfer Result:*\n\n" + (output || "Transaction failed"));
        });
    } else if (state.awaitingSwapAddress) {
        state.awaitingSwapAddress = false;
        state.pendingSwapToken = text;
        state.awaitingSwapAmount = true;
        if (state.lastPromptId) await deleteMessageSafe(chatId, state.lastPromptId);
        const sent = await bot.sendMessage(chatId, "ðŸ’° *Enter amount of SOL to swap:*", { parse_mode: "Markdown", reply_markup: { inline_keyboard: [[{ text: "ðŸ”™ BACK", callback_data: "back_home" }]] } });
        state.lastPromptId = sent.message_id;
    } else if (state.awaitingSwapAmount) {
        state.awaitingSwapAmount = false;
        const info = "ðŸ”„ *CONFIRM SWAP*\n\nToken: `" + state.pendingSwapToken + "`\nAmount: " + text + " SOL";
        if (state.lastPromptId) await deleteMessageSafe(chatId, state.lastPromptId);
        const sent = await bot.sendMessage(chatId, info, { 
            parse_mode: "Markdown", 
            reply_markup: { 
                inline_keyboard: [
                    [{ text: "âœ… CONFIRM SWAP", callback_data: "confirm_swap_" + state.pendingSwapToken + "_" + text }], 
                    [{ text: "ðŸ”™ BACK TO MENU", callback_data: "back_home" }]
                ] 
            } 
        });
        state.lastPromptId = sent.message_id;
    }
});

console.log("ðŸ’Ž LUXE SOLANA BOT V6.0 STARTED");
