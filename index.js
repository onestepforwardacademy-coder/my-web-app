/**
 * ==============================================================================
 * 👑 LUXE SOLANA WALLET BOT — FULL PRODUCTION MANIFEST (v6.1.0)
 * ==============================================================================
 */

import TelegramBot from "node-telegram-bot-api";
import fs from "fs";
import bs58 from "bs58";
import { spawn, exec } from "child_process";
import { Connection, clusterApiUrl, Keypair, PublicKey } from "@solana/web3.js";
import path from "path";
import { fileURLToPath } from "url";

// --- ANTI-ZOMBIE STARTUP ---
// This kills any ghost processes from previous crashes/runs
exec("pkill -9 node; pkill -9 python3", (err) => {
    console.log("[SYSTEM] Cleaning up background processes...");
});

// --- ESM ENVIRONMENT SETUP ---
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// --- HELPER: SPAWN PYTHON VIA VENV ---
function spawnPython(script, args = []) {
    const scriptPath = path.join(__dirname, script);
    // Point directly to your virtual environment
    const venvPython = path.join(__dirname, "venv", "bin", "python3");
    
    console.log(`[SPAWN] Executing: ${venvPython} ${scriptPath} ${args.join(' ')}`);
    const proc = spawn(venvPython, [scriptPath, ...args], { cwd: __dirname });
    
    proc.on("error", (err) => {
        console.error(`[SPAWN ERROR] Failed to start ${script}: ${err.message}`);
    });
    return proc;
}

// ------------------------------------------------------------------------------
// ⚙️ SYSTEM CONFIGURATION
// ------------------------------------------------------------------------------
const BOT_TOKEN = "7970793585:AAFSIPoo3NYwdQMAq4PzeoxUdSnDOQAfSmo";
const NETWORK = "mainnet-beta";
const RPC_URL = clusterApiUrl(NETWORK);
const LOG_FILE = "output.txt";
const SOL_TO_USD_RATE = 133.93; 
const REFRESH_INTERVAL_MS = 1000; 

const connection = new Connection(RPC_URL, "confirmed");

// ------------------------------------------------------------------------------
// 💾 GLOBAL STATE
// ------------------------------------------------------------------------------
const userState = {};
const userPythonProcess = {};            
const userTrades = {};            
const userTargetHits = {};
const userStopLossHits = {};      
const liveMonitorIntervals = {}; 
let activeInvestQueue = []; 

// ------------------------------------------------------------------------------
// 🤖 TELEGRAM BOT SETUP
// ------------------------------------------------------------------------------
const bot = new TelegramBot(BOT_TOKEN, { polling: { interval: 300, autoStart: true } });

// ------------------------------------------------------------------------------
// 🛠️ UTILITIES & MESSAGE MANAGEMENT
// ------------------------------------------------------------------------------
function logToFile(line) {
    const entry = `[${new Date().toISOString()}] ${line}`;
    fs.appendFileSync(LOG_FILE, entry + "\n", "utf8");
}

async function deleteMessageSafe(chatId, messageId) {
    if (!messageId) return;
    try { await bot.deleteMessage(chatId, messageId); } catch (e) {}
}

async function updateStatusMessage(chatId, text, autoDeleteMs = null) {
    const state = userState[chatId];
    if (state.lastStatusMsgId) await deleteMessageSafe(chatId, state.lastStatusMsgId);
    try {
        const sent = await bot.sendMessage(chatId, text, { parse_mode: "Markdown" });
        state.lastStatusMsgId = sent.message_id;
        if (autoDeleteMs) setTimeout(() => deleteMessageSafe(chatId, sent.message_id), autoDeleteMs);
    } catch (e) { logToFile(`Status Error: ${e.message}`); }
}

const solFromLamports = (l) => Number((l / 1e9).toFixed(6));
const usdDisplay = (s) => (s * SOL_TO_USD_RATE).toFixed(2);
const shortAddress = (a) => a?.length > 12 ? a.slice(0, 6) + "…" + a.slice(-6) : a;

// ------------------------------------------------------------------------------
// 🎨 UI ENGINE (CLEANED UP)
// ------------------------------------------------------------------------------
function premiumMenu({ connected = false, balanceText = null, chatId = null } = {}) {
    const PAD = 48;
    const state = userState[chatId] || {};
    const isRunning = activeInvestQueue.includes(chatId);

    const keyboard = [
        [{ text: (connected ? "🟩 CONNECTED" : "🔐 CONNECT WALLET").padEnd(PAD), callback_data: "connect_wallet" }],
        [{ text: (balanceText ? `💛 BALANCE: ${balanceText}` : "💛 CHECK BALANCE").padEnd(PAD), callback_data: "balance" }],
        [{ text: (isRunning ? "🟥 STOP INVESTMENT BOT" : "⚜️ START INVESTMENT BOT").padEnd(PAD), callback_data: "invest" }],
        [{ text: "📊 TRADES".padEnd(PAD), callback_data: "trades" }],
        [{ text: "💸 SELL BACK".padEnd(PAD), callback_data: "sell_back_list" }],
        [{ text: "🛑 PANIC SELL ALL".padEnd(PAD), callback_data: "panic_sell" }],
        [{ text: "🛡️ VERIFY DEV RUG HISTORY".padEnd(PAD), callback_data: "verify_rug_history" }],
        [{ text: "📤 TRANSFER SOL".padEnd(PAD), callback_data: "transfer_sol" }],
        [{ text: (state.targetMultiplier ? `🎯 TARGET: ${state.targetMultiplier}x` : "🎯 SET TARGET").padEnd(PAD), callback_data: "set_target" }],
        [{ text: (state.buyAmount ? `💰 AMOUNT: ${state.buyAmount} SOL` : "💰 SET AMOUNT").padEnd(PAD), callback_data: "set_amount" }]
    ];

    if (connected) keyboard.push([{ text: "❌ DISCONNECT WALLET".padEnd(PAD), callback_data: "disconnect" }]);
    return { inline_keyboard: keyboard };
}

async function showMenu(chatId, text, kb = null) {
    const state = userState[chatId];
    if (state.lastMenuMsgId) await deleteMessageSafe(chatId, state.lastMenuMsgId);
    const buttons = kb || premiumMenu({ connected: state.connected, balanceText: state.lastBalanceText, chatId });
    try {
        const sent = await bot.sendMessage(chatId, text, { parse_mode: "Markdown", reply_markup: buttons });
        state.lastMenuMsgId = sent.message_id;
    } catch (e) {}
}

// ------------------------------------------------------------------------------
// 📡 REAL-TIME MONITOR
// ------------------------------------------------------------------------------
function runLiveMonitor(chatId) {
    if (liveMonitorIntervals[chatId]) clearInterval(liveMonitorIntervals[chatId]);
    liveMonitorIntervals[chatId] = setInterval(async () => {
        const state = userState[chatId];
        if (!state?.connected || !state.lastMenuMsgId) return clearInterval(liveMonitorIntervals[chatId]);
        try {
            const bal = await connection.getBalance(new PublicKey(state.walletAddress));
            const sol = solFromLamports(bal);
            const combined = `${sol.toFixed(4)} SOL | $${usdDisplay(sol)}`;
            if (state.lastBalanceText !== combined) {
                state.lastBalanceText = combined;
                await bot.editMessageText(`👑 *LUXE WALLET*\n🟩 *Connected:* \`${state.walletAddress}\`\n💛 *Live:* ${combined}`, {
                    chat_id: chatId, message_id: state.lastMenuMsgId, parse_mode: "Markdown",
                    reply_markup: premiumMenu({ connected: true, balanceText: combined, chatId })
                }).catch(()=>{});
            }
        } catch (e) {}
    }, REFRESH_INTERVAL_MS);
}

// ------------------------------------------------------------------------------
// 🕹️ INTERACTION CONTROLLER
// ------------------------------------------------------------------------------
bot.on("callback_query", async (query) => {
    const chatId = query.message.chat.id;
    const data = query.data;
    const state = userState[chatId];
    const messageId = query.message.message_id;

    if (data === "back_home") return showMenu(chatId, "👑 *LUXE SOLANA WALLET*");

    // --- INVEST TOGGLE ---
    if (data === "invest") {
        if (!state.connected) return updateStatusMessage(chatId, "❌ Connect wallet first.", 3000);
        if (!activeInvestQueue.includes(chatId)) {
            activeInvestQueue.push(chatId);
            const pk = bs58.encode(Array.from(state.keypair.secretKey));
            userPythonProcess[chatId] = spawnPython("bot.py", [pk, String(state.targetMultiplier || 2.0), String(state.buyAmount || 0.01)]);
            
            userPythonProcess[chatId].stdout.on("data", (d) => {
                const str = d.toString();
                if (str.includes("BUYING")) updateStatusMessage(chatId, `🚀 *Position Opened:* ${str.match(/[A-Za-z0-9]{32,44}/)}`, 10000);
            });
            await updateStatusMessage(chatId, "▶️ Bot Started. Scanning...", 5000);
        } else {
            activeInvestQueue = activeInvestQueue.filter(id => id !== chatId);
            if (userPythonProcess[chatId]) { userPythonProcess[chatId].kill(); userPythonProcess[chatId] = null; }
            await updateStatusMessage(chatId, "⛔ Bot Stopped.", 5000);
        }
        return showMenu(chatId, "👑 *LUXE SOLANA WALLET*");
    }

    // --- RUG HISTORY ---
    if (data === "verify_rug_history") {
        state.awaitingRugToken = true;
        const sent = await bot.sendMessage(chatId, "🛡️ *Enter token address to check history (main.py):*");
        state.lastPromptId = sent.message_id;
        return;
    }

    // --- TRANSFER ---
    if (data === "transfer_sol") {
        if (!state.connected) return updateStatusMessage(chatId, "❌ Connect wallet first.", 3000);
        state.awaitingTransferAddress = true;
        const sent = await bot.sendMessage(chatId, "📤 *Step 1:* Enter destination address:");
        state.lastPromptId = sent.message_id;
        return;
    }

    // --- PANIC SELL ---
    if (data === "panic_sell") {
        if (!state.connected) return;
        await updateStatusMessage(chatId, "🚨 *Executing Panic Sell via execute_sell.py...*");
        const pk = bs58.encode(Array.from(state.keypair.secretKey));
        userTrades[chatId]?.forEach(t => spawnPython("execute_sell.py", [pk, t.address]));
        userTrades[chatId] = [];
        setTimeout(() => showMenu(chatId, "✅ Panic Sell complete."), 5000);
        return;
    }

    // --- WALLET CONNECT ---
    if (data === "connect_wallet") {
        const kb = { inline_keyboard: [[{ text: "✏️ SAMPLE CODE", callback_data: "enter_sample" }], [{ text: "⬅️ BACK", callback_data: "back_home" }]] };
        return showMenu(chatId, "👑 *CONNECT WALLET*", kb);
    }

    if (data === "enter_sample") {
        state.awaitingSampleCode = true;
        const sent = await bot.sendMessage(chatId, "✏️ *Paste your Private Key (Base58) now:*");
        state.lastPromptId = sent.message_id;
        return;
    }

    if (data === "disconnect") {
        state.connected = false; state.keypair = null;
        activeInvestQueue = activeInvestQueue.filter(id => id !== chatId);
        if (userPythonProcess[chatId]) userPythonProcess[chatId].kill();
        return showMenu(chatId, "❌ Wallet Disconnected.");
    }

    // --- OTHER UI HANDLERS ---
    if (data === "set_target") { state.awaitingTarget = true; const sent = await bot.sendMessage(chatId, "🎯 Target (e.g. 2.5):"); state.lastPromptId = sent.message_id; }
    if (data === "set_amount") { state.awaitingAmount = true; const sent = await bot.sendMessage(chatId, "💰 Amount (e.g. 0.1):"); state.lastPromptId = sent.message_id; }
    if (data === "trades") {
        let txt = "📊 *ACTIVE TRADES*\n\n" + (userTrades[chatId]?.map((t,i) => `${i+1}. \`${t.address.slice(0,8)}...\` - ${t.amount} SOL`).join("\n") || "None");
        bot.sendMessage(chatId, txt, { parse_mode: "Markdown", reply_markup: { inline_keyboard: [[{ text: "⬅️ BACK", callback_data: "back_home" }]] } });
    }
});

// ------------------------------------------------------------------------------
// ✉️ MESSAGE PROCESSOR
// ------------------------------------------------------------------------------
bot.on("message", async (msg) => {
    const chatId = msg.chat.id;
    const text = (msg.text || "").trim();
    if (!userState[chatId]) userState[chatId] = { connected: false };
    const state = userState[chatId];
    if (text.startsWith("/")) return;

    await deleteMessageSafe(chatId, msg.message_id);
    if (state.lastPromptId) await deleteMessageSafe(chatId, state.lastPromptId);

    // 1. Private Key Connect
    if (state.awaitingSampleCode) {
        state.awaitingSampleCode = false;
        try {
            state.keypair = Keypair.fromSecretKey(Uint8Array.from(bs58.decode(text)));
            state.connected = true; state.walletAddress = state.keypair.publicKey.toBase58();
            runLiveMonitor(chatId);
            await showMenu(chatId, `✅ *Wallet Connected:* \`${state.walletAddress}\``);
        } catch (e) { updateStatusMessage(chatId, "❌ Invalid Private Key.", 5000); }
    }

    // 2. Rug History (main.py)
    else if (state.awaitingRugToken) {
        state.awaitingRugToken = false;
        await updateStatusMessage(chatId, "🔎 Scanning...");
        const proc = spawnPython("main.py", [text]);
        let output = "";
        proc.stdout.on("data", (d) => output += d.toString());
        proc.on("close", () => bot.sendMessage(chatId, `🛡️ *Rug Analysis:*\n\n\`${output || "No data."}\``, { parse_mode: "Markdown" }));
    }

    // 3. Transfer Logic (transfer.py)
    else if (state.awaitingTransferAddress) {
        state.awaitingTransferAddress = false; state.pendingTo = text;
        state.awaitingTransferAmount = true;
        const sent = await bot.sendMessage(chatId, `💰 *Amount to send to* \`${text.slice(0,8)}...\`:`);
        state.lastPromptId = sent.message_id;
    }
    else if (state.awaitingTransferAmount) {
        state.awaitingTransferAmount = false;
        const amt = text; const to = state.pendingTo;
        await updateStatusMessage(chatId, "💸 *Sending via transfer.py...*");
        const pk = bs58.encode(Array.from(state.keypair.secretKey));
        const proc = spawnPython("transfer.py", [pk, to, amt]);
        proc.stdout.on("data", (d) => bot.sendMessage(chatId, `✅ *Sent!*\nSig: \`${d.toString().trim()}\``));
    }

    // 4. Settings
    else if (state.awaitingTarget) { state.targetMultiplier = text; state.awaitingTarget = false; showMenu(chatId, `🎯 Target set to ${text}x`); }
    else if (state.awaitingAmount) { state.buyAmount = text; state.awaitingAmount = false; showMenu(chatId, `💰 Amount set to ${text} SOL`); }
});

bot.onText(/\/start/, (msg) => {
    userState[msg.chat.id] = userState[msg.chat.id] || { connected: false };
    showMenu(msg.chat.id, "👑 *LUXE SOLANA WALLET V6.1*");
});

console.log("💎 LUXE BOT ONLINE");
