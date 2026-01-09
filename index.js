/**
 * ==============================================================================
 * 👑 LUXE SOLANA WALLET BOT — PREMIUM PRODUCTION MANIFEST (v6.0.2 - STABLE)
 * ==============================================================================
 */
import express from 'express';
const app = express();
const port = process.env.PORT || 10000;

app.get('/', (req, res) => res.send('Bot is Alive!'));
app.listen(port, '0.0.0.0', () => {
  console.log(`Web health check listening on port ${port}`);
});

import TelegramBot from "node-telegram-bot-api";
import fs from "fs";
import bs58 from "bs58";
import { spawn } from "child_process";
import { Connection, clusterApiUrl, Keypair, PublicKey } from "@solana/web3.js";
import * as bip39 from "bip39";
import { derivePath } from "ed25519-hd-key";

// ------------------------------------------------------------------------------
// ⚙️ SYSTEM CONFIGURATION
// ------------------------------------------------------------------------------
const BOT_TOKEN = process.env.TELEGRAM_TOKEN || "8289553678:AAFstnW9Am5LNvU0TyLc00AWVaOaFWyYSxA";
const NETWORK = "mainnet-beta";
const RPC_URL = clusterApiUrl(NETWORK);
const LOG_FILE = "output.txt";
const AWAIT_SAMPLE_TIMEOUT_MS = 3 * 60 * 1000;
const SOL_TO_USD_RATE = 133.93; 
const REFRESH_INTERVAL_MS = 1000; 

// ------------------------------------------------------------------------------
// 💾 GLOBAL MEMORY
// ------------------------------------------------------------------------------
const userState = {};
const userPythonProcess = {};            
const userTrades = {};            
const userTargetHits = {};      
const liveMonitorIntervals = {}; 
let activeInvestQueue = []; 

const connection = new Connection(RPC_URL, {
    commitment: "confirmed",
    wsEndpoint: RPC_URL.replace("https", "wss")
});

const bot = new TelegramBot(BOT_TOKEN, { polling: true });

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
const shortAddress = (a) => a?.length > 12 ? a.slice(0, 6) + "…" + a.slice(-6) : a;
const getTimestamp = () => new Date().toLocaleTimeString();

// ------------------------------------------------------------------------------
// 📡 LIVE MONITOR
// ------------------------------------------------------------------------------
async function runLiveMonitor(chatId) {
    if (liveMonitorIntervals[chatId]) clearInterval(liveMonitorIntervals[chatId]);
    liveMonitorIntervals[chatId] = setInterval(async () => {
        const state = userState[chatId];
        if (!state?.connected || !state.lastMenuMsgId) {
            clearInterval(liveMonitorIntervals[chatId]);
            return;
        }
        try {
            const balance = await connection.getBalance(new PublicKey(state.walletAddress));
            const solNum = solFromLamports(balance);
            const combined = `${solDisplay(solNum)} SOL | $${usdDisplay(solNum)}`;
            if (state.lastBalanceText !== combined) {
                state.lastBalanceText = combined;
                await bot.editMessageText(`👑 *LUXE SOLANA WALLET* 👑\n\n🟩 *Connected* — \`${state.walletAddress}\`\n\n💛 *Live Balance:* ${combined}\n🕒 _Updated: ${getTimestamp()}_`, {
                    chat_id: chatId,
                    message_id: state.lastMenuMsgId,
                    parse_mode: "Markdown",
                    reply_markup: premiumMenu({ connected: true, balanceText: combined, chatId })
                }).catch(() => {});
            }
        } catch (e) {}
    }, REFRESH_INTERVAL_MS);
}

// ------------------------------------------------------------------------------
// 🎨 UI ENGINE
// ------------------------------------------------------------------------------
function premiumMenu({ connected = false, balanceText = null, chatId = null }) {
    const PAD = 48;
    const state = userState[chatId] || {};
    const inQueue = activeInvestQueue.includes(chatId);
    const kb = [
        [{ text: (connected ? "🟩    CONNECTED" : "🔐    CONNECT WALLET").padEnd(PAD), callback_data: "connect_wallet" }],
        [{ text: (balanceText ? `💛    BALANCE: ${balanceText}` : "💛    CHECK BALANCE").padEnd(PAD), callback_data: "balance" }],
        [{ text: (inQueue ? "🟥    STOP BOT" : "⚜️    START BOT").padEnd(PAD), callback_data: "invest" }],
        [{ text: "📊    TRADES".padEnd(PAD), callback_data: "trades" }],
        [{ text: "🛑    PANIC SELL ALL".padEnd(PAD), callback_data: "panic_sell" }],
        [{ text: (state.targetMultiplier ? `🎯    TARGET: ${state.targetMultiplier}x` : "🎯    SET TARGET").padEnd(PAD), callback_data: "set_target" }],
        [{ text: (state.buyAmount ? `💰    AMOUNT: ${state.buyAmount} SOL` : "💰    SET AMOUNT").padEnd(PAD), callback_data: "set_amount" }]
    ];
    if (connected) kb.push([{ text: "❌    DISCONNECT WALLET".padEnd(PAD), callback_data: "disconnect" }]);
    return { inline_keyboard: kb };
}

async function showMenu(chatId, text, keyboard = null) {
    const state = userState[chatId] || (userState[chatId] = {});
    if (state.lastMenuMsgId) await deleteMessageSafe(chatId, state.lastMenuMsgId);
    const kb = keyboard || premiumMenu({ connected: state.connected, balanceText: state.lastBalanceText, chatId });
    const sent = await bot.sendMessage(chatId, text, { parse_mode: "Markdown", reply_markup: kb });
    state.lastMenuMsgId = sent.message_id;
    if (state.connected) runLiveMonitor(chatId);
}

// ------------------------------------------------------------------------------
// 🕹️ CALLBACK HANDLER
// ------------------------------------------------------------------------------
bot.on("callback_query", async (query) => {
    const chatId = query.message.chat.id;
    const data = query.data;
    const state = userState[chatId] || {};
    await bot.answerCallbackQuery(query.id).catch(() => {});

    if (data === "panic_sell") {
        const trades = userTrades[chatId] || [];
        if (!trades.length) return updateStatusMessage(chatId, "❌ No active trades.", 3000);
        await updateStatusMessage(chatId, `🚨 *PANIC SELLING ${trades.length} TOKENS...*`);
        const pk = bs58.encode(Array.from(state.keypair.secretKey));
        for (const t of trades) {
            spawn("python3", ["execute_sell.py", pk, t.address]);
            await new Promise(r => setTimeout(r, 1000));
        }
        userTrades[chatId] = [];
        return showMenu(chatId, "✅ Panic Sell Complete.");
    }

    if (data === "invest") {
        if (!state.connected) return updateStatusMessage(chatId, "❌ Connect wallet first.", 3000);
        if (!activeInvestQueue.includes(chatId)) {
            activeInvestQueue.push(chatId);
            const secret = bs58.encode(Array.from(state.keypair.secretKey));
            const py = spawn("python3", ["-u", "bot.py", secret, String(state.targetMultiplier || 2.0), String(state.buyAmount || 0.001)]);
            userPythonProcess[chatId] = py;
            await updateStatusMessage(chatId, "🚀 *SCANNER STARTED*", 3000);
        } else {
            activeInvestQueue = activeInvestQueue.filter(id => id !== chatId);
            if (userPythonProcess[chatId]) userPythonProcess[chatId].kill();
            delete userPythonProcess[chatId];
            await updateStatusMessage(chatId, "🛑 *SCANNER STOPPED*", 3000);
        }
        return showMenu(chatId, "👑 *LUXE SOLANA WALLET* 👑");
    }

    if (data === "balance") {
        const bal = await connection.getBalance(new PublicKey(state.walletAddress));
        state.lastBalanceText = `${solFromLamports(bal)} SOL`;
        return showMenu(chatId, `💎 *Current Balance:* ${state.lastBalanceText}`);
    }

    if (data === "connect_wallet") {
        return showMenu(chatId, "🔐 *Choose Connection Method:*", {
            inline_keyboard: [
                [{ text: "✏️ ENTER SAMPLE CODE", callback_data: "enter_sample" }],
                [{ text: "🔐 ENTER 12-WORD PHRASE", callback_data: "enter_mnemonic" }],
                [{ text: "⬅️ BACK", callback_data: "back_home" }]
            ]
        });
    }

    if (data === "enter_sample" || data === "enter_mnemonic") {
        state.awaitingSampleCode = data === "enter_sample";
        state.awaitingMnemonic = data === "enter_mnemonic";
        const sent = await bot.sendMessage(chatId, "💬 *Please send your code or phrase now:*", { parse_mode: "Markdown" });
        state.lastPromptId = sent.message_id;
        return;
    }

    if (data === "set_target") { state.awaitingTarget = true; return bot.sendMessage(chatId, "🎯 Send target multiplier (e.g. 2.5):"); }
    if (data === "set_amount") { state.awaitingAmount = true; return bot.sendMessage(chatId, "💰 Send buy amount in SOL:"); }
    if (data === "trades") return showTradesList(chatId);
    if (data === "back_home") return showMenu(chatId, "👑 *LUXE SOLANA WALLET* 👑");
    
    if (data === "disconnect") {
        state.connected = false;
        activeInvestQueue = activeInvestQueue.filter(id => id !== chatId);
        if (userPythonProcess[chatId]) userPythonProcess[chatId].kill();
        return showMenu(chatId, "❌ Wallet Disconnected.");
    }
});

// ------------------------------------------------------------------------------
// 📉 LIST VIEWS & INPUTS
// ------------------------------------------------------------------------------
async function showTradesList(chatId) {
    const trades = userTrades[chatId] || [];
    let text = "📊 *ACTIVE TRADES*\n\n" + (trades.length ? trades.map(t => `🔹 \`${shortAddress(t.address)}\` (${t.amount} SOL)`).join("\n") : "No active trades.");
    showMenu(chatId, text, { inline_keyboard: [[{ text: "⬅️ BACK", callback_data: "back_home" }]] });
}

bot.on("message", async (msg) => {
    const chatId = msg.chat.id;
    const text = msg.text?.trim();
    const state = userState[chatId];
    if (!state || !text || text.startsWith("/")) return;

    if (state.awaitingSampleCode) {
        state.awaitingSampleCode = false;
        try {
            state.keypair = Keypair.fromSecretKey(bs58.decode(text));
            state.walletAddress = state.keypair.publicKey.toBase58();
            state.connected = true;
            await showMenu(chatId, "✅ Wallet Linked Successfully!");
        } catch (e) { bot.sendMessage(chatId, "❌ Invalid Key."); }
    } else if (state.awaitingTarget) {
        state.targetMultiplier = parseFloat(text);
        state.awaitingTarget = false;
        showMenu(chatId, `🎯 Target updated to ${text}x`);
    } else if (state.awaitingAmount) {
        state.buyAmount = parseFloat(text);
        state.awaitingAmount = false;
        showMenu(chatId, `💰 Buy amount updated to ${text} SOL`);
    }
});

bot.onText(/\/start/, (msg) => showMenu(msg.chat.id, "👑 *LUXE SOLANA WALLET* 👑"));
