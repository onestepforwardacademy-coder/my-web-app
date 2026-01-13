/**
 * ==============================================================================
 * 👑 LUXE SOLANA WALLET BOT — PREMIUM PRODUCTION MANIFEST (v6.0.0)
 * ==============================================================================
 */

import TelegramBot from "node-telegram-bot-api";
import fs from "fs";
import bs58 from "bs58";
import { spawn } from "child_process";
import { Connection, clusterApiUrl, Keypair, PublicKey } from "@solana/web3.js";
import * as bip39 from "bip39";
import { derivePath } from "ed25519-hd-key";
import path from "path";
import { fileURLToPath } from "url";

// Get __dirname equivalent in ESM
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Helper to spawn Python scripts with correct paths
// Cleanup sold token from all tracking arrays
function cleanupSoldToken(chatId, tokenAddr) {
    // Remove from userTrades
    if (userTrades[chatId]) {
        userTrades[chatId] = userTrades[chatId].filter(t => t.address !== tokenAddr);
    }
    // Remove from userPositions
    if (userPositions[chatId]) {
        userPositions[chatId] = userPositions[chatId].filter(p => p.token !== tokenAddr);
    }
    // Remove from userTargetHits
    if (userTargetHits[chatId]) {
        userTargetHits[chatId] = userTargetHits[chatId].filter(t => t.address !== tokenAddr);
    }
    // Remove from userStopLossHits
    if (userStopLossHits[chatId]) {
        userStopLossHits[chatId] = userStopLossHits[chatId].filter(t => t.address !== tokenAddr);
    }
    // Also call Python DB cleanup
    spawnPython("user_db.py", ["cleanup", String(chatId), tokenAddr]);
    console.log(`[CLEANUP] Removed ${tokenAddr.slice(0,8)}... from all tracking for ${chatId}`);
}

function spawnPython(script, args = []) {
    const scriptPath = path.join(__dirname, script);
    console.log(`[SPAWN] Launching: python3 ${scriptPath} ${args.join(' ')}`);
    console.log(`[SPAWN] CWD: ${__dirname}`);
    
    const proc = spawn("python3", [scriptPath, ...args], { cwd: __dirname });
    
    proc.on("error", (err) => {
        console.error(`[SPAWN ERROR] Failed to start ${script}: ${err.message}`);
    });
    
    return proc;
}

// ------------------------------------------------------------------------------
// ⚙️ SYSTEM CONFIGURATION & CONSTANTS
// ------------------------------------------------------------------------------
const BOT_TOKEN = process.env.TELEGRAM_TOKEN || "7246241507:AAGOvokvFkayC__UBd4Nk39KeDLzSUoSQzw";
const NETWORK = "mainnet-beta";
const RPC_URL = clusterApiUrl(NETWORK);
const LOG_FILE = "output.txt";
const AWAIT_SAMPLE_TIMEOUT_MS = 3 * 60 * 1000;
let SOL_TO_USD_RATE = 133.93;
let lastSolPriceFetch = 0;

async function fetchLiveSolPrice() {
    try {
        const now = Date.now();
        if (now - lastSolPriceFetch < 60000) return SOL_TO_USD_RATE;
        
        const resp = await fetch("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd");
        const data = await resp.json();
        if (data?.solana?.usd) {
            SOL_TO_USD_RATE = data.solana.usd;
            lastSolPriceFetch = now;
            console.log("[PRICE] SOL updated to $" + SOL_TO_USD_RATE);
        }
    } catch (e) {
        console.log("[PRICE] Fetch failed, using cached: $" + SOL_TO_USD_RATE);
    }
    return SOL_TO_USD_RATE;
}

fetchLiveSolPrice();
setInterval(fetchLiveSolPrice, 60000); 
const REFRESH_INTERVAL_MS = 1000; 

const PUMP_FUN_PROGRAM_ID = "6EF8rSdWkbzzqJuS2B73rw9URnR445as6U3LTmpxTazz";
const SLIPPAGE_BPS = 500; 
const JITO_TIP_LAMPORTS = 100000;

// ------------------------------------------------------------------------------
// 💾 GLOBAL MEMORY & STATE MANAGEMENT
// ------------------------------------------------------------------------------
const userState = {};
const userPythonProcess = {};            
const userTrades = {};            
const userTargetHits = {};
const userStopLossHits = {};
const userPositions = {};  // Track positions for live profit
const userInvestActive = {};  // Track which users have invest mode active: {chatId: [{token, buyPrice, amount, timestamp}]}      
const liveMonitorIntervals = {}; 
const systemAuditLogs = [];

// NEW: Global Queue for active investment accounts
let activeInvestQueue = []; 

// ------------------------------------------------------------------------------
// 🔗 BLOCKCHAIN INFRASTRUCTURE
// ------------------------------------------------------------------------------
const connection = new Connection(RPC_URL, {
    commitment: "confirmed",
    confirmTransactionInitialTimeout: 60000,
    wsEndpoint: RPC_URL.replace("https", "wss")
});

// ------------------------------------------------------------------------------
// 🤖 TELEGRAM BOT INITIALIZATION
// ------------------------------------------------------------------------------
const bot = new TelegramBot(BOT_TOKEN, { 
    polling: {
        interval: 300,
        autoStart: true,
        params: {
            allowed_updates: ["message", "callback_query"]
        }
    } 
});

// ------------------------------------------------------------------------------
// 🔌 EXTERNAL MODULE INTEGRATION (INLINE)
// ------------------------------------------------------------------------------
const extraButtons = [];

function attachExtraButtons(botInstance, stateRef) {
    console.log("[EXTRA_BUTTONS] Module initialized (inline mode)");
}

function getExtraButtons() {
    return extraButtons;
}

attachExtraButtons(bot, userState);

// ------------------------------------------------------------------------------
// 🛠️ INTERNAL UTILITY SUITE
// ------------------------------------------------------------------------------

function logToFile(line) {
    try { 
        const timestamp = new Date().toISOString();
        const entry = `[${timestamp}] ${line}`;
        fs.appendFileSync(LOG_FILE, entry + "\n", "utf8"); 
        systemAuditLogs.push(entry);
        if (systemAuditLogs.length > 100) systemAuditLogs.shift();
    } catch (e) {
        console.error("Logging failed:", e.message);
    }
}

async function deleteMessageSafe(chatId, messageId) {
    if (!messageId) return; 
    try { 
        await bot.deleteMessage(chatId, messageId); 
    } catch (e) {
        // Silently ignore
    }
}

async function updateStatusMessage(chatId, text, autoDeleteMs = null) {
    const state = userState[chatId];
    if (state.lastStatusMsgId) {
        await deleteMessageSafe(chatId, state.lastStatusMsgId);
    }
    try {
        const sent = await bot.sendMessage(chatId, text, { parse_mode: "Markdown" });
        state.lastStatusMsgId = sent.message_id;

        if (autoDeleteMs) {
            setTimeout(() => deleteMessageSafe(chatId, sent.message_id), autoDeleteMs);
        }
    } catch (e) {
        logToFile(`Status Message Error: ${e.message}`);
    }
}

function solFromLamports(lamports) { 
    return Number((lamports / 1e9).toFixed(6)); 
}

function solDisplay(solNum) { 
    return solNum.toFixed(6); 
}

function usdDisplay(solNum) { 
    return (solNum * SOL_TO_USD_RATE).toFixed(2); 
}

function shortAddress(addr) { 
    return addr?.length > 12 ? addr.slice(0, 6) + "…" + addr.slice(-6) : addr; 
}

function getTimestamp() {
    return new Date().toLocaleTimeString();
}

// ------------------------------------------------------------------------------
// 📡 REAL-TIME BALANCE MONITOR (1-SECOND TICK)
// ------------------------------------------------------------------------------

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

                const body = `👑 *LUXE SOLANA WALLET* 👑\n\n` +
                             `🟩 *Connected* — \`${state.walletAddress}\`\n\n` +
                             `💛 *Live Balance:* ${combined}\n` +
                             `🕒 _Updated: ${getTimestamp()}_`;

                await bot.editMessageText(body, {
                    chat_id: chatId,
                    message_id: state.lastMenuMsgId,
                    parse_mode: "Markdown",
                    reply_markup: premiumMenu({ 
                        connected: true, 
                        balanceText: combined, 
                        chatId, 
                        extraButtons: getExtraButtons() 
                    })
                }).catch(() => {});
            }
        } catch (error) {
            logToFile(`Monitor Error for ${chatId}: ${error.message}`);
        }
    }, REFRESH_INTERVAL_MS);
}

// ------------------------------------------------------------------------------
// 🎨 DYNAMIC UI ENGINE
// ------------------------------------------------------------------------------

function premiumMenu({ connected = false, balanceText = null, chatId = null, extraButtons = [] } = {}) {
    const PAD_WIDTH = 48;
    const state = userState[chatId] || {};

    const isUserInQueue = activeInvestQueue.includes(chatId);

    const connectLabel = (connected ?
        "🟩    CONNECTED (WALLET ACTIVE)    " :
        "🔐    CONNECT YOUR WALLET    ").padEnd(PAD_WIDTH, " ");

    const balanceLabel = (balanceText ?
        `💛    BALANCE — ${balanceText}    ` :
        "💛    BALANCE    ").padEnd(PAD_WIDTH, " ");

    const investLabel = (isUserInQueue ?
        "🟥    STOP INVESTMENT BOT    " :
        "⚜️    START INVESTMENT BOT    ").padEnd(PAD_WIDTH, " ");

    const tradesLabel = "📊    TRADES    ".padEnd(PAD_WIDTH, " ");
    const sellLabel = "💸    SELL BACK    ".padEnd(PAD_WIDTH, " ");

    const lastHit = userTargetHits[chatId] && userTargetHits[chatId].length > 0 
        ? userTargetHits[chatId][userTargetHits[chatId].length - 1].address 
        : null;
    const targetHitLabel = (lastHit 
        ? `🎯    HIT: ${shortAddress(lastHit)}` 
        : "🎯    TARGET HIT    ").padEnd(PAD_WIDTH, " ");

    const lastStopLoss = userStopLossHits[chatId] && userStopLossHits[chatId].length > 0 
        ? userStopLossHits[chatId][userStopLossHits[chatId].length - 1].address 
        : null;
    const stopLossLabel = (lastStopLoss 
        ? `🔻    LOSS: ${shortAddress(lastStopLoss)}` 
        : "🔻    STOP LOSS HIT    ").padEnd(PAD_WIDTH, " ");

    const targetMultiplierLabel = state.targetMultiplier
        ? `🎯    TARGET SET TO ${state.targetMultiplier}x    `
        : "🎯    SET TARGET    ";

    const buyAmountLabel = state.buyAmount
        ? `💰    AMOUNT SET TO ${state.buyAmount} SOL    `
        : "💰    SET AMOUNT    ";

    const keyboard = [
        [{ text: connectLabel, callback_data: "connect_wallet" }],
        [{ text: balanceLabel, callback_data: "balance" }],
        [{ text: investLabel, callback_data: "invest" }],
        [{ text: tradesLabel, callback_data: "trades" }],
        [{ text: sellLabel, callback_data: "sell_back_list" }],
        [{ text: "🛑    PANIC SELL ALL    ".padEnd(PAD_WIDTH, " "), callback_data: "panic_sell" }], 
        [{ text: targetHitLabel, callback_data: "target_hit" }],
        [{ text: stopLossLabel, callback_data: "stop_loss_hit" }],
        [{ text: targetMultiplierLabel, callback_data: "set_target" }],
        [{ text: buyAmountLabel, callback_data: "set_amount" }]
    ];

    keyboard.push([{ text: "🔄    SWAP NOW    ".padEnd(PAD_WIDTH, " "), callback_data: "swap_now" }]);
    keyboard.push([{ text: "📈    CHECK LIVE PROFIT    ".padEnd(PAD_WIDTH, " "), callback_data: "check_profit" }]);
    keyboard.push([{ text: "💸    TRANSFER SOL    ".padEnd(PAD_WIDTH, " "), callback_data: "transfer_sol" }]);
    keyboard.push([{ text: "🔍    VERIFY DEV RUG    ".padEnd(PAD_WIDTH, " "), callback_data: "verify_rug" }]);
    keyboard.push([{ text: "📊    ANALYSE TOKEN    ".padEnd(PAD_WIDTH, " "), callback_data: "analyse_token" }]);
    keyboard.push([{ text: "🔎    SEARCH TOKEN    ".padEnd(PAD_WIDTH, " "), callback_data: "search_token" }]);

    if (extraButtons && extraButtons.length) {
        keyboard.push(...extraButtons);
    }

    if (connected) {
        keyboard.push([{ text: "❌    DISCONNECT WALLET    ".padEnd(PAD_WIDTH, " "), callback_data: "disconnect" }]);
    }

    return { inline_keyboard: keyboard };
}

// ------------------------------------------------------------------------------
// 🖼️ UI RENDERER
// ------------------------------------------------------------------------------

async function showMenu(chatId, text, keyboard) {
    if (!userState[chatId]) userState[chatId] = {};
    const state = userState[chatId];

    if (state.lastStatusMsgId) {
        await deleteMessageSafe(chatId, state.lastStatusMsgId);
        state.lastStatusMsgId = null;
    }

    if (state.lastMenuMsgId) {
        await deleteMessageSafe(chatId, state.lastMenuMsgId);
        state.lastMenuMsgId = null;
    }

    const buttons = keyboard || premiumMenu({ 
        connected: state.connected, 
        balanceText: state.lastBalanceText, 
        chatId, 
        extraButtons: getExtraButtons() 
    });

    try {
        const sent = await bot.sendMessage(chatId, text, {
            parse_mode: "Markdown",
            reply_markup: buttons
        });
        state.lastMenuMsgId = sent.message_id;
    } catch (e) {
        logToFile(`Menu Render Error: ${e.message}`);
    }

    if (state.connected) {
        runLiveMonitor(chatId);
    }
}

// ------------------------------------------------------------------------------
// 🏁 CORE COMMAND HANDLERS
// ------------------------------------------------------------------------------

bot.onText(/\/start/, async (msg) => {
    const chatId = msg.chat.id;

    if (!userState[chatId]) {
        userState[chatId] = {
            connected: false,
            walletAddress: null,
            keypair: null,
            awaitingSampleCode: false,
            awaitingMnemonic: false,
            awaitingTimer: null,
            lastMenuMsgId: null,
            lastPromptId: null, 
            lastStatusMsgId: null,
            lastBalanceText: null,
            targetMultiplier: null,
            buyAmount: null,
            awaitingTarget: false,
            awaitingAmount: false,
            pumpFunActive: true,
            jitoEnabled: true
        };
        // Cleanup each token from all tracking
                results.forEach(r => cleanupSoldToken(chatId, r.addr));
                userTrades[chatId] = [];
        userTargetHits[chatId] = [];
    }

    const state = userState[chatId];
    const uiHeader = `👑 *LUXE SOLANA WALLET* 👑\n\n`;

    if (state.connected && state.walletAddress) {
        const balanceText = state.lastBalanceText || "Fetching balance...";
        const ui = `${uiHeader}🟩 *Connected* — \`${state.walletAddress}\`\n\n💛 *Balance:* ${balanceText}\n`;
        await showMenu(chatId, ui);
    } else {
        await showMenu(
            chatId,
            `${uiHeader}Your premium gateway to Solana & Pump.fun.\n\nSelect an option below to begin:\n`
        );
    }
});

// ------------------------------------------------------------------------------
// 🕹️ CALLBACK INTERACTION CONTROLLER
// ------------------------------------------------------------------------------

bot.on("callback_query", async (query) => {
    const chatId = query.message.chat.id;
    const data = query.data;

    if (!userState[chatId]) userState[chatId] = {};
    if (!userTrades[chatId]) userTrades[chatId] = [];
    if (!userTargetHits[chatId]) userTargetHits[chatId] = [];

    const state = userState[chatId];
    const messageId = query.message.message_id;

    if (data === "sell_back_list") {
        await deleteMessageSafe(chatId, messageId);
        const trades = userTrades[chatId] || [];
        if (trades.length === 0) {
            const noneMsg = await bot.sendMessage(chatId, "📊 No active trades found.", { 
                reply_markup: { inline_keyboard: [[{ text: "⬅️ BACK", callback_data: "back_home" }]] } 
            });
            setTimeout(() => deleteMessageSafe(chatId, noneMsg.message_id), 5000);
            return;
        }
        const btns = trades.map((t, i) => ([{ text: `💸 SELL [${i+1}] ${t.address.slice(0,12)}...`, callback_data: `conf_sell_${i}` }]));
        btns.push([{ text: "⬅️ BACK", callback_data: "back_home" }]);
        return bot.sendMessage(chatId, `💰 *SELECT TOKEN TO SELL BACK*\nTotal active pairs: ${trades.length}`, { parse_mode: "Markdown", reply_markup: { inline_keyboard: btns } });
    }

    if (data.startsWith("conf_sell_")) {
        const idx = data.split("_")[2];
        const trade = userTrades[chatId][idx];
        const confirmKb = { inline_keyboard: [[{ text: "✅ CONFIRM SELL", callback_data: `exec_sell_${idx}` }], [{ text: "❌ CANCEL", callback_data: "sell_back_list" }]] };
        return bot.sendMessage(chatId, `⚠️ *CONFIRM SELL*\n\nToken: \`${trade.address}\`\nExecute Sell Back?`, { parse_mode: "Markdown", reply_markup: confirmKb });
    }

    // --- UPDATED SELL BACK WITH SIGNATURE & AUTO-DELETE ---
    if (data.startsWith("exec_sell_")) {
        const idx = data.split("_")[2];
        const trade = userTrades[chatId][idx];
        const secret = bs58.encode(Array.from(state.keypair.secretKey));

        await deleteMessageSafe(chatId, messageId);
        await updateStatusMessage(chatId, `🚀 *EXECUTING SELL BACK...*`);

        const signatures = [];
        const proc = spawnPython("execute_sell.py", [secret, trade.address]);

        proc.stdout.on("data", (d) => { 
            const output = d.toString();
            process.stdout.write(`[SELL-BACK LOG]: ${output}`); 
            const sigMatch = output.match(/(?:Signature|TX|Hash):\s*([A-Za-z0-9]{32,88})/i);
            if (sigMatch) signatures.push(sigMatch[1]);
        });

        proc.on("close", async () => {
            cleanupSoldToken(chatId, trade.address);
            let report = "✅ *SELL COMPLETE*";
            if (signatures.length > 0) {
                report += `\n\n🔗 [View Transaction](https://solscan.io/tx/${signatures[0]})`;
            }

            const resMsg = await bot.sendMessage(chatId, report, { 
                parse_mode: "Markdown", 
                disable_web_page_preview: true 
            });

            // Cleanup report and show main menu
            setTimeout(() => deleteMessageSafe(chatId, resMsg.message_id), 10000);
            showMenu(chatId, "👑 *LUXE SOLANA WALLET* 👑");
        });
        return;
    }

    // --- UPDATED PANIC SELL ALL HANDLER (WITH AUTO-DELETE) ---
    if (data === "panic_sell") {
        const trades = userTrades[chatId] || [];
        if (trades.length === 0) {
            const noneMsg = await bot.sendMessage(chatId, "❌ No active trades found.");
            setTimeout(() => deleteMessageSafe(chatId, noneMsg.message_id), 5000);
            return showMenu(chatId, "👑 *LUXE SOLANA WALLET* 👑");
        }

        await updateStatusMessage(chatId, `🚨 *PANIC SELL INITIATED* 🚨\nSelling ${trades.length} tokens...`);

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
                    let report = "✅ *PANIC SELL COMPLETE*\n\n";
                    if (signatures.length > 0) {
                        signatures.forEach((s, idx) => {
                            report += `🔹 \`${s.addr.slice(0, 6)}...\` -> [View TX](https://solscan.io/tx/${s.sig})\n`;
                        });
                    } else {
                        report += "⚠️ TXs sent, but no signatures captured.";
                    }

                    const resMsg = await bot.sendMessage(chatId, report, { parse_mode: "Markdown", disable_web_page_preview: true });
                    setTimeout(() => deleteMessageSafe(chatId, resMsg.message_id), 15000);
                    userTrades[chatId] = [];
                    return showMenu(chatId, "👑 *LUXE SOLANA WALLET* 👑");
                }
            });
        }
        return;
    }

    if (data.startsWith("del_trade_")) {
        const idx = parseInt(data.split("_")[2]);
        cleanupSoldToken(chatId, trade.address);
        return showTradesList(chatId);
    }

    await deleteMessageSafe(chatId, messageId);

    if (data === "pump_fun_info") {
        const info = "⚡ *PUMP.FUN MODE*\n\n" +
                     "The bot is currently optimized for bonding curve detection.\n" +
                     "• Program: \`6EF8rSdW...\`\n" +
                     "• Routing: Jito Priority Bundles\n" +
                     "• Slippage: 500 BPS (Global Setting)";
        const infoMsg = await bot.sendMessage(chatId, info, { parse_mode: "Markdown" });
        setTimeout(() => deleteMessageSafe(chatId, infoMsg.message_id), 15000);
        return showMenu(chatId, "👑 *LUXE SOLANA WALLET* 👑");
    }

    if (data === "connect_wallet") {
        const text = `👑 *CONNECT WALLET* 👑\n\nChoose how to connect:`;
        const keyboard = {
            inline_keyboard: [
                [{ text: "✏️    ENTER SAMPLE CODE    ".padEnd(48, " "), callback_data: "enter_sample" }],
                [{ text: "🔐    ENTER 12-WORD PHRASE    ".padEnd(48, " "), callback_data: "enter_mnemonic" }],
                [{ text: "⬅️    BACK    ".padEnd(48, " "), callback_data: "back_home" }]
            ]
        };
        await showMenu(chatId, text, keyboard);
        return;
    }

    if (data === "enter_mnemonic") {
        state.awaitingMnemonic = true;
        const sent = await bot.sendMessage(chatId, "🔐 *Send your 12-word Trust Wallet phrase now.*", { 
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "⬅️    BACK    ", callback_data: "back_home" }]] }
        });
        state.lastPromptId = sent.message_id;
        return;
    }

    if (data === "enter_sample") {
        state.awaitingSampleCode = true;
        if (state.awaitingTimer) clearTimeout(state.awaitingTimer);
        state.awaitingTimer = setTimeout(() => { state.awaitingSampleCode = false; }, AWAIT_SAMPLE_TIMEOUT_MS);
        const sent = await bot.sendMessage(chatId, "✏️ *Send your Sample Wallet Code now.*", { 
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "⬅️    BACK    ", callback_data: "back_home" }]] }
        });
        state.lastPromptId = sent.message_id;
        return;
    }

    if (data === "set_target") {
        state.awaitingTarget = true;
        const sent = await bot.sendMessage(chatId, "🎯 *Send your target multiplier now* (e.g., 2 for 2x):", { 
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "⬅️    BACK    ", callback_data: "back_home" }]] }
        });
        state.lastPromptId = sent.message_id;
        return;
    }

    if (data === "set_amount") {
        state.awaitingAmount = true;
        const sent = await bot.sendMessage(chatId, "💰 *Send your buy amount in SOL* (e.g., 0.002):", { 
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "⬅️    BACK    ", callback_data: "back_home" }]] }
        });
        state.lastPromptId = sent.message_id;
        return;
    }

    if (data === "transfer_sol") {
        if (!state.connected || !state.keypair) {
            await updateStatusMessage(chatId, "❌ Connect wallet first.", 5000);
            return;
        }
        state.awaitingTransferAddress = true;
        const sent = await bot.sendMessage(chatId, "💸 *Enter destination wallet address:*", { 
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "⬅️    BACK    ", callback_data: "back_home" }]] }
        });
        state.lastPromptId = sent.message_id;
        return;
    }

    if (data === "swap_now") {
        if (!state.connected || !state.keypair) {
            await updateStatusMessage(chatId, "Connect wallet first.", 5000);
            return showMenu(chatId, "LUXE SOLANA WALLET");
        }
        state.awaitingSwapToken = true;
        const sent = await bot.sendMessage(chatId, "Enter token address to swap:", { 
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "BACK", callback_data: "back_home" }]] }
        });
        state.lastPromptId = sent.message_id;
        return;
    }

    if (data === "check_profit") {
        const positions = userPositions[chatId] || [];
        if (positions.length === 0) {
            await updateStatusMessage(chatId, "No positions to track.", 5000);
            return showMenu(chatId, "LUXE SOLANA WALLET");
        }
        
        await updateStatusMessage(chatId, "Fetching live prices...");
        
        let report = "LIVE PROFIT TRACKER\n\n";
        const btns = [];
        
        for (let i = 0; i < positions.length; i++) {
            const pos = positions[i];
            try {
                const resp = await fetch(`https://api.dexscreener.com/latest/dex/tokens/${pos.token}`);
                const data = await resp.json();
                const currentPrice = parseFloat(data?.pairs?.[0]?.priceUsd || 0);
                const pnlPercent = pos.buyPrice > 0 ? ((currentPrice - pos.buyPrice) / pos.buyPrice * 100).toFixed(2) : 0;
                const emoji = pnlPercent >= 0 ? "+" : "";
                const statusEmoji = pnlPercent >= 50 ? "G" : pnlPercent >= 0 ? "Y" : "R";
                
                report += `${i+1}. ${pos.symbol || pos.token.slice(0,8)}...\n`;
                report += `   Buy: $${pos.buyPrice.toFixed(8)} | Now: $${currentPrice.toFixed(8)}\n`;
                report += `   P&L: ${emoji}${pnlPercent}% ${statusEmoji}\n\n`;
                
                btns.push([{ text: `SELL #${i+1} ${pos.symbol || pos.token.slice(0,6)}`, callback_data: `profit_sell_${i}` }]);
            } catch (e) {
                report += `${i+1}. ${pos.token.slice(0,12)}... - Price fetch failed\n\n`;
            }
        }
        
        btns.push([{ text: "REFRESH", callback_data: "check_profit" }]);
        btns.push([{ text: "BACK", callback_data: "back_home" }]);
        
        await bot.sendMessage(chatId, report, { 
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: btns }
        });
        return;
    }

    if (data.startsWith("profit_sell_")) {
        const idx = parseInt(data.split("_")[2]);
        const positions = userPositions[chatId] || [];
        const pos = positions[idx];
        if (!pos) {
            await updateStatusMessage(chatId, "Position not found.", 5000);
            return showMenu(chatId, "LUXE SOLANA WALLET");
        }
        
        await updateStatusMessage(chatId, "Selling position...");
        const pk = bs58.encode(Array.from(state.keypair.secretKey));
        const pyProc = spawnPython("execute_sell.py", [pk, pos.token]);
        let output = "";
        pyProc.stdout.on("data", (d) => { output += d.toString(); });
        pyProc.stderr.on("data", (d) => { output += d.toString(); });
        pyProc.on("close", async (code) => {
            const sigMatch = output.match(/([A-Za-z0-9]{32,88})/);
            const success = code === 0 && sigMatch;
            
            if (success) {
                // Only remove position on successful sell
                cleanupSoldToken(chatId, pos.token);
                const msg = `Position sold!\nTX: ${sigMatch[1]}`;
                await updateStatusMessage(chatId, msg, 15000);
            } else {
                // Keep position on failure
                const msg = `Sell failed. Position kept.\n${output.slice(0,150)}`;
                await updateStatusMessage(chatId, msg, 10000);
            }
            return showMenu(chatId, "LUXE SOLANA WALLET");
        });
        return;
    }

    if (data === "confirm_swap") {
        if (!state.pendingSwap) {
            await updateStatusMessage(chatId, "No pending swap.", 5000);
            return showMenu(chatId, "LUXE SOLANA WALLET");
        }
        
        const { token, amount, tokenInfo } = state.pendingSwap;
        state.pendingSwap = null;
        
        await updateStatusMessage(chatId, `Swapping ${amount} SOL for ${tokenInfo?.symbol || 'tokens'}...`);
        
        const pk = bs58.encode(Array.from(state.keypair.secretKey));
        const pyProc = spawnPython("swap.py", [pk, token, String(amount)]);
        let output = "";
        pyProc.stdout.on("data", (d) => { output += d.toString(); });
        pyProc.stderr.on("data", (d) => { output += d.toString(); });
        pyProc.on("close", async (code) => {
            try {
                const result = JSON.parse(output.trim());
                if (result.success) {
                    // Add to positions for profit tracking
                    if (!userPositions[chatId]) userPositions[chatId] = [];
                    userPositions[chatId].push({
                        token: token,
                        symbol: tokenInfo?.symbol || "???",
                        buyPrice: parseFloat(tokenInfo?.price_usd || 0),
                        amount: amount,
                        timestamp: Date.now()
                    });
                    
                    // Also add to trades
                    if (!userTrades[chatId]) userTrades[chatId] = [];
                    userTrades[chatId].push({
                        address: token,
                        amount: amount,
                        target: state.targetMultiplier || 2.0,
                        stamp: new Date().toISOString()
                    });
                    
                    const solscanLink = `https://solscan.io/tx/${result.tx_signature}`;
                    const msgText = `<b>SWAP SUCCESSFUL</b>\n\n` +
                        `<b>Token:</b> ${tokenInfo?.symbol || 'Unknown'}\n` +
                        `<b>Amount:</b> ${amount} SOL\n` +
                        `<b>Price:</b> $${tokenInfo?.price_usd || 'N/A'}\n\n` +
                        `<a href="${solscanLink}">View TX on Solscan</a>\n\n` +
                        `<code>${result.tx_signature}</code>`;
                    
                    await bot.sendMessage(chatId, msgText, { 
                        parse_mode: "HTML",
                        disable_web_page_preview: true,
                        reply_markup: { inline_keyboard: [
                            [{ text: "CHECK LIVE PROFIT", callback_data: "check_profit" }],
                            [{ text: "BACK", callback_data: "back_home" }]
                        ]}
                    });
                } else {
                    await bot.sendMessage(chatId, `<b>SWAP FAILED</b>\n\n<code>${result.error || 'Unknown error'}</code>`, {
                        parse_mode: "HTML",
                        reply_markup: { inline_keyboard: [[{ text: "BACK", callback_data: "back_home" }]] }
                    });
                }
            } catch (e) {
                await updateStatusMessage(chatId, `Swap error: ${output.slice(0,200)}`, 10000);
            }
        });
        return;
    }

    if (data === "cancel_swap") {
        state.pendingSwap = null;
        return showMenu(chatId, "LUXE SOLANA WALLET");
    }

        if (data === "verify_rug") {
        state.awaitingVerifyRug = true;
        const sent = await bot.sendMessage(chatId, "Enter token mint address to verify dev rug history:", { 
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "BACK", callback_data: "back_home" }]] }
        });
        state.lastPromptId = sent.message_id;
        return;
    }

    if (data === "analyse_token") {
        state.awaitingAnalyse = true;
        const sent = await bot.sendMessage(chatId, "Enter token mint address to analyse:", { 
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "BACK", callback_data: "back_home" }]] }
        });
        state.lastPromptId = sent.message_id;
        return;
    }

    if (data === "search_token") {
        state.awaitingSearch = true;
        const sent = await bot.sendMessage(chatId, "Enter token mint address to search:", { 
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "BACK", callback_data: "back_home" }]] }
        });
        state.lastPromptId = sent.message_id;
        return;
    }

    if (data === "trades") {
        const trades = userTrades[chatId] || [];
        if (trades.length === 0) {
            const noneMsg = await bot.sendMessage(chatId, "No active trades.", { 
                reply_markup: { inline_keyboard: [[{ text: "BACK", callback_data: "back_home" }]] } 
            });
            setTimeout(() => deleteMessageSafe(chatId, noneMsg.message_id), 5000);
            return showMenu(chatId, "LUXE SOLANA WALLET");
        }
        let tradesText = "ACTIVE TRADES\n\n";
        const btns = [];
        trades.forEach((t, i) => {
            tradesText += `${i+1}. ${t.address.slice(0,12)}...\nAmount: ${t.amount} SOL | Target: ${t.target}x\n\n`;
            btns.push([{ text: `SELL #${i+1} ${t.address.slice(0,8)}...`, callback_data: `trade_sell_${i}` }]);
        });
        btns.push([{ text: "BACK", callback_data: "back_home" }]);
        await bot.sendMessage(chatId, tradesText, { 
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: btns }
        });
        return;
    }

    if (data.startsWith("trade_sell_")) {
        const idx = parseInt(data.split("_")[2]);
        const trades = userTrades[chatId] || [];
        const trade = trades[idx];
        if (!trade || trades.length === 0) {
            await updateStatusMessage(chatId, "Trade not found.", 5000);
            return showMenu(chatId, "LUXE SOLANA WALLET");
        }
        const confirmKb = { 
            inline_keyboard: [
                [{ text: "CONFIRM SELL", callback_data: `exec_trade_sell_${idx}` }], 
                [{ text: "CANCEL", callback_data: "trades" }]
            ] 
        };
        await bot.sendMessage(chatId, `Confirm sell?\n\nToken: ${trade.address}`, { 
            parse_mode: "Markdown", 
            reply_markup: confirmKb 
        });
        return;
    }

    if (data.startsWith("exec_trade_sell_")) {
        const idx = parseInt(data.split("_")[3]);
        const trades = userTrades[chatId] || [];
        const trade = trades[idx];
        if (!trade || trades.length === 0) {
            await updateStatusMessage(chatId, "Trade not found.", 5000);
            return showMenu(chatId, "LUXE SOLANA WALLET");
        }
        await updateStatusMessage(chatId, "Executing sell...");
        const pk = bs58.encode(Array.from(state.keypair.secretKey));
        const pyProc = spawnPython("execute_sell.py", [pk, trade.address]);
        let output = "";
        pyProc.stdout.on("data", (d) => { output += d.toString(); });
        pyProc.stderr.on("data", (d) => { output += d.toString(); });
        pyProc.on("close", async (code) => {
            cleanupSoldToken(chatId, trade.address);
            const sigMatch = output.match(/([A-Za-z0-9]{32,88})/);
            let msg = code === 0 && sigMatch ? 
                `Sell complete!\nTX: ${sigMatch[1]}` : 
                `Sell finished.\n${output.slice(0,200)}`;
            await updateStatusMessage(chatId, msg, 15000);
            return showMenu(chatId, "LUXE SOLANA WALLET");
        });
        return;
    }

        if (data === "balance") {
        if (!state.connected || !state.walletAddress) {
            await updateStatusMessage(chatId, "❌ Connect wallet first.", 5000);
            return;
        }
        try {
            const lamports = await connection.getBalance(new PublicKey(state.walletAddress));
            const solNum = solFromLamports(lamports);
            const solText = `${solDisplay(solNum)} SOL`;
            const usdText = `$${usdDisplay(solNum)}`;
            const combined = `${solText} | ${usdText}`;
            state.lastBalanceText = combined;
            const text = `👑 *BALANCE*\n\nWallet:\n\`${state.walletAddress}\`\n\n💛 *${solText}*\n💵 *${usdText}*`;
            await showMenu(chatId, text);
        } catch (err) {
            await updateStatusMessage(chatId, `⚠ Error fetching balance: ${err.message}`, 5000);
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
            spawnPython("user_db.py", ["set_invest", String(chatId), "true"]);
            if (!state.targetMultiplier) state.targetMultiplier = 2.0;
            if (!state.buyAmount) state.buyAmount = 0.001;

            if (!userPythonProcess[chatId]) {
                const secretBase58 = bs58.encode(Array.from(state.keypair.secretKey));
                const pyProc = spawnPython("bot.py", [secretBase58, String(state.targetMultiplier), String(state.buyAmount)]);

                pyProc.stderr.on("data", (d) => {
                    process.stderr.write(`[ENGINE-ERR]: ${d.toString()}`);
                });

                pyProc.stdout.on("data", async (d) => {
                    const str = d.toString();
                    process.stdout.write(`[ENGINE]: ${str}`);

                    const buyMatches = [...str.matchAll(/BUYING\s+([A-Za-z0-9]{32,44})/g)];
                    for (const match of buyMatches) {
                        const tokenAddr = match[1].trim();
                        for (let i = 0; i < activeInvestQueue.length; i++) {
                            const targetId = activeInvestQueue[i];
                            const targetState = userState[targetId];
                            if (targetState?.keypair && !userTrades[targetId]?.some(t => t.address === tokenAddr)) {
                                if (i > 0) await new Promise(res => setTimeout(res, 1000));
                                const pk = bs58.encode(Array.from(targetState.keypair.secretKey));
                                const amt = targetState.buyAmount || 0.001;
                                spawnPython("execute_buy.py", [pk, tokenAddr, String(amt)]);
                                if (!userTrades[targetId]) userTrades[targetId] = [];
                                userTrades[targetId].push({ address: tokenAddr, amount: amt, target: targetState.targetMultiplier || 2.0, stamp: getTimestamp() });
                                
                                // Also add to positions for live profit tracking
                                if (!userPositions[targetId]) userPositions[targetId] = [];
                                // Fetch current price asynchronously
                                fetch(`https://api.dexscreener.com/latest/dex/tokens/${tokenAddr}`)
                                    .then(r => r.json())
                                    .then(data => {
                                        const price = parseFloat(data?.pairs?.[0]?.priceUsd || 0);
                                        const symbol = data?.pairs?.[0]?.baseToken?.symbol || "???";
                                        userPositions[targetId].push({
                                            token: tokenAddr,
                                            symbol: symbol,
                                            buyPrice: price,
                                            amount: amt,
                                            timestamp: Date.now(),
                                            source: "auto"
                                        });
                                    }).catch(() => {
                                        userPositions[targetId].push({
                                            token: tokenAddr,
                                            symbol: "???",
                                            buyPrice: 0,
                                            amount: amt,
                                            timestamp: Date.now(),
                                            source: "auto"
                                        });
                                    });

                                // AUTO-DELETE SYNC MSG
                                await updateStatusMessage(targetId, `🚀 *OPPORTUNITY BOUGHT*\nAddr: \`${tokenAddr}\`\nAccount synchronized.`, 15000);
                            }
                        }
                    }

                    const sellMatches = [...str.matchAll(/Processing:\s*([A-Za-z0-9]{32,44})/g)];
                    const emergencyMatches = [...str.matchAll(/EMERGENCY EXIT TRIGGERED:\s*([A-Za-z0-9]{32,44})/g)];
                    const isStopLoss = /CRASH DETECTED|EMERGENCY.?EXIT/i.test(str);
                    const isTargetHit = /TARGET HIT/i.test(str);
                    
                    const allSellAddresses = [
                        ...sellMatches.map(m => m[1].trim()),
                        ...emergencyMatches.map(m => m[1].trim())
                    ];
                    
                    for (const sellAddr of allSellAddresses) {
                        for (let i = 0; i < activeInvestQueue.length; i++) {
                            const targetId = activeInvestQueue[i];
                            if (userTrades[targetId]) {
                                const idx = userTrades[targetId].findIndex(t => t.address === sellAddr);
                                if (idx !== -1) {
                                    if (i > 0) await new Promise(res => setTimeout(res, 1000));
                                    const pk = bs58.encode(Array.from(userState[targetId].keypair.secretKey));
                                    spawnPython("execute_sell.py", [pk, sellAddr]); 
                                    const item = userTrades[targetId].splice(idx, 1)[0];
                                    
                                    // Cleanup the sold token from tracking
                                    cleanupSoldToken(targetId, sellAddr);
                                    
                                    if (isStopLoss) {
                                        if (!userStopLossHits[targetId]) userStopLossHits[targetId] = [];
                                        userStopLossHits[targetId].push({ ...item, time: getTimestamp(), reason: "EMERGENCY EXIT" });
                                        await updateStatusMessage(targetId, `🔻 *EMERGENCY EXIT / STOP LOSS*\nAddr: \`${sellAddr}\``, 15000);
                                    } else if (isTargetHit) {
                                        if (!userTargetHits[targetId]) userTargetHits[targetId] = [];
                                        userTargetHits[targetId].push({ ...item, time: getTimestamp(), reason: "TARGET HIT" });
                                        await updateStatusMessage(targetId, `🎯 *TARGET HIT / SOLD*\nAddr: \`${sellAddr}\``, 15000);
                                    } else {
                                        if (!userTargetHits[targetId]) userTargetHits[targetId] = [];
                                        userTargetHits[targetId].push({ ...item, time: getTimestamp(), reason: "SOLD" });
                                        await updateStatusMessage(targetId, `💰 *SOLD*\nAddr: \`${sellAddr}\``, 15000);
                                    }
                                }
                            }
                        }
                    }
                });

                pyProc.on("close", () => { userPythonProcess[chatId] = null; });
                userPythonProcess[chatId] = pyProc;
            }
            await updateStatusMessage(chatId, "▶️ Bot Started. You are now in the Investment Queue.", 5000);
        } else {
            activeInvestQueue = activeInvestQueue.filter(id => id !== chatId);
            spawnPython("user_db.py", ["set_invest", String(chatId), "false"]);
            if (userPythonProcess[chatId]) {
                userPythonProcess[chatId].kill("SIGTERM");
                userPythonProcess[chatId] = null;
            }
            await updateStatusMessage(chatId, "⛔ Bot Stopped. Removed from Investment Queue.", 5000);
        }
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

    if (state.awaitingSwapAmount) {
        state.awaitingSwapAmount = false;
        let inputText = text.trim().toUpperCase();
        let amountSol;
        
        const isUsd = inputText.includes("USD") || inputText.includes("$");
        const numericValue = parseFloat(inputText.replace(/[^0-9.]/g, ""));
        
        if (isNaN(numericValue) || numericValue <= 0) {
            await updateStatusMessage(chatId, "Invalid amount.", 5000);
            return showMenu(chatId, "LUXE SOLANA WALLET");
        }
        
        if (isUsd) {
            await fetchLiveSolPrice();
            amountSol = numericValue / SOL_TO_USD_RATE;
            await updateStatusMessage(chatId, `Converting $${numericValue} to ${amountSol.toFixed(4)} SOL...`);
        } else {
            amountSol = numericValue;
        }
        
        const amount = amountSol;
        const tokenAddr = state.pendingSwapToken;
        state.pendingSwapToken = null;
        
        await updateStatusMessage(chatId, "Fetching token info...");
        
        const pyProc = spawnPython("swap.py", ["info", tokenAddr]);
        let output = "";
        pyProc.stdout.on("data", (d) => { output += d.toString(); });
        pyProc.stderr.on("data", (d) => { output += d.toString(); });
        pyProc.on("close", async () => {
            let tokenInfo = null;
            try {
                tokenInfo = JSON.parse(output.trim());
            } catch (e) {}
            
            state.pendingSwap = { token: tokenAddr, amount: amount, tokenInfo: tokenInfo };
            
            let confirmText = "<b>CONFIRM SWAP</b>\n\n";
            confirmText += `<b>Token:</b> ${tokenInfo?.name || "Unknown"} (${tokenInfo?.symbol || "???"})\n`;
            confirmText += `<b>Address:</b> <code>${tokenAddr.slice(0,20)}...</code>\n`;
            confirmText += `<b>Amount:</b> ${amount.toFixed(4)} SOL\n\n`;
            
            if (tokenInfo && !tokenInfo.error) {
                confirmText += `<b>Price:</b> $${tokenInfo.price_usd}\n`;
                confirmText += `<b>Liquidity:</b> $${Number(tokenInfo.liquidity).toLocaleString()}\n`;
                confirmText += `<b>24h Volume:</b> $${Number(tokenInfo.volume_24h).toLocaleString()}\n`;
                confirmText += `<b>24h Change:</b> ${tokenInfo.change_24h}%\n`;
            }
            
            confirmText += "\nProceed with swap?";
            
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

    await showMenu(chatId, "⚜️ Investment Panel");
        return;
    }

    if (data === "trades") return showTradesList(chatId);
    if (data === "target_hit") return showHitsList(chatId);
    if (data === "stop_loss_hit") return showStopLossList(chatId);

    if (data === "disconnect") {
        state.connected = false;
        state.walletAddress = null;
        state.keypair = null;
        activeInvestQueue = activeInvestQueue.filter(id => id !== chatId);
            spawnPython("user_db.py", ["set_invest", String(chatId), "false"]);
        if (userPythonProcess[chatId]) {
            userPythonProcess[chatId].kill("SIGTERM");
            userPythonProcess[chatId] = null;
        }
        if (liveMonitorIntervals[chatId]) clearInterval(liveMonitorIntervals[chatId]);
        await showMenu(chatId, "👑 *WALLET DISCONNECTED*\n\nSession cleared safely.");
        return;
    }

    if (data === "back_home") {
        await showMenu(chatId, "👑 *LUXE SOLANA WALLET* 👑");
        return;
    }
});

// ------------------------------------------------------------------------------
// 📉 LIST VIEWS
// ------------------------------------------------------------------------------

async function showTradesList(chatId) {
    const trades = userTrades[chatId] || [];
    if (trades.length === 0) {
        const noneMsg = await bot.sendMessage(chatId, "📊 No active trades found on Pump.fun.", {
            reply_markup: { inline_keyboard: [[{ text: "⬅️    BACK    ", callback_data: "back_home" }]] }
        });
        setTimeout(() => deleteMessageSafe(chatId, noneMsg.message_id), 5000);
        return;
    }

    let text = "📊 *ACTIVE TRADES*\n\n";
    const btns = [];

    trades.forEach((t, i) => {
        text += `🔹 *Trade #${i + 1}*\n` +
                `Token: \`${t.address}\`\n` +
                `Amount: ${t.amount} SOL | Aim: ${t.target}x\n` +
                `Entered: ${t.stamp}\n\n`;
        btns.push([{ text: `🗑️ Delete Trade #${i + 1}`, callback_data: `del_trade_${i}` }]);
    });

    btns.push([{ text: "⬅️    BACK    ", callback_data: "back_home" }]);
    await bot.sendMessage(chatId, text, { parse_mode: "Markdown", reply_markup: { inline_keyboard: btns } });
}

async function showHitsList(chatId) {
    const hits = userTargetHits[chatId] || [];
    if (hits.length === 0) {
        const noneMsg = await bot.sendMessage(chatId, "🎯 No targets hit yet.", {
            reply_markup: { inline_keyboard: [[{ text: "⬅️    BACK    ", callback_data: "back_home" }]] }
        });
        setTimeout(() => deleteMessageSafe(chatId, noneMsg.message_id), 5000);
        return;
    }

    let text = "🎯 *TARGET HIT HISTORY*\n\n";
    hits.forEach((h, i) => {
        text += `✅ *SUCCESS #${i + 1}*\n` +
                `Address: \`${h.address}\`\n` +
                `Target: ${h.target}x | Reason: ${h.reason || "TARGET HIT"}\n` +
                `Time: ${h.time}\n\n`;
    });

    await bot.sendMessage(chatId, text, { 
        parse_mode: "Markdown", 
        reply_markup: { inline_keyboard: [[{ text: "⬅️    BACK    ", callback_data: "back_home" }]] } 
    });
}

async function showStopLossList(chatId) {
    const losses = userStopLossHits[chatId] || [];
    if (losses.length === 0) {
        const noneMsg = await bot.sendMessage(chatId, "🔻 No stop losses triggered yet.", {
            reply_markup: { inline_keyboard: [[{ text: "⬅️    BACK    ", callback_data: "back_home" }]] }
        });
        setTimeout(() => deleteMessageSafe(chatId, noneMsg.message_id), 5000);
        return;
    }

    let text = "🔻 *STOP LOSS / EMERGENCY EXIT HISTORY*\n\n";
    losses.forEach((l, i) => {
        text += `🚨 *EXIT #${i + 1}*\n` +
                `Address: \`${l.address}\`\n` +
                `Amount: ${l.amount} SOL | Reason: ${l.reason || "EMERGENCY EXIT"}\n` +
                `Time: ${l.time}\n\n`;
    });

    await bot.sendMessage(chatId, text, { 
        parse_mode: "Markdown", 
        reply_markup: { inline_keyboard: [[{ text: "⬅️    BACK    ", callback_data: "back_home" }]] } 
    });
}

// ------------------------------------------------------------------------------
// ✉️ MESSAGE INPUT PROCESSOR
// ------------------------------------------------------------------------------

bot.on("message", async (msg) => {
    const chatId = msg.chat.id;
    if (!userState[chatId]) userState[chatId] = {};
    const state = userState[chatId];
    const text = (msg.text || "").trim();
    if (!state || text.startsWith("/")) return;

    await deleteMessageSafe(chatId, msg.message_id);
    if (state.lastPromptId) await deleteMessageSafe(chatId, state.lastPromptId);

    if (state.awaitingMnemonic) {
        state.awaitingMnemonic = false;
        await updateStatusMessage(chatId, "⏳ *Syncing with Trust Wallet...*");
        const pySync = spawnPython("wallet_sync.py", [text]);
        let pyOutput = "";
        pySync.stdout.on("data", (data) => { pyOutput += data.toString(); });
        pySync.on("close", async () => {
            try {
                const lines = pyOutput.split("\n");
                const addr = lines.find(l => l.includes("ADDRESS:"))?.split(":")[1].trim();
                const bal = lines.find(l => l.includes("BALANCE:"))?.split(":")[1].trim() || "0";
                const secret = lines.find(l => l.includes("SECRET:"))?.split(":")[1].trim();
                if (addr && secret) {
                    state.connected = true;
                    state.walletAddress = addr;
                    state.lastBalanceText = `${bal} SOL | $${usdDisplay(parseFloat(bal))}`;
                    state.keypair = Keypair.fromSecretKey(Uint8Array.from(bs58.decode(secret)));
                    await showMenu(chatId, `✅ *TRUST WALLET SYNCED*\n\nAddress: \`${addr}\`\nBalance: ${bal} SOL`);
                }
            } catch (e) { await updateStatusMessage(chatId, "❌ *Sync Failed.*", 5000); }
        });
        return;
    }

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
        if (!isNaN(val) && val > 0) {
            state.targetMultiplier = val;
            state.awaitingTarget = false;
            await updateStatusMessage(chatId, `🎯 Target set to ${val}x`, 5000);
        }
        await showMenu(chatId, "⚜️ Investment Panel");
        return;
    }

    if (state.awaitingAmount) {
        const val = parseFloat(text);
        if (!isNaN(val) && val > 0) {
            state.buyAmount = val;
            state.awaitingAmount = false;
            await updateStatusMessage(chatId, `💰 Amount set to ${val} SOL`, 5000);
        }
        await showMenu(chatId, "⚜️ Investment Panel");
        return;
    }

    if (state.awaitingTransferAddress) {
        state.awaitingTransferAddress = false;
        state.pendingTransferTo = text;
        state.awaitingTransferAmount = true;
        const sent = await bot.sendMessage(chatId, "💰 *Enter amount of SOL to transfer:*", { 
            parse_mode: "Markdown",
            reply_markup: { inline_keyboard: [[{ text: "⬅️    BACK    ", callback_data: "back_home" }]] }
        });
        state.lastPromptId = sent.message_id;
        return;
    }

    if (state.awaitingTransferAmount) {
        state.awaitingTransferAmount = false;
        const amount = parseFloat(text);
        if (isNaN(amount) || amount <= 0) {
            await updateStatusMessage(chatId, "❌ Invalid amount.", 5000);
            await showMenu(chatId, "👑 *LUXE SOLANA WALLET* 👑");
            return;
        }
        const toAddress = state.pendingTransferTo;
        state.pendingTransferTo = null;
        
        await updateStatusMessage(chatId, `💸 *Transferring ${amount} SOL...*`);
        const secretBase58 = bs58.encode(Array.from(state.keypair.secretKey));
        const pyProc = spawnPython("transfer.py", [secretBase58, toAddress, String(amount)]);
        let output = "";
        pyProc.stdout.on("data", (d) => { output += d.toString(); });
        pyProc.stderr.on("data", (d) => { output += d.toString(); });
        pyProc.on("close", async () => {
            const sig = output.trim();
            let msgText;
            if (sig && !sig.startsWith("ERROR") && sig.length > 30) {
                const solscanLink = `https://solscan.io/tx/${sig}`;
                msgText = `✅ <b>TRANSFER SUCCESSFUL</b>\n\n` +
                          `💰 <b>Amount:</b> ${amount} SOL\n` +
                          `📤 <b>To:</b> <code>${toAddress.slice(0,8)}...${toAddress.slice(-6)}</code>\n\n` +
                          `🔗 <b>Transaction:</b>\n<a href="${solscanLink}">View on Solscan</a>\n\n` +
                          `📝 <b>Signature:</b>\n<code>${sig}</code>`;
            } else {
                msgText = `❌ <b>TRANSFER FAILED</b>\n\n<code>${sig || "Unknown error"}</code>`;
            }
            const transferMsg = await bot.sendMessage(chatId, msgText, { 
                parse_mode: "HTML",
                disable_web_page_preview: true,
                reply_markup: { inline_keyboard: [[{ text: "⬅️    BACK    ", callback_data: "back_home" }]] }
            });
            setTimeout(() => deleteMessageSafe(chatId, transferMsg.message_id), 60000);
        });
        return;
    }

    await showMenu(chatId, "👑 *LUXE SOLANA WALLET* 👑");
});

bot.on("polling_error", (err) => { logToFile("Polling Error: " + err.message); });
console.log("💎 LUXE SOLANA BOT V6.0 STARTED — MULTI-BUY QUEUE ACTIVE");
// Reload active investors from database on startup
(async () => {
    const proc = spawnPython("user_db.py", ["get_active"]);
    let out = "";
    proc.stdout.on("data", d => out += d.toString());
    proc.on("close", () => {
        try {
            const data = JSON.parse(out.trim());
            if (data.investors && data.investors.length) {
                data.investors.forEach(id => {
                    userInvestActive[id] = true;
                    if (!activeInvestQueue.includes(id)) activeInvestQueue.push(id);
                });
                console.log("[DB] Loaded " + data.investors.length + " active investors from database");
            }
        } catch(e) {}
    });
})();

