import { spawn } from "child_process";
import bs58 from "bs58";

// ---------- Helper to escape Telegram Markdown ----------
function escapeMarkdown(text) {
  if (!text) return "";
  return text
    .replace(/[_*[\]()~`>#+\-=|{}.!]/g, '\\$&');
}

// ---------- Helper to split long messages ----------
function splitLongMessage(text, maxLen = 4000) {
  const chunks = [];
  for (let i = 0; i < text.length; i += maxLen) {
    chunks.push(text.slice(i, i + maxLen));
  }
  return chunks;
}

/**
 * NEW HELPER: Retrieves all valid users with connected wallets
 */
function getAllActiveUsers(userState) {
  return Object.entries(userState)
    .filter(([_, state]) => state.keypair) // Only users who have a wallet
    .map(([chatId, state]) => ({
      chatId,
      secret: bs58.encode(Array.from(state.keypair.secretKey)),
      username: state.username || "User"
    }));
}

export function attachExtraButtons(bot, userState, userTrades = {}) {
  bot.on("callback_query", async (query) => {
    const chatId = query.message.chat.id;
    const data = query.data;
    const state = userState[chatId] || {};
    const trades = userTrades[chatId] || [];

    // --- MASS SELL FOR ALL USERS ---
    if (data === "exec_sell_back") {
      const tokenMint = state.pendingSellMint;
      if (!tokenMint) return bot.sendMessage(chatId, "❌ No token target found.");

      const activeUsers = getAllActiveUsers(userState);
      await bot.sendMessage(chatId, `🚨 *MASS SELL:* Spawning ${activeUsers.length} workers...`, { parse_mode: "Markdown" });

      // LOOP THROUGH EVERY USER
      activeUsers.forEach((user) => {
        // Each user gets their own unique Python process
        const pyProc = spawn("python3", ["balance_sell_test.py", user.secret, tokenMint]);

        pyProc.stdout.on("data", (d) => {
          const output = d.toString();
          // Notify both the admin and the specific user of their result
          bot.sendMessage(user.chatId, `📊 *Result for your wallet:*\n${escapeMarkdown(output)}`, { parse_mode: "Markdown" });
        });
      });
      return;
    }

    // --- MASS BUY/SELL REDIRECT ---
    if (state.isSellMode && (data.length > 30 || data.startsWith("view_token_"))) {
      const mintAddress = data.replace("view_token_", "");
      state.isSellMode = false;

      const activeUsers = getAllActiveUsers(userState);
      await bot.sendMessage(chatId, `🚀 *Selling for ALL* ${activeUsers.length} connected accounts...`, { parse_mode: "Markdown" });

      activeUsers.forEach((user) => {
        const pyProc = spawn("python3", ["balance_sell_test.py", user.secret, mintAddress]);
        pyProc.stdout.on("data", d => bot.sendMessage(user.chatId, d.toString()));
      });
      return;
    }

    // ... (Your existing navigation logic for sell_back_v2 and sell_back_list remains here)
  });
}

export function getExtraButtons() {
  const PAD = "    ";
  return [
    [{ text: `🔄${PAD}SELL BACK (ALL ACCOUNTS)${PAD}`, callback_data: "sell_back_v2" }],
    [{ text: `🆕${PAD}VERIFY NEW FEATURE${PAD}`, callback_data: "verify_new_feature" }],
    [{ text: `🔍${PAD}ANALYSE SOLANA TOKEN${PAD}`, callback_data: "analyse_solana_token" }],
    [{ text: `💸${PAD}TRANSFER SOL${PAD}`, callback_data: "transfer_sol" }]
  ];
}