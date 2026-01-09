/**
 * ==============================================================================
 * 👑 LUXE SOLANA WALLET BOT — PREMIUM PRODUCTION MANIFEST
 * ==============================================================================
 */
import express from 'express';
import TelegramBot from "node-telegram-bot-api";
import fs from "fs";
import bs58 from "bs58";
import { spawn } from "child_process";
import { Connection, clusterApiUrl, Keypair, PublicKey } from "@solana/web3.js";

// ------------------------------------------------------------------------------
// ⚙️ SYSTEM CONFIGURATION
// ------------------------------------------------------------------------------
const app = express();
const port = process.env.PORT || 10000;

app.get('/', (req, res) => res.send('Bot is Alive!'));
app.listen(port, '0.0.0.0', () => {
    console.log(`Web health check listening on port ${port}`);
});

const BOT_TOKEN = process.env.TELEGRAM_TOKEN || "8289553678:AAFstnW9Am5LNvU0TyLc00AWVaOaFWyYSxA";
const RPC_URL = clusterApiUrl("mainnet-beta");
const SOL_TO_USD_RATE = 133.93; 

// ------------------------------------------------------------------------------
// 💾 GLOBAL MEMORY
// ------------------------------------------------------------------------------
const userState = {};
const userPythonProcess = {};            
const userTrades = {};            
const userTargetHits = {};      
const liveMonitorIntervals = {}; 
let activeInvestQueue = []; 

const connection = new Connection(RPC_URL, { commitment: "confirmed" });

// Updated polling logic to help resolve the 409 Conflict error
const bot = new TelegramBot(BOT_TOKEN, { 
    polling: {
        params: {
            timeout: 10
        }
    } 
});

// ------------------------------------------------------------------------------
// 🛠️ UTILITIES
// ------------------------------------------------------------------------------
async function deleteMessageSafe(chatId, messageId) {
    if (!messageId) return; 
    try { await bot.deleteMessage(chatId, messageId); } catch (e) {}
}

async function updateStatusMessage(chatId, text, autoDeleteMs = null) {
    const state = userState[chatId] || {};
    if (state.lastStatusMsgId) await deleteMessageSafe(chatId, state.lastStatusMsgId);
    try {
        const sent = await bot.sendMessage(chatId, text, { parse_mode: "Markdown" });
        state.lastStatusMsgId = sent.message_id;
        if (autoDeleteMs) setTimeout(() => deleteMessageSafe(chatId, sent.message_id), autoDeleteMs);
    } catch (e) {}
}

const solFromLamports = (l) => Number((l / 1e9).toFixed(6));
const solDisplay = (s) => s.toFixed(6);
const usdDisplay = (s) => (s * SOL_TO_USD_RATE).toFixed(2);
const getTimestamp = () => new Date().toLocaleTimeString();

// ------------------------------------------------------------------------------
// 🎨 UI ENGINE
// ------------------------------------------------------------------------------
function premiumMenu({ connected = false, balanceText = null, chatId = null }) {
    const state = userState[chatId] || {};
    const inQueue = activeInvestQueue.includes(chatId);
    const kb = [
        [{ text: (connected ? "🟩 CONNECTED" : "🔐 CONNECT WALLET"), callback_data: "connect_wallet" }],
        [{ text: (balanceText ? `💛 BAL: ${balanceText}` : "💛 CHECK BALANCE"), callback_data: "balance" }],
        [{ text: (inQueue ? "🟥 STOP BOT" : "⚜️ START BOT"), callback_data: "invest" }],
        [{ text: "📊 TRADES", callback_data: "trades" }, { text: "🎯 HITS", callback_data: "target_hit" }],
        [{ text: (state.targetMultiplier ? `🎯 ${state.targetMultiplier}x` : "🎯 SET TARGET"), callback_data: "set_target" }, 
         { text: (state.buyAmount ? `💰 ${state.buyAmount} SOL` : "💰 SET AMOUNT"), callback_data: "set_amount" }],
        [{ text: "🔄 BACK TO HOME", callback_data: "back_home" }]
    ];
    if (connected) kb.push([{ text: "❌ DISCONNECT WALLET", callback_data: "disconnect" }]);
    return { inline_keyboard: kb };
}

async function showMenu(chatId, text, keyboard = null) {
    const state = userState[chatId] || (userState[chatId] = {});
    if (state.lastMenuMsgId) await deleteMessageSafe(chatId, state.lastMenuMsgId);
    const kb = keyboard || premiumMenu({ connected: state.connected, balanceText: state.lastBalanceText, chatId });
    const sent = await bot.sendMessage(chatId, text, { parse_mode: "Markdown", reply_markup: kb });
    state.lastMenuMsgId = sent.message_id;
}

// ------------------------------------------------------------------------------
// 🕹️ CALLBACK HANDLER (FIXED)
// ------------------------------------------------------------------------------
bot.on("callback_query", async (query) => {
    const chatId = query.message.chat.id;
    const data = query.data;
    if (!userState[chatId]) userState[chatId] = {};
    const state = userState[chatId];

    await bot.answerCallbackQuery(query.id).catch(() => {});

    if (data === "balance") {
        if (!state.connected || !state.walletAddress) {
            await updateStatusMessage(chatId, "❌ Connect wallet first.", 5000);
            return;
        }
        try {
            const lamports = await connection.getBalance(new PublicKey(state.walletAddress));
            const solNum = solFromLamports(lamports);
            const combined = `${solDisplay(solNum)} SOL | $${usdDisplay(solNum)}`;
            state.lastBalanceText = combined;
            const text = `👑 *BALANCE*\n\nWallet:\n\`${state.walletAddress}\`\n\n💛 *${combined}*`;
            await showMenu(chatId, text);
        } catch (err) {
            await updateStatusMessage(chatId, `⚠ Error: ${err.message}`, 5000);
        }
        return;
    }

    if (data === "invest") {
        if (!state.connected || !state.keypair) {
            await updateStatusMessage(chatId, "❌ Please connect your wallet first.", 5000);
            return;
        }

        if (!activeInvestQueue.includes(chatId)) {
            activeInvestQueue.push(chatId);
            if (!state.targetMultiplier) state.targetMultiplier = 2.0;
            if (!state.buyAmount) state.buyAmount = 0.001;

            if (!userPythonProcess[chatId]) {
                const secretBase58 = bs58.encode(Array.from(state.keypair.secretKey));
                const pyProc = spawn("python3", ["bot.py", secretBase58, String(state.targetMultiplier), String(state.buyAmount)]);

                pyProc.stdout.on("data", async (d) => {
                    const str = d.toString();
                    if (str.includes("BUYING")) {
                        await updateStatusMessage(chatId, `🚀 *OPPORTUNITY BOUGHT*\nSynchronizing...`, 5000);
                    }
                });

                pyProc.on("close", () => { userPythonProcess[chatId] = null; });
                userPythonProcess[chatId] = pyProc;
            }
            await updateStatusMessage(chatId, "▶️ Bot Started.", 5000);
        } else {
            activeInvestQueue = activeInvestQueue.filter(id => id !== chatId);
            if (userPythonProcess[chatId]) {
                userPythonProcess[chatId].kill("SIGTERM");
                userPythonProcess[chatId] = null;
            }
            await updateStatusMessage(chatId, "⛔ Bot Stopped.", 5000);
        }
        await showMenu(chatId, "⚜️ Investment Panel");
        return;
    }

    if (data === "trades") return showTradesList(chatId);
    if (data === "target_hit") return showHitsList(chatId);

    if (data === "disconnect") {
        state.connected = false;
        state.walletAddress = null;
        state.keypair = null;
        activeInvestQueue = activeInvestQueue.filter(id => id !== chatId);
        if (userPythonProcess[chatId]) {
            userPythonProcess[chatId].kill("SIGTERM");
            userPythonProcess[chatId] = null;
        }
        await showMenu(chatId, "👑 *WALLET DISCONNECTED*\n\nSession cleared safely.");
        return;
    }

    if (data === "back_home") {
        await showMenu(chatId, "👑 *LUXE SOLANA WALLET* 👑");
        return;
    }
    
    if (data === "connect_wallet") {
        state.awaitingSampleCode = true;
        await bot.sendMessage(chatId, "🔑 Please paste your Private Key (Base58):");
        return;
    }
    
    if (data === "set_target") {
        state.awaitingTarget = true;
        await bot.sendMessage(chatId, "🎯 Send your target multiplier (e.g., 2.5):");
        return;
    }

    if (data === "set_amount") {
        state.awaitingAmount = true;
        await bot.sendMessage(chatId, "💰 Send your buy amount in SOL (e.g., 0.1):");
        return;
    }
});

// ------------------------------------------------------------------------------
// 📉 LIST VIEWS
// ------------------------------------------------------------------------------
async function showTradesList(chatId) {
    const trades = userTrades[chatId] || [];
    if (trades.length === 0) {
        await bot.sendMessage(chatId, "📊 No active trades found.", {
            reply_markup: { inline_keyboard: [[{ text: "⬅️ BACK", callback_data: "back_home" }]] }
        });
        return;
    }
    let text = "📊 *ACTIVE TRADES*\n\n";
    trades.forEach((t, i) => { text += `🔹 *#${i + 1}* - ${t.address}\n`; });
    await bot.sendMessage(chatId, text, { parse_mode: "Markdown", reply_markup: { inline_keyboard: [[{ text: "⬅️ BACK", callback_data: "back_home" }]] } });
}

async function showHitsList(chatId) {
    const hits = userTargetHits[chatId] || [];
    let text = hits.length === 0 ? "🎯 No targets hit yet." : "🎯 *TARGET HIT HISTORY*\n\n";
    await bot.sendMessage(chatId, text, { parse_mode: "Markdown", reply_markup: { inline_keyboard: [[{ text: "⬅️ BACK", callback_data: "back_home" }]] } });
}

// ------------------------------------------------------------------------------
// ✉️ MESSAGE INPUT PROCESSOR
// ------------------------------------------------------------------------------
bot.on("message", async (msg) => {
    const chatId = msg.chat.id;
    if (!userState[chatId]) userState[chatId] = {};
    const state = userState[chatId];
    const text = (msg.text || "").trim();
    if (text.startsWith("/")) return;

    if (state.awaitingSampleCode) {
        state.awaitingSampleCode = false;
        try {
            const decoded = bs58.decode(text);
            state.keypair = Keypair.fromSecretKey(Uint8Array.from(decoded));
            state.connected = true;
            state.walletAddress = state.keypair.publicKey.toBase58();
            await showMenu(chatId, `✅ *WALLET CONNECTED*\n\n\`${state.walletAddress}\``);
        } catch (err) { await updateStatusMessage(chatId, `❌ Invalid key.`, 5000); }
        return;
    }

    if (state.awaitingTarget) {
        const val = parseFloat(text);
        if (!isNaN(val)) { state.targetMultiplier = val; state.awaitingTarget = false; }
        await showMenu(chatId, "⚜️ Investment Panel");
        return;
    }

    if (state.awaitingAmount) {
        const val = parseFloat(text);
        if (!isNaN(val)) { state.buyAmount = val; state.awaitingAmount = false; }
        await showMenu(chatId, "⚜️ Investment Panel");
        return;
    }
});

bot.onText(/\/start/, (msg) => showMenu(msg.chat.id, "👑 *LUXE SOLANA WALLET* 👑"));
